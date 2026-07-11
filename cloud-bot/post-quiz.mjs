// ============================================================
// クラウドBot: 時間帯別の時事コンテンツを生成してXへ自動投稿する（GitHub Actions用）
//
// 番組表（JST）:
//   6時  … 朝のブリーフィング: 日本が寝ている間の海外ニュースを20問のQ&Aで
//           1本の長文ポストに（タイパ重視・答えは同じ投稿内・企業の朝の話題作り向け）
//   12時 … 昼のエンタメクイズ: 午前の出来事・スポーツ・芸能をX投票(Poll)で出題
//           → 2時間後に正解をスレッド返信
//   17時 … 夕方の時事クイズ: 今日の主要ニュースをX投票(Poll)で出題
//           → 2時間後に正解をスレッド返信
//   20時 … 夜の振り返り: 1日の主要ニュースを一問一答20問で振り返る長文ポスト
//   随時 … 速報: 投稿が急増している話題（インプレッションが伸びそうな情報）を
//           検知したら臨時投稿（1日2回まで・2時間間隔でチェック）
//
// 環境変数:
//   ANTHROPIC_API_KEY            … 生成用（必須）
//   TWITTER_CONSUMER_KEY/SECRET  … X API OAuth 1.0a（必須）
//   TWITTER_ACCESS_TOKEN/SECRET  … X API OAuth 1.0a（必須）
//   ANSWER_DELAY_HOURS           … 正解返信までの時間（既定 2）
//   MONTHLY_POST_LIMIT           … 月間投稿数の安全上限（既定 450。X無料枠対策）
//   BREAKING_ENABLED             … "false" で速報チェックを無効化（既定 有効）
//   DRY_RUN / FORCE_POST / TEST_POST / MOCK_QUIZ_JSON / NOW_MS … テスト用フック
// ============================================================

import fs from 'node:fs';
import path from 'node:path';
import https from 'node:https';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const STATE_FILE = path.join(__dirname, 'state.json');

const DRY_RUN = process.env.DRY_RUN === 'true';
const FORCE_POST = process.env.FORCE_POST === 'true';
const TEST_POST = process.env.TEST_POST === 'true';
const ANSWER_DELAY_MS = (parseFloat(process.env.ANSWER_DELAY_HOURS || '2')) * 3600 * 1000;
const MONTHLY_POST_LIMIT = parseInt(process.env.MONTHLY_POST_LIMIT || '450', 10);
const BREAKING_ENABLED = process.env.BREAKING_ENABLED !== 'false';
const BREAKING_MAX_PER_DAY = 2;
const BREAKING_CHECK_INTERVAL_MS = 2 * 3600 * 1000; // 速報チェックは2時間間隔
const MIN_POST_GAP_MS = 30 * 60 * 1000; // 新規投稿（スロット・速報）同士は最低30分間隔をあける

// Secretsコピペ時の前後空白・改行はOAuth署名を壊すため必ず除去する
const cleanEnv = k => (process.env[k] || '').trim();
const ANTHROPIC_API_KEY = cleanEnv('ANTHROPIC_API_KEY');
const TW_CONSUMER_KEY    = cleanEnv('TWITTER_CONSUMER_KEY');
const TW_CONSUMER_SECRET = cleanEnv('TWITTER_CONSUMER_SECRET');
const TW_ACCESS_TOKEN    = cleanEnv('TWITTER_ACCESS_TOKEN');
const TW_ACCESS_SECRET   = cleanEnv('TWITTER_ACCESS_TOKEN_SECRET');

// ===== 番組表（スロット→プロファイル） =====
const SLOT_PROFILES = {
  6:  { kind: 'briefing' },
  12: { kind: 'quiz', genre: '今日の午前中の出来事や、スポーツ・芸能・エンタメの明るい話題（昼休みに気軽に楽しめる、重すぎないもの）' },
  17: { kind: 'quiz', genre: '今日の主要な時事ニュース（国内・国際・経済・社会から、帰宅時間帯に知っておきたい話題）' },
  20: { kind: 'recap' },
};
const POST_SLOTS = Object.keys(SLOT_PROFILES).map(Number).sort((a, b) => a - b);

// ===== JSTスロット計算 =====
function jstHourOf(ms) {
  return parseInt(new Intl.DateTimeFormat('ja-JP', { timeZone: 'Asia/Tokyo', hour: 'numeric', hour12: false }).format(new Date(ms)), 10);
}

