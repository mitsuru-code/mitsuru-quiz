// 自前検索の退避動作の検証。
// 外部サービス(Tavily)を依存に加えたため、そこが落ちた時にBotごと止まらないことが最重要。
// fetchを差し替えてから本体を読み込むので、post-quiz.test.mjs とは別ファイルにしている
// （node --test はファイルごとに別プロセスで実行するため、環境変数の設定が混ざらない）
import { test } from 'node:test';
import assert from 'node:assert';

const calls = [];
globalThis.fetch = async url => {
  calls.push(String(url));
  if (String(url).includes('tavily')) return { ok: false, status: 503, json: async () => ({}) };
  throw new Error('自前検索が失敗した時点でAnthropicは呼ばれないはず');
};
process.env.SEARCH_MODE = 'self';
process.env.TAVILY_API_KEY = 'dummy';
const { research, searchPlanFor } = await import('../post-quiz.mjs');

test('検索プロバイダが落ちてもBotは止まらず、web_searchツールに退避する', async () => {
  const r = await research(searchPlanFor('briefing'));
  assert.strictEqual(r.mode, 'tool', '失敗時はtoolモードに退避すべき');
  assert.strictEqual(r.context, '', '中途半端な検索結果をプロンプトに残さない');
  assert.ok(calls.some(u => u.includes('tavily')), '実際に検索を試みている');
});

test('検索結果が空でもtoolモードに退避する（情報源なしで書かせない）', async () => {
  globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({ results: [] }) });
  assert.strictEqual((await research(searchPlanFor('recap'))).mode, 'tool');
});

test('成功時はselfモードで検索結果ブロックを返す', async () => {
  globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({
    results: [{ title: '見出し', url: 'https://news.example/1', content: '本文の要約', published_date: '2026-08-06' }],
  }) });
  const r = await research(searchPlanFor('quiz', { genre: 'スポーツ' }));
  assert.strictEqual(r.mode, 'self');
  assert.ok(r.context.includes('【検索結果】'));
  assert.ok(r.context.includes('https://news.example/1'), '出典URLをそのまま渡している');
});

test('プランが無い場合は検索せずtoolモードにする', async () => {
  assert.strictEqual((await research(null)).mode, 'tool');
});
