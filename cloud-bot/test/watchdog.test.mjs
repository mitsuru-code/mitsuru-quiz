import { test } from 'node:test';
import assert from 'node:assert';
import { checkStale, nextSlotEpochAfter, WATCHDOG_THRESHOLD_MIN } from '../watchdog.mjs';

// JSTの特定時刻のepoch msを作るヘルパー（post-quiz.test.mjsと同じ方式。基準日: 2026-08-06・木曜日）
function jstTime(hh, mm, day = 6) {
  return Date.UTC(2026, 7, day, hh - 9, mm, 0);
}

test('nextSlotEpochAfter: 同じ日の次のスロットを返す', () => {
  const next = nextSlotEpochAfter(jstTime(6, 0)); // 6時台の次は7時台
  assert.strictEqual(new Date(next + 9 * 3600000).getUTCHours(), 7);
});

test('nextSlotEpochAfter: 最終スロット(20時台)の次は翌日の最初のスロット(5時台)に繰り上がる', () => {
  const next = nextSlotEpochAfter(jstTime(20, 0));
  const jst = new Date(next + 9 * 3600000);
  assert.strictEqual(jst.getUTCHours(), 5);
  assert.strictEqual(jst.getUTCDate(), 7); // 翌日
});

test('checkStale: 直近スロットが期限内に投稿されていれば正常', () => {
  const state = { lastSlotFulfilledEpoch: jstTime(6, 0) }; // 6時台の豆知識を消化済み
  const now = jstTime(7, 30); // 次の7時台の解禁(7:45)前
  const r = checkStale(now, state);
  assert.strictEqual(r.stale, false);
});

// 2026-08-06の実際の事故: GitHub Actions側の障害でcronが3時間以上まったく起動せず、
// 朝ブリーフィングが投稿されないまま誰も気づけなかった
test('checkStale: 次のスロットがしきい値を超えて未消化なら異常（実際の事故の再現）', () => {
  const state = { lastSlotFulfilledEpoch: jstTime(20, 0, 5) }; // 前日20時台までは正常に消化済み
  const now = jstTime(9, 0); // 翌9:00。5時台のブリーフィングが解禁(5:45)から3時間以上未消化
  const r = checkStale(now, state);
  assert.strictEqual(r.stale, true);
  assert.strictEqual(r.nextSlotHour, 5);
  assert.ok(r.delayMin >= WATCHDOG_THRESHOLD_MIN);
});

test('checkStale: しきい値未満の遅延はまだ異常としない（通常のcron遅延を誤検知しない）', () => {
  const state = { lastSlotFulfilledEpoch: jstTime(20, 0, 5) };
  const now = jstTime(6, 30, 6); // 5時台の解禁(5:45)から45分。キャッチアップの通常範囲内
  const r = checkStale(now, state);
  assert.strictEqual(r.stale, false);
});

// 長時間の障害中でも、参照するスロットを固定して見続けるため遅延が単調に伸び続けることを確認する
// （本体のpickDueSlotをそのまま転用すると、参照スロットが1時間おきに切り替わって遅延が
// 60分前後にリセットされ、検知が点滅してしまう）
test('checkStale: 障害が長引いても遅延は単調に増加し続ける（点滅しない）', () => {
  const state = { lastSlotFulfilledEpoch: jstTime(20, 0, 5) };
  const delays = [jstTime(6, 30, 6), jstTime(8, 30, 6), jstTime(10, 30, 6), jstTime(12, 30, 6)]
    .map(now => checkStale(now, state).delayMin);
  for (let i = 1; i < delays.length; i++) {
    assert.ok(delays[i] > delays[i - 1], `遅延が減っている: ${delays.join(', ')}`);
  }
});

// 20時台の振り返り→翌5時台のブリーフィングは番組表上、最大9時間空く（唯一の長い夜間ギャップ）。
// 固定しきい値で「最後の投稿からN分」を見る素朴な実装だと、この夜間ギャップで毎晩誤検知する
test('checkStale: 20時台→翌5時台の夜間ギャップ（最大9時間）を誤検知しない', () => {
  const state = { lastSlotFulfilledEpoch: jstTime(20, 5, 5) }; // 20時台の振り返りを20:05に投稿
  const now = jstTime(4, 30, 6); // 翌4:30（20時台の投稿から8時間以上経過だが、5時台はまだ解禁前）
  const r = checkStale(now, state);
  assert.strictEqual(r.stale, false);
});

test('checkStale: lastSlotFulfilledEpochが無い古いstateでもlastPostedAtで近似して動く', () => {
  const state = { lastPostedAt: jstTime(20, 0, 5) }; // 移行前のstate.json（新フィールド無し）
  const now = jstTime(6, 0);
  const r = checkStale(now, state);
  assert.strictEqual(r.stale, false);
});

test('checkStale: しきい値はカスタマイズできる', () => {
  const state = { lastSlotFulfilledEpoch: jstTime(20, 0, 5) };
  const now = jstTime(6, 30, 6); // 5時台の解禁(5:45)から45分
  assert.strictEqual(checkStale(now, state, 30).stale, true, 'しきい値を30分にすれば45分遅延は異常');
  assert.strictEqual(checkStale(now, state, 60).stale, false, 'しきい値を60分にすれば45分遅延はまだ正常');
});