// 現在時刻以前で最も新しい投稿スロットの時刻(epoch ms)を返す
function latestSlotEpoch(nowMs) {
  const jst = new Date(nowMs + 9 * 3600 * 1000); // JSTの壁時計をUTCメソッドで読むためのシフト
  let slotHour = null;
  let dayOffset = 0;
  for (const s of POST_SLOTS) {
    if (s <= jst.getUTCHours()) slotHour = s;
  }
  if (slotHour === null) { // 今日のスロットがまだ来ていない → 前日の最終スロット
    slotHour = POST_SLOTS[POST_SLOTS.length - 1];
    dayOffset = -1;
  }
  return Date.UTC(jst.getUTCFullYear(), jst.getUTCMonth(), jst.getUTCDate() + dayOffset, slotHour - 9, 0, 0);
}

function jstDateKey(ms) {
  return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Tokyo', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(ms));
}

// ===== X API: OAuth 1.0a（server.js から移植した実績コード） =====
function oauthSign(method, url, params, tokenSecret) {
  const sigParams = { ...params };
  const base = method.toUpperCase() + '&' +
    encodeURIComponent(url) + '&' +
    encodeURIComponent(Object.keys(sigParams).sort().map(k =>
      encodeURIComponent(k) + '=' + encodeURIComponent(sigParams[k])
    ).join('&'));
  const signingKey = encodeURIComponent(TW_CONSUMER_SECRET) + '&' + encodeURIComponent(tokenSecret);
  return crypto.createHmac('sha1', signingKey).update(base).digest('base64');
}

function buildOAuthHeader(method, url, extraParams) {
  const oauthParams = {
    oauth_consumer_key: TW_CONSUMER_KEY,
    oauth_nonce: crypto.randomBytes(16).toString('hex'),
    oauth_signature_method: 'HMAC-SHA1',
    oauth_timestamp: Math.floor(Date.now() / 1000).toString(),
    oauth_token: TW_ACCESS_TOKEN,
    oauth_version: '1.0',
  };
  const allParams = { ...oauthParams, ...extraParams };
  oauthParams.oauth_signature = oauthSign(method, url, allParams, TW_ACCESS_SECRET);
  return 'OAuth ' + Object.keys(oauthParams).sort().map(k =>
    encodeURIComponent(k) + '="' + encodeURIComponent(oauthParams[k]) + '"'
  ).join(', ');
}

// GET系エンドポイント用（投票結果の取得等）。OAuth 1.0aはGETのクエリパラメータも署名対象になる
function apiGet(urlPath, queryParams) {
  return new Promise((resolve, reject) => {
    const apiUrl = 'https://api.twitter.com' + urlPath;
    const authHeader = buildOAuthHeader('GET', apiUrl, queryParams);
    const qs = new URLSearchParams(queryParams).toString();
    const options = { method: 'GET', headers: { 'Authorization': authHeader } };
    const req = https.request(apiUrl + '?' + qs, options, (r) => {
      let data = '';
      r.on('data', d => data += d);
      r.on('end', () => {
        try {
          const json = JSON.parse(data);
          if (r.statusCode >= 200 && r.statusCode < 300) resolve(json);
          else reject(new Error(`HTTP ${r.statusCode}: ${JSON.stringify(json)}`));
        } catch { reject(new Error(`HTTP ${r.statusCode}: ${data}`)); }
      });
    });
    req.on('error', reject);
    req.end();
  });
}

// 投票結果を取得し「A案 62% / B案 38%」のような文字列にする。
// X無料プランは読み取りAPIの枠が非常に少なく失敗しうるため、失敗時はnullを返して
// 呼び出し側は通常の正解返信（投票結果なし）にフォールバックする
async function getPollSummary(tweetId) {
  try {
    const json = await apiGet('/2/tweets', {
      ids: tweetId,
      expansions: 'attachments.poll_ids',
      'poll.fields': 'options,voting_status',
    });
    const poll = json.includes?.polls?.[0];
    if (!poll || !Array.isArray(poll.options)) return null;
    const total = poll.options.reduce((sum, o) => sum + (o.votes || 0), 0);
    if (total <= 0) return null;
    return poll.options.map(o => `${o.label} ${Math.round((o.votes || 0) / total * 100)}%`).join(' / ');
  } catch (e) {
    console.log(`⚠️ 投票結果の取得に失敗（無視して通常の返信を続行）: ${e.message}`);
    return null;
  }
}

