// ============================================================
// クラウドBotの生存監視（デッドマン・スイッチ）
//
// post-quiz.mjs（本体）の「失敗をIssueで通知」ステップは、ワークフローが実際に実行され、
// その中のどこかのステップが失敗した場合しか動かない。2026-08-06のGitHub Actions大規模
// 障害（ホストランナーを確保できずジョブが1ステップも実行されないまま終了する）のように、
// ワークフローそのものが起動できない場合は本体側の通知ステップも同様に実行されないため、
// 3時間以上投稿が止まっても誰にも気づけなかった。
//
// このスクリプトは cloud-bot.yml（本体）とは別のワークフロー・別のcronから独立して動く。
// Anthropic/X APIのSecretsを一切使わず、state.jsonを読むだけで判定する。
//
// 判定は「直近に実際に消化したスロット(state.lastSlotFulfilledEpoch)の次に来るはずの
// スロットが、解禁時刻からどれだけ経過しているか」で行う。本体のpickDueSlotは「今どのスロット
// を投稿すべきか」（現在スロットとその1つ前まで、1時間程度で入れ替わる）を決めるための関数で、
// 経過時間がしきい値をまたぐたびに参照スロットが切り替わって遅延が60分前後にリセットされて
// しまうため、そのまま監視に転用すると本当に数時間止まっていても検知が点滅してしまう。
// 監視に必要なのは「最後に消化したスロットの次」を固定して見続ける、単調に伸びる遅延なので、
// ここでは専用に計算する。20時台の振り返り→翌5時台のブリーフィングという番組表上唯一の
// 長い夜間ギャップ（最大9時間）でも、まだ解禁前なので誤検知しない
// ============================================================
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { SLOT_PROFILES, releaseMinOf, jstHourOf } from './post-quiz.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const STATE_FILE = path.join(__dirname, 'state.json');
const POST_SLOTS = Object.keys(SLOT_PROFILES).map(Number).sort((a, b) => a - b);

// 解禁から何分経っても未消化なら異常とみなすか。
// スロットのキャッチアップ猶予(本体の既定360分)より十分短く、かつcronの通常の遅延
// （15分おきトリガーが混雑で間引かれる分の揺らぎ）では誤検知しない値にしてある
export const WATCHDOG_THRESHOLD_MIN = 90;

// afterEpoch（=直近に消化したスロットのepoch）の次に来る、番組表上のスロットのepochを返す。
// 今日に残っていなければ翌日の最初のスロットに繰り上がる（スロットは毎日循環するので必ず見つかる）
export function nextSlotEpochAfter(afterEpoch) {
  const jst = new Date(afterEpoch + 9 * 3600 * 1000);
  const hour = jst.getUTCHours();
  const nextHour = POST_SLOTS.find(h => h > hour);
  if (nextHour !== undefined) {
    return Date.UTC(jst.getUTCFullYear(), jst.getUTCMonth(), jst.getUTCDate(), nextHour - 9, 0, 0);
  }
  return Date.UTC(jst.getUTCFullYear(), jst.getUTCMonth(), jst.getUTCDate() + 1, POST_SLOTS[0] - 9, 0, 0);
}

// 「実際に消化したスロットのepoch」の次のスロットの解禁時刻(slotEpoch + releaseMin分)を返す
export function nextSlotReleaseEpoch(afterEpoch) {
  const next = nextSlotEpochAfter(afterEpoch);
  return next + releaseMinOf(jstHourOf(next)) * 60000;
}

export function checkStale(now, state, thresholdMin = WATCHDOG_THRESHOLD_MIN) {
  const lastFulfilled = (state.lastSlotFulfilledEpoch !== undefined && state.lastSlotFulfilledEpoch !== null)
    ? state.lastSlotFulfilledEpoch
    : (state.lastPostedAt || 0);
  const nextSlot = nextSlotEpochAfter(lastFulfilled);
  const releaseEpoch = nextSlotReleaseEpoch(lastFulfilled);
  const delayMin = Math.round((now - releaseEpoch) / 60000);
  const stale = delayMin >= thresholdMin;
  return { stale, delayMin, nextSlotHour: jstHourOf(nextSlot), kind: (SLOT_PROFILES[jstHourOf(nextSlot)] || {}).kind };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const now = parseInt(process.env.NOW_MS || '', 10) || Date.now(); // NOW_MSはテスト用フック
  const state = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
  const result = checkStale(now, state);
  console.log(`⏰ 次に消化すべきスロット: ${result.nextSlotHour}時台(${result.kind}) / 解禁からの経過: ${result.delayMin}分`);
  if (result.stale) {
    console.log(`🔇 ${result.delayMin}分間、投稿が確認できません（しきい値${WATCHDOG_THRESHOLD_MIN}分）`);
    process.exitCode = 1;
  } else {
    console.log('✅ 正常範囲内です');
  }
}
