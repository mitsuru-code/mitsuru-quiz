import { test } from 'node:test';
import assert from 'node:assert';
import {
  jstDateKey,
  jstDateLabel,
  findDueCheckpoint,
  stripMarkdown,
  safeSlice,
  scheduleFollowUps,
  assertValidPostText,
} from '../post-quiz.mjs';

// JSTの特定時刻のepoch msを作るヘルパー（基準日: 2026-07-21・火曜日）
function jstTime(hh, mm, day = 21) {
  return Date.UTC(2026, 6, day, hh - 9, mm, 0);
}

test('jstDateLabel: 正しい日付・曜日ラベルを返す', () => {
  // 実際に事故が起きた時刻（2026-07-21 05:17 JST、本来は火曜日）
  assert.strictEqual(jstDateLabel(jstTime(5, 17)), '2026年7月21日火曜日');
});

test('jstDateKey: JSTの日付キー(YYYY-MM-DD)を返す', () => {
  assert.strictEqual(jstDateKey(jstTime(5, 17)), '2026-07-21');
  // JST 0:30は前日UTCの15:30。日付境界をまたいでも正しくJST日付になること
  assert.strictEqual(jstDateKey(jstTime(0, 30)), '2026-07-21');
});

test('stripMarkdown: **太字**を平文に変換する（実際のバグの再現）', () => {
  const r = stripMarkdown('**Q1. 米軍とイランが再び交戦。最新の状況は？**\nA: 精密攻撃を実施。');
  assert.ok(!r.includes('**'));
  assert.ok(r.startsWith('Q1. 米軍とイランが再び交戦'));
});

test('stripMarkdown: 独立行の"---"を罫線文字に変換する', () => {
  const r = stripMarkdown('あいさつ文\n\n---\n\nQ1. 本文');
  assert.ok(!r.includes('---'));
  assert.ok(r.includes('─'.repeat(21)));
});

test('stripMarkdown: URL中のハイフンなど独立行でないものは変換しない', () => {
  const r = stripMarkdown('詳しくは https://example.com/a--b--c を参照');
  assert.strictEqual(r, '詳しくは https://example.com/a--b--c を参照');
});

test('safeSlice: 絵文字の直前で切れるケースを安全に処理する（実際の事故の再現）', () => {
  // 39文字 + 🐹（サロゲートペア）= 41コード単位。素のslice(0,40)だと孤立サロゲートが残る
  const text = 'あ'.repeat(39) + '🐹';
  const fixed = safeSlice(text, 40);
  assert.strictEqual(fixed, 'あ'.repeat(39)); // 絵文字ごと落として孤立サロゲートを作らない
});

test('safeSlice: サロゲート境界に関係ない通常ケースは従来通り', () => {
  const text = 'あいうえお'.repeat(20);
  assert.strictEqual(safeSlice(text, 40), text.slice(0, 40));
});

test('safeSlice: maxLenより短い文字列はそのまま返す', () => {
  const text = 'あいうえお🐹';
  assert.strictEqual(safeSlice(text, 100), text);
});

test('assertValidPostText: 孤立サロゲートを含む文字列は例外を投げる', () => {
  const bad = 'あ'.repeat(39) + '\ud83d'; // 高サロゲート単体
  assert.throws(() => assertValidPostText(bad, jstTime(5, 17)), /孤立サロゲート/);
});

test('assertValidPostText: 正常な文字列（絵文字含む）はエラーにならない', () => {
  assert.doesNotThrow(() => assertValidPostText('おはようございます🐹 今日もいい天気', jstTime(5, 17)));
});

test('assertValidPostText: 実際の日付と食い違う曜日表記は例外を投げる（実際の事故の再現）', () => {
  // 2026-07-21は火曜日なのに「月曜日です」と書かれているケース
  const bad = '今朝の通勤ブリーフィング、月曜日です。週明け早々……';
  assert.throws(() => assertValidPostText(bad, jstTime(5, 17)), /曜日表記/);
});

test('assertValidPostText: 実際の日付と一致する曜日表記は許可される', () => {
  const ok = '今朝の通勤ブリーフィング、火曜日です。';
  assert.doesNotThrow(() => assertValidPostText(ok, jstTime(5, 17)));
});

test('assertValidPostText: 曜日への言及が無い文章はチェック対象外', () => {
  assert.doesNotThrow(() => assertValidPostText('速報：中東情勢が緊迫化しています', jstTime(5, 17)));
});

test('assertValidPostText: 本文途中の別日付への曜日言及は誤検知しない（未来の予定への正当な言及）', () => {
  // 冒頭は今日(火曜日)の話題で始まり、本文の途中（先頭80文字より後）で別の日
  // （決勝は来週日曜日）に触れるケース。これは正当な内容なのでエラーにしてはいけない
  const text = '火曜日の朝です。'.padEnd(100, '　') + 'なお決勝は来週の日曜日に開催されます。';
  assert.doesNotThrow(() => assertValidPostText(text, jstTime(5, 17)));
});

test('findDueCheckpoint: ちょうどの時刻でヒットする', () => {
  const cp = findDueCheckpoint(jstTime(9, 30), []);
  assert.strictEqual(cp.hm, '09:30');
  assert.strictEqual(cp.fallback, 'quiz');
});

test('findDueCheckpoint: 猶予時間内（cron遅延を想定した20分後）でもヒットする', () => {
  const cp = findDueCheckpoint(jstTime(9, 50), []);
  assert.strictEqual(cp.hm, '09:30');
});

test('findDueCheckpoint: 猶予切れの古いチェックポイントは飛ばして次にヒットする', () => {
  const cp = findDueCheckpoint(jstTime(10, 20), []);
  assert.strictEqual(cp.hm, '10:00');
});

test('findDueCheckpoint: 深夜2:00/4:00はforceArticle=trueでヒットする', () => {
  assert.strictEqual(findDueCheckpoint(jstTime(2, 5), []).forceArticle, true);
  assert.strictEqual(findDueCheckpoint(jstTime(4, 0), []).forceArticle, true);
});

test('findDueCheckpoint: 処理済み(doneKeys)のチェックポイントは再ヒットしない', () => {
  const todayKey = jstDateKey(jstTime(9, 30));
  const cp = findDueCheckpoint(jstTime(9, 40), [`${todayKey}_09:30`]);
  assert.strictEqual(cp, null);
});

test('findDueCheckpoint: どのチェックポイントにも該当しない時刻はnull', () => {
  assert.strictEqual(findDueCheckpoint(jstTime(20, 0), []), null);
});

test('scheduleFollowUps: followUp=falseなら何も積まない', () => {
  const state = {};
  scheduleFollowUps(state, 'h', 't', 1000, false);
  assert.strictEqual(state.breakingFollowUps, undefined);
});

test('scheduleFollowUps: followUp=trueなら常に30分後の1件のみ積む', () => {
  const state = {};
  const now = 1_000_000;
  scheduleFollowUps(state, 'h', 't', now, true);
  assert.strictEqual(state.breakingFollowUps.length, 1);
  assert.strictEqual(state.breakingFollowUps[0].dueAt, now + 30 * 60000);
  assert.strictEqual(state.breakingFollowUps[0].stageLabel, '30分後');
});