// poll: { options: string[], duration_minutes: number } を渡すと投票付き投稿になる
function postTweet(text, replyToId, poll) {
  return new Promise((resolve, reject) => {
    const apiUrl = 'https://api.twitter.com/2/tweets';
    const payload = { text };
    if (replyToId) payload.reply = { in_reply_to_tweet_id: replyToId };
    if (poll) payload.poll = poll;
    const body = JSON.stringify(payload);
    const authHeader = buildOAuthHeader('POST', apiUrl, {});
    const options = {
      method: 'POST',
      headers: {
        'Authorization': authHeader,
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body),
      },
    };
    const req = https.request(apiUrl, options, (r) => {
      let data = '';
      r.on('data', d => data += d);
      r.on('end', () => {
        try {
          const json = JSON.parse(data);
          if (json.data && json.data.id) resolve(json.data.id);
          else reject(new Error(`HTTP ${r.statusCode}: ${JSON.stringify(json)}`));
        } catch { reject(new Error(`HTTP ${r.statusCode}: ${data}`)); }
      });
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

// 誤投稿の削除用（DELETE_TWEET_ID環境変数が指定された時のみmain()から呼ばれる保守用ユーティリティ）
function deleteTweet(tweetId) {
  return new Promise((resolve, reject) => {
    const apiUrl = `https://api.twitter.com/2/tweets/${tweetId}`;
    const authHeader = buildOAuthHeader('DELETE', apiUrl, {});
    const options = { method: 'DELETE', headers: { 'Authorization': authHeader } };
    const req = https.request(apiUrl, options, (r) => {
      let data = '';
      r.on('data', d => data += d);
      r.on('end', () => {
        try {
          const json = JSON.parse(data);
          if (json.data) resolve(json.data);
          else reject(new Error(`HTTP ${r.statusCode}: ${JSON.stringify(json)}`));
        } catch { reject(new Error(`HTTP ${r.statusCode}: ${data}`)); }
      });
    });
    req.on('error', reject);
    req.end();
  });
}

// ===== Anthropic API 呼び出し（共通・低レベル） =====
async function callAnthropic(prompt, maxTokens, maxSearches) {
  const res = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': ANTHROPIC_API_KEY,
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify({
      model: 'claude-sonnet-4-6',
      max_tokens: maxTokens,
      messages: [{ role: 'user', content: prompt }],
      tools: [{ type: 'web_search_20250305', name: 'web_search', max_uses: maxSearches }]
    })
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error?.message || `Anthropic APIエラー (${res.status})`);
  }
  const data = await res.json();
  const text = data.content.filter(i => i.type === 'text').map(i => i.text).join('');
  return { text, stopReason: data.stop_reason };
}

// JSON形式での生成（Pollクイズ・速報チェック用の短文向け）。
// パース失敗時は1回だけ生成をやり直す（非決定的な生成の一過性の崩れを拾うため）
async function callClaude(prompt, maxTokens, maxSearches) {
  // テスト用フック: MOCK_QUIZ_JSON があればAPIを呼ばない
  if (process.env.MOCK_QUIZ_JSON) {
    return JSON.parse(process.env.MOCK_QUIZ_JSON);
  }
  let lastErr;
  for (let attempt = 1; attempt <= 2; attempt++) {
    const { text, stopReason } = await callAnthropic(prompt, maxTokens, maxSearches);
    const clean = text.replace(/```json|```/g, '').trim();
    const match = clean.match(/\{[\s\S]*\}/);
    if (!match) {
      lastErr = new Error('生成結果にJSONが見つかりません');
      console.log(`⚠️ JSON抽出失敗（試行${attempt}/2、stop_reason=${stopReason}）`);
      continue;
    }
    try {
      return JSON.parse(match[0]);
    } catch {
      try {
        // 長文生成では文字列内に生の改行が混入することがあり、標準のJSON.parseが失敗する。
        // 文字列リテラル内だけをエスケープして再試行する
        return JSON.parse(sanitizeJsonText(match[0]));
      } catch (e2) {
        lastErr = e2;
        const pos = parseInt((e2.message.match(/position (\d+)/) || [])[1], 10);
        const around = isNaN(pos) ? '' : match[0].slice(Math.max(0, pos - 80), pos + 80);
        console.log(`⚠️ JSON解析失敗（試行${attempt}/2、stop_reason=${stopReason}）: ${e2.message}\n周辺テキスト: ${around}`);
      }
    }
  }
  throw lastErr;
}

function sanitizeJsonText(text) {
  return text.replace(/"(?:[^"\\]|\\.)*"/gs, (str) =>
    str.replace(/[\u0000-\u001F]/g, (ch) => {
      const map = { '\n': '\\n', '\r': '\\r', '\t': '\\t' };
      return map[ch] || '\\u' + ch.charCodeAt(0).toString(16).padStart(4, '0');
    })
  );
}

