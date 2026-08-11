import { test } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  loadCoveredTopics,
  buildTopicPrompt,
  parseTopics,
  topicPlanFor,
  buildFactPrompt,
  detectProseLeak,
  formatIssueBody,
  TOPICS_PER_SHEET,
} from '../material.mjs';

function tempStock(articles) {
  const p = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'stock-')), 'trivia-stock.json');
  fs.writeFileSync(p, JSON.stringify(articles), 'utf8');
  return p;
}

test('loadCoveredTopics: 各記事の1行目だけを既出テーマとして集める', () => {
  const p = tempStock([
    '雷までの距離は、数を数えれば分かります\n\n光は一瞬で届きますが…',
    '鏡は左右を反転していません🐹\n\n上下はそのままなのに…',
  ]);
  assert.deepStrictEqual(loadCoveredTopics(p), [
    '雷までの距離は、数を数えれば分かります',
    '鏡は左右を反転していません🐹',
  ]);
});

test('loadCoveredTopics: ストックが読めなくても落ちない（素材配信を止めない）', () => {
  assert.deepStrictEqual(loadCoveredTopics('/does/not/exist.json'), []);
});

test('loadCoveredTopics: 空行だけの要素は除外する', () => {
  const p = tempStock(['ちゃんとした記事\n\n本文', '', '   ']);
  assert.deepStrictEqual(loadCoveredTopics(p), ['ちゃんとした記事']);
});

test('buildTopicPrompt: 既出テーマを重複禁止リストとして渡す', () => {
  const prompt = buildTopicPrompt(['鏡は左右を反転していません', '紙は7回しか折れません']);
  assert.ok(prompt.includes('- 鏡は左右を反転していません'));
  assert.ok(prompt.includes('- 紙は7回しか折れません'));
  assert.ok(prompt.includes('重複禁止'));
});

test('buildTopicPrompt: trivia-style.mdの禁止話題をプロンプトに含める', () => {
  const prompt = buildTopicPrompt([]);
  for (const banned of ['政治', '宗教', '健康効能', '薬機法', '速報ニュース']) {
    assert.ok(prompt.includes(banned), `禁止話題「${banned}」がプロンプトに無い`);
  }
});

test('parseTopics: 番号や記号が付いていても剥がして取り出す', () => {
  const raw = [
    '1. コーヒーの脱カフェイン製法 / 水を使う製法の原理',
    '- 信号機の青 / 実際には緑に近い色である理由',
    '• 畳のへり / 踏んではいけないとされる理由',
  ].join('\n');
  assert.deepStrictEqual(parseTopics(raw), [
    'コーヒーの脱カフェイン製法 / 水を使う製法の原理',
    '信号機の青 / 実際には緑に近い色である理由',
    '畳のへり / 踏んではいけないとされる理由',
  ]);
});

test('parseTopics: 前置きや空行が混ざっても件数どおりに絞る', () => {
  const raw = [
    'はい、承知しました。',
    '',
    '畳のへり / 踏んではいけないとされる理由',
    '信号機の青 / 実際には緑に近い色である理由',
    'コーヒーの脱カフェイン / 水を使う製法の原理',
    '振り子の等時性 / 振れ幅によらず周期が一定になる理由',
  ].join('\n');
  const topics = parseTopics(raw);
  assert.strictEqual(topics.length, TOPICS_PER_SHEET, '上限件数まで絞るはず');
  assert.ok(!topics.some(t => t.includes('承知')), 'スラッシュの無い前置きは落ちるはず');
});

test('topicPlanFor: スラッシュの左側（テーマ名）だけを検索クエリにする', () => {
  const plan = topicPlanFor(['コーヒーの脱カフェイン製法 / 水を使う製法の原理']);
  assert.deepStrictEqual(plan.queries, ['コーヒーの脱カフェイン製法']);
});

// 恒久ネタなので topic:'news' で引くと当日の記事しか返らず、仕組みを解説した定説のページが落ちる
test('topicPlanFor: 検索は general（時事ニュース検索ではない）', () => {
  assert.strictEqual(topicPlanFor(['畳のへり / 由来']).topic, 'general');
});

test('topicPlanFor: テーマが無ければnullを返す（空クエリで検索しない）', () => {
  assert.strictEqual(topicPlanFor([]), null);
});

test('buildFactPrompt: 語源・由来には必ず諸説ありを書かせる指示が入っている', () => {
  const prompt = buildFactPrompt(['「油を売る」の由来 / 何の油か'], '2026年8月11日火曜日', '');
  assert.ok(prompt.includes('諸説あり'));
  assert.ok(prompt.includes('URLは検索結果の「URL:」行から一字一句そのまま転記'));
});

// このスクリプトの存在意義そのもの。プロンプトが緩んで完成文を書かせるようになると、
// コピペ投稿を招いて Original Content Rewards の対象外条件に触れる
test('buildFactPrompt: 完成文・記事本文・朝礼台本の生成を明示的に禁止している', () => {
  const prompt = buildFactPrompt(['テスト / テスト'], '2026年8月11日火曜日', '');
  assert.ok(prompt.includes('記事を書きません'));
  assert.ok(prompt.includes('「です」「ます」「でした」で終わる文を1つも書かない'));
  assert.ok(prompt.includes('「朝礼で使うなら」の台本を書かない'));
  assert.ok(prompt.includes('体言止め'));
});

test('detectProseLeak: 体言止めのデータ列挙は警告しない', () => {
  const sheet = [
    '## 1. 音の水中伝播',
    '- 事実: 水中での音速が空気中の約4倍',
    '- 数字: 空気中 秒速約340メートル、水中 秒速約1500メートル',
    '- 確度: 教科書レベルで確立',
    '- 出典: https://example.com/a',
  ].join('\n');
  assert.deepStrictEqual(detectProseLeak(sheet), []);
});

test('detectProseLeak: 完成文が混ざったら警告する', () => {
  const warnings = detectProseLeak('- 事実: 水中では音が速く伝わります。\n- 数字: 約1500メートル');
  assert.ok(warnings.some(w => w.includes('完成文の語尾')));
});

test('detectProseLeak: 絵文字と朝礼台本の混入を検知する', () => {
  const warnings = detectProseLeak('## 1. テスト🐹\n朝礼で使うなら:\n- 事実: なし');
  assert.ok(warnings.some(w => w.includes('絵文字')));
  assert.ok(warnings.some(w => w.includes('朝礼で使うなら')));
});

test('formatIssueBody: 手動投稿の手順と規約の理由を必ず載せる', () => {
  const body = formatIssueBody('2026年8月11日火曜日', '## 1. テスト\n- 事実: なし');
  assert.ok(body.includes('素材であって原稿ではありません'));
  assert.ok(body.includes('自分の言葉で'));
  assert.ok(body.includes('手動で投稿'));
  assert.ok(body.includes('automated means'));
});

test('formatIssueBody: trivia-style.mdのチェック項目を載せる', () => {
  const body = formatIssueBody('2026年8月11日火曜日', '素材');
  assert.ok(body.includes('trivia-style.md'));
  assert.ok(body.includes('諸説あります'));
  assert.ok(body.includes('80〜600字'));
});

test('formatIssueBody: 警告があれば本文に出す（黙って配らない）', () => {
  const body = formatIssueBody('2026年8月11日火曜日', '素材', ['完成文の語尾が3個含まれています']);
  assert.ok(body.includes('自動チェックの警告'));
  assert.ok(body.includes('完成文の語尾が3個含まれています'));
});