// プレーンテキスト形式での生成（ブリーフィング・振り返り用の長文向け）。
// 長文をJSON文字列リテラルに詰めると、未エスケープの引用符等でパースが壊れやすい
// （Issue #18）。本文をそのまま出力させ、末尾の区切り行だけメタ情報として取り出す。
const POST_START = '---POST-START---';
const POST_END = '---POST-END---';
async function callClaudePlain(prompt, maxTokens, maxSearches) {
  // テスト用フック: MOCK_QUIZ_JSON は従来通りJSONとして扱う（{text, source, category}形式）
  if (process.env.MOCK_QUIZ_JSON) {
    return JSON.parse(process.env.MOCK_QUIZ_JSON);
  }
  let lastErr;
  for (let attempt = 1; attempt <= 2; attempt++) {
    const { text: raw, stopReason } = await callAnthropic(prompt, maxTokens, maxSearches);
    const clean = raw.replace(/```[a-z]*\n?/gi, '').replace(/```/g, '').trim();
    const startIdx = clean.indexOf(POST_START);
    const endIdx = clean.indexOf(POST_END);
    // POST_START〜POST_ENDの間だけを本文として使う。前置き（「情報が揃いました」等の
    // Claude自身の独り言）がマーカーの外に出ても、本文には一切混入しない設計にする
    if (startIdx === -1 || endIdx === -1 || endIdx <= startIdx) {
      lastErr = new Error(`生成結果に${POST_START}/${POST_END}区切りが見つかりません`);
      console.log(`⚠️ 区切りマーカーが見つかりません（試行${attempt}/2、stop_reason=${stopReason}）`);
      continue;
    }
    const text = clean.slice(startIdx + POST_START.length, endIdx).trim();
    const metaBlock = clean.slice(endIdx + POST_END.length);
    const source = (metaBlock.match(/^source:\s*(.*)$/mi) || [])[1]?.trim() || '';
    const category = (metaBlock.match(/^category:\s*(.*)$/mi) || [])[1]?.trim() || '';
    if (!text) {
      lastErr = new Error('生成結果の本文が空です');
      console.log(`⚠️ 本文が空です（試行${attempt}/2、stop_reason=${stopReason}）`);
      continue;
    }
    return { text, source, category };
  }
  throw lastErr;
}

// ===== キャラクター共通指示 =====
const CHARACTER = `【キャラクター設定】
あなたはX(Twitter)の時事アカウント「クイズハム🐹」の中の人です。キンクマハムスターがモチーフですが、キャラは"ほんのり"効かせる程度に抑え、誰が読んでも自然で親しみやすい文章にします。基本は親しみやすく丁寧な口調。時々「🐹」の絵文字で愛嬌を出す程度に留め、内容の分かりやすさと読みやすさを最優先します。
【共通ルール】
- ハッシュタグは使わない。出典は「（出典: メディア名）」の平文で記載する
- 1行目はタイムラインで最初に見える「見出し」。必ず興味を引くフックにする
- 事実（数字・固有名詞・日付）は検索結果に忠実に。推測で書かない
- 出力の冒頭に「情報が揃いました」「投稿を組み立てます」のような前置き・作業報告・区切り線を絶対に書かない。指定されたフォーマットの中身だけを書く（それ以外の文章は一切書かない）`;

// ===== 生成: 朝のブリーフィング（6時） =====
async function generateBriefing(state) {
  const prompt = `${CHARACTER}

Web検索を使って、「日本時間の昨夜から今朝（前日22時〜今朝6時ごろ）に海外で報じられた・起きたニュース」を幅広く調べてください（Reuters/AP/BBC/CNN/Bloomberg等の海外メディア中心。米国市場の動き、国際政治、テクノロジー、スポーツの海外試合結果など）。

それを元に、朝の通勤時間にサッと読める「一問一答ブリーフィング」を1本作ってください:
- 全20問。1問は「Q: 質問文」「A: 答え＋一言解説」の2〜3行で完結（タイパ重視）
- 職場の朝の雑談や商談の話題作りにそのまま使える、幅広いジャンル構成にする
- 冒頭に「☀️ おはようございます！寝ている間に世界で起きたこと、20問でおさらい🐹」のような挨拶と、この投稿の使い方が一目で分かる一文
- 各問は番号付き（Q1〜Q20）。ジャンルの偏りを避ける
- 最後に「今日も良い一日を！」のような締めと、主な出典を「（出典: Reuters、BBC ほか）」のようにまとめて記載

出力形式（JSONにしない。本文中の引用符「"」はそのまま自由に使ってよい）:
まず ---POST-START--- とだけ書いた行、続けて投稿本文、続けて ---POST-END--- とだけ書いた行、続けて次の2行を書いてください。---POST-START--- より前には何も書かないこと（前置き・確認・作業報告は一切禁止）:
---POST-START---
（ここに投稿本文）
---POST-END---
source: 使った主な出典メディアの一覧
category: 朝ブリーフィング`;
  return callClaudePlain(prompt, 6000, 8);
}

// ===== 生成: Poll形式クイズ（12時・17時） =====
async function generatePollQuiz(state, genre) {
  const recentTopics = (state.recentTopics || []).join(' / ');
  const recentOpeners = (state.recentOpeners || []).join(' / ');
  const pick = arr => arr[Math.floor(Math.random() * arr.length)];
  const format = pick(['4択', '二択', '○×']);

  const prompt = `${CHARACTER}

Web検索で「${genre}」を1件調べ、それを元にX(Twitter)の投票（Poll）機能で出題するクイズを1問作ってください。

【投票クイズのルール】
- 形式は【${format}】（4択なら選択肢4つ、二択なら2つ、○×なら「○ 正しい」「× 間違い」の2つ）
- 本文（question）には選択肢を書かない。選択肢は choices 配列に入れる（Xの投票欄に表示される）
- 各選択肢は必ず25文字以内（Xの投票の上限。超えると投稿できない）
- 本文は120文字以内。1行目にフック、続けて問題文、最後に「投票で答えてね🐹 正解は2時間後にリプで発表！」のような参加を促す一言
- 正解の位置は毎回変える

【重複禁止】
${recentTopics ? '- 以下と異なるニュースを選ぶこと: ' + recentTopics : '- （履歴なし）'}
${recentOpeners ? '- 以下の書き出しと被らないこと: ' + recentOpeners : ''}

以下のJSON形式のみで返答してください:
{
  "question": "投稿本文（選択肢を含めない。フック＋問題＋投票を促す一言）",
  "choices": ["選択肢1", "選択肢2", ...],
  "answer": "正解返信用の全文。①『正解は○○でした！』と答え合わせ（投票してくれた人への感謝や労いを一言）②簡潔な解説 ③『🌰豆知識』1つ。200文字程度",
  "source": "出典メディア名と記事タイトル",
  "sourceUrl": "出典記事の正確なURL（実在するもののみ。不明なら空文字）",
  "category": "ジャンル名・${format}"
}`;
  return callClaude(prompt, 1500, 5);
}

// ===== 生成: 夜の振り返り（20時） =====
async function generateRecap(state) {
  const prompt = `${CHARACTER}

Web検索で「今日（日本時間の本日）の主要ニュース」を国内外・経済・社会・スポーツから幅広く調べてください。

それを元に、1日を振り返る「一問一答おさらいクイズ」を1本作ってください（朝のブリーフィングと同じ一問一答形式・全20問）:
- 全20問。1問は「Q: 質問文」「A: 答え＋一言解説」の2〜3行で完結（タイパ重視）
- 冒頭に「🌙 今日も一日おつかれさまでした。今日のニュース、どれだけ覚えてる？20問でおさらいです🐹」のような導入
- 各問は番号付き（Q1〜Q20）。今日1日の出来事から、ジャンルの偏りを避けて幅広く選ぶ
- 最後に「また明日🐹」のような締めと、主な出典を「（出典: NHK、Reuters ほか）」のようにまとめて記載

出力形式（JSONにしない。本文中の引用符「"」はそのまま自由に使ってよい）:
まず ---POST-START--- とだけ書いた行、続けて投稿本文、続けて ---POST-END--- とだけ書いた行、続けて次の2行を書いてください。---POST-START--- より前には何も書かないこと（前置き・確認・作業報告は一切禁止）:
---POST-START---
（ここに投稿本文）
---POST-END---
source: 使った主な出典メディアの一覧
category: 夜の振り返り`;
  return callClaudePlain(prompt, 6000, 8);
}

// ===== 生成: 速報チェック（随時） =====
async function checkBreaking(state) {
  const recentBreaking = (state.recentBreaking || []).join(' / ');
  const prompt = `${CHARACTER}

Web検索で「今まさに話題が急拡大しているニュース・出来事」を調べてください。判断基準は重大性ではなく**話題量と拡散の勢い**です:
- 直近1〜3時間で複数のメディアが一斉に報じ始めた話題
- X(Twitter)で投稿数が急増している・トレンド入りしている話題
- 「今知っておかないと乗り遅れる」感のある、インプレッションが急激に伸びそうな情報

該当する話題が見つかった場合のみ、その内容を分かりやすく伝える速報ポストを1本作ってください:
- 冒頭は「🚨 速報」または「📈 いま話題」から始める
- 何が起きたかを3〜5行で簡潔に。数字や固有名詞は正確に
- 最後に「（出典: メディア名）」
- 全体で200文字以内

${recentBreaking ? `【既に投稿済みの速報（同じ話題は不可）】: ${recentBreaking}` : ''}

該当する話題が「明確に」ある場合のみ breaking を true にしてください。迷ったら false（通常ニュース程度で乱発しない）。

以下のJSON形式のみで返答してください:
{
  "breaking": true または false,
  "text": "速報ポストの全文（breakingがfalseなら空文字）",
  "headline": "話題の見出し（重複チェック用の短い要約）",
  "source": "出典メディア名"
}`;
  return callClaude(prompt, 1000, 4);
}

// ===== 状態管理 =====
function loadState() {
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
  } catch {
    return {};
  }
}

function saveState(state) {
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2) + '\n');
}

// ===== 月間投稿数ガード =====
function canPost(state, now) {
  const month = jstDateKey(now).slice(0, 7);
  if (!state.monthly || state.monthly.month !== month) {
    state.monthly = { month, posts: 0 };
  }
  return state.monthly.posts < MONTHLY_POST_LIMIT;
}

// 返信（スレッド返信）はタイムライン上の新規投稿ではないため間隔規制の対象外。月間カウントのみ加算
function countPostOnly(state) {
  state.monthly.posts++;
}

// スロット投稿・速報投稿（新規トップレベル投稿）用。間隔規制の基準時刻も更新する
function countPost(state, now) {
  state.monthly.posts++;
  state.lastAnyPostAt = now;
}

// 投稿履歴（Pixelアプリの稼働状況カードから参照する）。最新30件を保持
function recordPost(state, { tweetId, kind, category, textPreview, postedAt }) {
  state.postHistory = state.postHistory || [];
  state.postHistory.unshift({ tweetId, kind, category: category || '', textPreview: (textPreview || '').slice(0, 80), postedAt });
  state.postHistory = state.postHistory.slice(0, 30);
}

// 直近の新規投稿からMIN_POST_GAP_MS以上経っているか（速報とスロット投稿が接近しすぎるのを防ぐ）
function spacingOk(state, now) {
  return (now - (state.lastAnyPostAt || 0)) >= MIN_POST_GAP_MS;
}

// ===== メイン =====
async function main() {
  const DELETE_TWEET_ID = (process.env.DELETE_TWEET_ID || '').trim();
  const missing = [];
  if (!ANTHROPIC_API_KEY && !process.env.MOCK_QUIZ_JSON && !TEST_POST) missing.push('ANTHROPIC_API_KEY');
  if (!DRY_RUN || TEST_POST || DELETE_TWEET_ID) {
    if (!TW_CONSUMER_KEY) missing.push('TWITTER_CONSUMER_KEY');
    if (!TW_CONSUMER_SECRET) missing.push('TWITTER_CONSUMER_SECRET');
    if (!TW_ACCESS_TOKEN) missing.push('TWITTER_ACCESS_TOKEN');
    if (!TW_ACCESS_SECRET) missing.push('TWITTER_ACCESS_TOKEN_SECRET');
  }
  if (missing.length) {
    console.error('❌ 環境変数が不足しています: ' + missing.join(', '));
    process.exit(1);
  }

  // 接続テストモード: 生成をスキップし、X認証だけを検査する
  if (TEST_POST) {
    console.log(`🔧 X API接続テスト（キー長: CK=${TW_CONSUMER_KEY.length} / CS=${TW_CONSUMER_SECRET.length} / AT=${TW_ACCESS_TOKEN.length} / AS=${TW_ACCESS_SECRET.length}）`);
    const id = await postTweet(`🔧 クラウドBot接続テスト ${new Date().toISOString()}`, null);
    console.log(`✅ X APIの接続テストに成功しました（tweet: ${id}）。このテスト投稿はXアプリから削除して構いません`);
    return;
  }

  // 誤投稿削除モード: DELETE_TWEET_ID が指定された時だけ、その投稿を削除して終了する（保守用）
  if (DELETE_TWEET_ID) {
    if (DRY_RUN) {
      console.log(`🧪 [DRY_RUN] tweet ${DELETE_TWEET_ID} を削除します（実際には削除しません）`);
      return;
    }
    await deleteTweet(DELETE_TWEET_ID);
    console.log(`🗑 投稿を削除しました（tweet: ${DELETE_TWEET_ID}）`);
    return;
  }

  const state = loadState();
  state.pendingAnswers = state.pendingAnswers || [];
  state.recentTopics = state.recentTopics || [];
  state.recentOpeners = state.recentOpeners || [];
  state.recentBreaking = state.recentBreaking || [];

  const now = parseInt(process.env.NOW_MS || '', 10) || Date.now(); // NOW_MSはテスト用フック
  const jstHour = jstHourOf(now);
  const slotEpoch = latestSlotEpoch(now);
  const slotHour = jstHourOf(slotEpoch);
  const profile = SLOT_PROFILES[slotHour] || { kind: 'quiz', genre: '直近の重要な時事問題' };
  const slotStr = new Intl.DateTimeFormat('ja-JP', { timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(new Date(slotEpoch));
  canPost(state, now); // 月カウンタの初期化
  console.log(`⏰ JST ${jstHour}時 / スロット: [${POST_SLOTS.join(', ')}] / 直近: ${slotStr}(${profile.kind}) / 今月の投稿: ${state.monthly.posts}/${MONTHLY_POST_LIMIT} / DRY_RUN=${DRY_RUN} / FORCE_POST=${FORCE_POST}`);

  let stateChanged = false;

  // --- 1. 期限が来た正解をスレッド返信 ---
  const due = state.pendingAnswers.filter(a => a.dueAt <= now);
  for (const item of due) {
    let answerText = item.answer;
    if (item.isPoll && !DRY_RUN) {
      const summary = await getPollSummary(item.tweetId);
      if (summary) answerText = `📊 投票結果: ${summary}\n\n` + answerText;
    }
    if (item.sourceUrl) answerText += `\n\n📰 詳しくはこちら→ ${item.sourceUrl}`;
    if (DRY_RUN) {
      console.log(`🧪 [DRY_RUN] 正解返信（→ ${item.tweetId}）:\n${answerText}\n`);
    } else if (!canPost(state, now)) {
      console.log('⚠️ 月間投稿上限に達したため正解返信を見送ります');
    } else {
      try {
        const replyId = await postTweet(answerText, item.tweetId);
        console.log(`💬 正解を返信しました（tweet: ${replyId} → 元: ${item.tweetId}）`);
        state.pendingAnswers = state.pendingAnswers.filter(a => a !== item);
        countPostOnly(state);
        stateChanged = true;
      } catch (e) {
        console.error(`⚠️ 正解返信に失敗（元: ${item.tweetId}）: ${e.message} — 次回の実行で再試行します`);
      }
    }
  }

  // --- 2. 直近スロットが未投稿ならコンテンツを生成して投稿（キャッチアップ方式） ---
  const delayMin = Math.round((now - slotEpoch) / 60000);
  const tooLate = delayMin > 360; // 6時間超の遅延は深夜投稿等になり逆効果なので見送る
  const slotUnposted = (state.lastPostedAt || 0) < slotEpoch;
  const shouldPost = FORCE_POST || (slotUnposted && !tooLate);
  if (shouldPost && !DRY_RUN && !canPost(state, now)) {
    console.log('⚠️ 月間投稿上限に達したためスロット投稿を見送ります');
  } else if (shouldPost && !DRY_RUN && !spacingOk(state, now)) {
    const waitMin = Math.ceil((MIN_POST_GAP_MS - (now - (state.lastAnyPostAt || 0))) / 60000);
    console.log(`⏳ 前回の投稿から30分経っていないためスロット投稿を見送ります（次回の実行で再試行、あと約${waitMin}分）`);
  } else if (shouldPost) {
    if (!FORCE_POST) console.log(`📮 ${slotStr} のスロット（${profile.kind}）が未投稿のため投稿します（${delayMin}分経過）`);

    if (profile.kind === 'briefing' || profile.kind === 'recap') {
      const gen = profile.kind === 'briefing' ? await generateBriefing(state) : await generateRecap(state);
      if (!gen.text) throw new Error('生成結果に text がありません');
      console.log(`🧠 生成した${gen.category}（${gen.text.length}文字）:\n${gen.text.slice(0, 300)}…\n`);
      if (DRY_RUN) {
        console.log(`🧪 [DRY_RUN] 全文:\n${gen.text}`);
      } else {
        const tweetId = await postTweet(gen.text, null);
        console.log(`🐦 Xに投稿しました（tweet: ${tweetId}）`);
        state.recentTopics = [gen.source || gen.category, ...state.recentTopics].filter(Boolean).slice(0, 8);
        state.lastPostedAt = now;
        countPost(state, now);
        recordPost(state, { tweetId, kind: profile.kind, category: gen.category, textPreview: gen.text, postedAt: now });
        stateChanged = true;
      }

    } else { // quiz（Poll形式）
      const quiz = await generatePollQuiz(state, profile.genre);
      if (!quiz.question) throw new Error('生成結果に question がありません');

      // Poll選択肢のバリデーション（2〜4個・各25文字以内）。不正ならテキスト投稿へフォールバック
      let poll = null;
      let text = quiz.question;
      const choices = Array.isArray(quiz.choices) ? quiz.choices.map(c => String(c)) : [];
      if (choices.length >= 2 && choices.length <= 4 && choices.every(c => c.length <= 25)) {
        poll = { options: choices, duration_minutes: Math.round(ANSWER_DELAY_MS / 60000) };
      } else {
        console.log('⚠️ Poll選択肢が条件を満たさないためテキスト投稿にフォールバックします');
        text = quiz.question + '\n\n' + choices.map((c, i) => `${['A','B','C','D'][i]}. ${c}`).join('\n');
      }
      console.log(`🧠 生成したクイズ（${quiz.category || '時事'}）:\n${text}\n選択肢: ${JSON.stringify(choices)}\n`);

      if (DRY_RUN) {
        console.log(`🧪 [DRY_RUN] 投稿はスキップ。正解文:\n${quiz.answer || '(なし)'}\n出典: ${quiz.source || ''} ${quiz.sourceUrl || ''}`);
      } else {
        let tweetId;
        try {
          tweetId = await postTweet(text, null, poll);
        } catch (e) {
          if (poll) {
            // Poll起因の失敗はテキスト投稿で再試行（投稿自体を止めない）
            console.log(`⚠️ Poll付き投稿に失敗（${e.message}）。テキスト投稿で再試行します`);
            text = quiz.question + '\n\n' + choices.map((c, i) => `${['A','B','C','D'][i]}. ${c}`).join('\n');
            tweetId = await postTweet(text, null);
          } else {
            throw e;
          }
        }
        console.log(`🐦 Xに投稿しました（tweet: ${tweetId}）`);
        if (quiz.answer) {
          state.pendingAnswers.push({
            tweetId,
            answer: quiz.answer,
            sourceUrl: quiz.sourceUrl || '',
            question: (quiz.question || '').slice(0, 60),
            postedAt: now,
            dueAt: now + ANSWER_DELAY_MS,
            isPoll: !!poll,
          });
        }
        state.recentTopics = [quiz.source || quiz.category || '', ...state.recentTopics].filter(Boolean).slice(0, 8);
        state.recentOpeners = [(quiz.question || '').slice(0, 40), ...state.recentOpeners].filter(Boolean).slice(0, 5);
        state.lastPostedAt = now;
        countPost(state, now);
        recordPost(state, { tweetId, kind: 'quiz', category: quiz.category, textPreview: quiz.question, postedAt: now });
        stateChanged = true;
      }
    }
  } else if (slotUnposted && tooLate) {
    console.log(`⏭ ${slotStr} のスロットは未投稿ですが、${delayMin}分経過しているため見送ります（次のスロットから再開）`);
  } else {
    console.log('⏭ 直近スロットは投稿済み（返信キューと速報チェックのみ）');
  }

  // --- 3. 速報チェック（2時間間隔・7〜23時・1日2回まで） ---
  const today = jstDateKey(now);
  if (state.breakingDate !== today) { state.breakingDate = today; state.breakingCount = 0; }
  const breakingOk = BREAKING_ENABLED && jstHour >= 7 && jstHour <= 23
    && (now - (state.lastBreakingCheck || 0)) >= BREAKING_CHECK_INTERVAL_MS
    && state.breakingCount < BREAKING_MAX_PER_DAY
    && (DRY_RUN || spacingOk(state, now)); // 直前にスロット投稿等があった場合は間隔を優先しスキップ（次回に再試行）
  if (breakingOk && !process.env.MOCK_QUIZ_JSON) { // MOCKテスト時はスロット側のみ検証
    state.lastBreakingCheck = now;
    stateChanged = true;
    try {
      const b = await checkBreaking(state);
      if (b.breaking && b.text) {
        console.log(`🚨 速報を検知: ${b.headline}`);
        if (DRY_RUN) {
          console.log(`🧪 [DRY_RUN] 速報投稿:\n${b.text}`);
        } else if (canPost(state, now)) {
          const tweetId = await postTweet(b.text, null);
          console.log(`🐦 速報を投稿しました（tweet: ${tweetId}）`);
          state.recentBreaking = [b.headline, ...state.recentBreaking].filter(Boolean).slice(0, 10);
          state.breakingCount++;
          countPost(state, now);
          recordPost(state, { tweetId, kind: 'breaking', category: b.headline, textPreview: b.text, postedAt: now });
          state.lastPostedAt = now;
        }
      } else {
        console.log('📡 速報チェック: 該当なし');
      }
    } catch (e) {
      console.error(`⚠️ 速報チェックに失敗: ${e.message}（次回に再試行）`);
    }
  }

  if (stateChanged && !DRY_RUN) {
    saveState(state);
    console.log('💾 state.json を更新しました');
  }
  console.log('✅ 完了');
}

main().catch(e => {
  console.error('❌ 実行エラー:', e.message);
  if (e.message.includes('HTTP 401')) {
    console.error(`💡 401(認証失敗)の主な原因:
  1. X Developer Portalのアプリ権限が「Read」のみ → 「Read and Write」に変更し、
     その後 Access Token & Secret を必ず「Regenerate」して、GitHubのSecrets
     （X_ACCESS_TOKEN / X_ACCESS_TOKEN_SECRET）を新しい値に更新する
  2. Secretsの値の貼り間違い（API Key と Access Token の取り違え等）
  3. キー長（CK≈25 / CS≈50 / AT≈50 / AS≈45 が目安）が極端に違う場合は値が別物`);
  } else if (e.message.includes('HTTP 403')) {
    console.error(`💡 403(権限拒否)の主な原因:
  1. アプリがProjectに紐付いていない（Developer PortalでProject配下にアプリを作る）
  2. 同一内容の重複投稿
  3. APIプランの制限`);
  }
  process.exit(1);
});
