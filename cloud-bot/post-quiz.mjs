// ============================================================
// クラウドBot: 時間帯別の時事コンテンツを生成してXへ自動投稿する（GitHub Actions用）
//
// 番組表（JST）:
//   5時台 … 朝のブリーフィング: 日本が寝ている間の海外ニュースを20問のQ&Aで
//           1本の長文ポストに（タイパ重視・答えは同じ投稿内・企業の朝の話題作り向け）
//   12時 … 昼のエンタメクイズ: 午前の出来事・スポーツ・芸能をX投票(Poll)で出題
//           → 2時間後に正解をスレッド返信
//   17時 … 夕方の時事クイズ: 今日の主要ニュースをX投票(Poll)で出題
//           → 2時間後に正解をスレッド返信
//   20時 … 夜の振り返り: 1日の主要ニュースを一問一答20問で振り返る長文ポスト
//   随時 … 速報: 深夜2時・4時／朝9時半〜11時／午後14〜16時の固定時刻に話題の急拡大を
//           チェックし、見つかれば臨時投稿（1日 BREAKING_MAX_PER_DAY 回まで）。
//           朝の枠で速報が無ければ代わりに軽いクイズを投稿。深夜は必ず、午後は場合により
//           30分後の詳細記事フォローアップも自動投稿
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
const TOPIC_HINT = (process.env.TOPIC_HINT || '').trim(); // 手動実行時のみ: その回の生成トピックを一時的に指定する
const ANSWER_DELAY_MS = (parseFloat(process.env.ANSWER_DELAY_HOURS || '2')) * 3600 * 1000;
const MONTHLY_POST_LIMIT = parseInt(process.env.MONTHLY_POST_LIMIT || '450', 10);
const BREAKING_ENABLED = process.env.BREAKING_ENABLED !== 'false';
// 速報チェックは「N時間おき」の間隔方式ではなく、経験上ニュースが発生しやすい固定時刻の
// チェックポイント方式に一本化する（.github/workflows/cloud-bot.ymlの専用cronで実際にこの時刻に起動）。
// fallback:'quiz' は該当時刻で速報が見つからなかった場合に代わりに軽いクイズを投稿する枠、
// forceArticle:true は速報が見つかった場合、AIの自己判定を待たず必ず30分後の詳細記事も出す枠
// （深夜は情報が少なく誤読しやすいため、続報で正確性を補う狙い）
const BREAKING_CHECKPOINTS = [
  { hm: '02:00', fallback: null,   forceArticle: true  },
  { hm: '04:00', fallback: null,   forceArticle: true  },
  { hm: '09:30', fallback: 'quiz', forceArticle: false },
  { hm: '10:00', fallback: 'quiz', forceArticle: false },
  { hm: '10:30', fallback: 'quiz', forceArticle: false },
  { hm: '11:00', fallback: 'quiz', forceArticle: false },
  { hm: '14:00', fallback: null,   forceArticle: false },
  { hm: '15:00', fallback: null,   forceArticle: false },
  { hm: '16:00', fallback: null,   forceArticle: false },
];
const BREAKING_CHECKPOINT_WINDOW_MIN = 45; // cronの起動遅延・投稿間隔調整による再試行を許容する猶予（分）
// チェックポイントが9箇所に増えたため、旧来の「1日2回」から引き上げる
// （checkBreaking自体は「明確な場合のみtrue」と保守的に判定するため、実際に全枠が
// 該当することは想定していない。運用してみて多すぎる/少なすぎる場合は要調整）
const BREAKING_MAX_PER_DAY = 6;
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
  5:  { kind: 'briefing' },
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

export function jstDateKey(ms) {
  return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Tokyo', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(ms));
}

// 日付・曜日を明示してプロンプトに埋め込むためのラベル（例: "2026年7月21日火曜日"）。
// Web検索結果や生成モデル自身の記憶に基づく曜日推定は実際の日付とずれることがあるため
// （実際に「月曜日です」という誤りが本番投稿された事故が発生）、コード側で計算した
// 正しい日付・曜日を明示的に伝え、それを優先させる
export function jstDateLabel(ms) {
  return new Intl.DateTimeFormat('ja-JP', { timeZone: 'Asia/Tokyo', year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' }).format(new Date(ms));
}

// 現在時刻に対して「今日まだ未処理」かつ「予定時刻を過ぎて猶予時間内」の
// 速報チェックポイントを1件返す（無ければnull）。doneKeysは当日処理済みの"日付_時刻"キー一覧
export function findDueCheckpoint(now, doneKeys) {
  const todayKey = jstDateKey(now);
  const hhmm = new Intl.DateTimeFormat('ja-JP', { timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(now));
  const [h, m] = hhmm.split(':').map(Number);
  const nowMin = h * 60 + m;
  for (const cp of BREAKING_CHECKPOINTS) {
    const key = `${todayKey}_${cp.hm}`;
    if (doneKeys.includes(key)) continue;
    const [ch, cm] = cp.hm.split(':').map(Number);
    const cpMin = ch * 60 + cm;
    if (nowMin >= cpMin && nowMin < cpMin + BREAKING_CHECKPOINT_WINDOW_MIN) {
      return { ...cp, key };
    }
  }
  return null;
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

// 曜日チェックの対象範囲（冒頭のみ）。記事本文の途中では「来週日曜日に」のような
// "今日"以外の日付への正当な言及があり得るため、実際の事故が起きた「冒頭の自己紹介文
// （今朝の●●、○曜日です）」の範囲だけを対象にすることで誤検知を避ける
const WEEKDAY_CHECK_HEAD_CHARS = 80;

// 投稿直前の機械的サニティチェック（最後の砦）。プロンプト側の指示や生成モデルの
// 自己申告だけに頼らず、明らかにおかしい投稿を機械的に検知して中断する。
// 1) 孤立サロゲート（絵文字の途中で切れた不正なUTF-16文字）が残っていないか
//    → 残っていると"no low surrogate in string"でX APIに拒否される事故が実際に発生した
// 2) 冒頭の「○曜日」という言及が、実際の日付の曜日と食い違っていないか
//    → AIが実際とは異なる曜日を書いて投稿してしまう事故が実際に発生した
export function assertValidPostText(text, now = parseInt(process.env.NOW_MS || '', 10) || Date.now()) {
  for (let i = 0; i < text.length; i++) {
    const code = text.charCodeAt(i);
    if (code >= 0xD800 && code <= 0xDBFF) {
      const next = text.charCodeAt(i + 1);
      if (!(next >= 0xDC00 && next <= 0xDFFF)) {
        throw new Error(`投稿本文に不正な文字（孤立サロゲート）が含まれています（位置${i}）`);
      }
    } else if (code >= 0xDC00 && code <= 0xDFFF) {
      const prev = text.charCodeAt(i - 1);
      if (!(prev >= 0xD800 && prev <= 0xDBFF)) {
        throw new Error(`投稿本文に不正な文字（孤立サロゲート）が含まれています（位置${i}）`);
      }
    }
  }

  const actualWeekday = new Intl.DateTimeFormat('ja-JP', { timeZone: 'Asia/Tokyo', weekday: 'short' }).format(new Date(now)); // 例: "火"
  const head = text.slice(0, WEEKDAY_CHECK_HEAD_CHARS);
  const mentioned = head.match(/[日月火水木金土]曜日/g) || [];
  for (const m of mentioned) {
    if (m[0] !== actualWeekday) {
      throw new Error(`投稿冒頭の曜日表記「${m}」が実際の日付（${actualWeekday}曜日）と一致しません`);
    }
  }
}

// poll: { options: string[], duration_minutes: number } を渡すと投票付き投稿になる
function postTweet(text, replyToId, poll) {
  assertValidPostText(text);
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
async function callClaudePlain(prompt, maxTokens, maxSearches, allowEmpty = false) {
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
    const text = stripMarkdown(clean.slice(startIdx + POST_START.length, endIdx).trim());
    const metaBlock = clean.slice(endIdx + POST_END.length);
    const source = (metaBlock.match(/^source:\s*(.*)$/mi) || [])[1]?.trim() || '';
    const category = (metaBlock.match(/^category:\s*(.*)$/mi) || [])[1]?.trim() || '';
    const update = (metaBlock.match(/^update:\s*(.*)$/mi) || [])[1]?.trim() || '';
    if (!text && !(allowEmpty && /^no$/i.test(update))) {
      lastErr = new Error('生成結果の本文が空です');
      console.log(`⚠️ 本文が空です（試行${attempt}/2、stop_reason=${stopReason}）`);
      continue;
    }
    return { text, source, category, update };
  }
  throw lastErr;
}

// プロンプトで禁止していても、Claudeが習慣的にMarkdown記法（太字・水平線）を
// 混ぜてしまうことがある（生の「**」やASCII罫線「---」がそのまま投稿される事故）。
// プロンプト側の指示だけに頼らず、最後の砦としてここで機械的に取り除く
export function stripMarkdown(text) {
  return text
    .replace(/\*\*(.*?)\*\*/g, '$1')      // **太字** → 太字
    .replace(/^-{3,}\s*$/gm, '─'.repeat(21)); // 独立行の "---" → 罫線文字に置き換え
}

// 文字列の先頭maxLen文字を安全に切り出す。.slice(0,N)だと絵文字などのサロゲート
// ペア（UTF-16で2コード単位からなる文字）の中間で切れて孤立サロゲートになることがあり、
// その文字列を後で（recentOpeners経由で）APIリクエストのJSON本文に含めると
// "no low surrogate in string" エラーで以後の生成が全滅する事故が実際に発生した。
// 末尾が高サロゲート単体になっていたら1文字落とす
export function safeSlice(str, maxLen) {
  let sliced = str.slice(0, maxLen);
  const lastCode = sliced.charCodeAt(sliced.length - 1);
  if (lastCode >= 0xD800 && lastCode <= 0xDBFF) {
    sliced = sliced.slice(0, -1);
  }
  return sliced;
}

// ===== キャラクター共通指示 =====
const CHARACTER = `【キャラクター設定】
あなたはX(Twitter)の時事アカウント「クイズハム🐹」の中の人です。キンクマハムスターがモチーフですが、キャラは"ほんのり"効かせる程度に抑え、誰が読んでも自然で親しみやすい文章にします。基本は親しみやすく丁寧な口調。時々「🐹」の絵文字で愛嬌を出す程度に留め、内容の分かりやすさと読みやすさを最優先します。
【共通ルール】
- ハッシュタグは使わない。出典は「（出典: メディア名）」の平文で記載する
- 1行目はタイムラインで最初に見える「見出し」。必ず興味を引くフックにする
- 事実（数字・固有名詞・日付）は検索結果に忠実に。推測で書かない
- 出力の冒頭に「情報が揃いました」「投稿を組み立てます」のような前置き・作業報告・区切り線を絶対に書かない。指定されたフォーマットの中身だけを書く（それ以外の文章は一切書かない）
- Markdown記法は一切使わない（**太字**、# 見出し、- 箇条書きなど禁止）。Xは生のテキストがそのまま表示されるため、Markdown記号は読者にそのまま記号として見えてしまう。区切り線が必要な場合は「─」（罫線文字）を使い、ハイフン3つ「---」は使わない`;

// ===== 生成: 朝のブリーフィング（5時台） =====
async function generateBriefing(state, now) {
  const recentOpeners = (state.recentOpeners || []).join(' / ');
  const todayLabel = jstDateLabel(now);
  const prompt = `${CHARACTER}

【本日の日付】${todayLabel}（日本時間）。曜日や日付に言及する場合は必ずこの情報を使うこと。Web検索結果や自身の記憶に基づく曜日推定がこれと食い違っても、この日付情報を優先すること（誤った曜日を投稿してしまう事故が過去に発生したため）。

Web検索を使って、「日本時間の昨夜から今朝（前日22時〜今朝6時ごろ）に海外で報じられた・起きたニュース」を幅広く調べてください（Reuters/AP/BBC/CNN/Bloomberg等の海外メディア中心。米国市場の動き、国際政治、テクノロジー、スポーツの海外試合結果など）。

それを元に、朝の通勤時間にサッと読める「一問一答ブリーフィング」を1本作ってください:
- 全20問。1問は「Q: 質問文」「A: 答え＋一言解説」の2〜3行で完結（タイパ重視）
- 職場の朝の雑談や商談の話題作りにそのまま使える、幅広いジャンル構成にする
- 冒頭2〜3行は、その日いちばん気になったニュースへの一言リアクションから始めるなど、日によって書き方を変える（「おはようございます！寝ている間に〜」のような同じ言い回しの繰り返しは避ける。ただし挨拶自体は入れてよい）
- 各問は番号付き（Q1〜Q20）。ジャンルの偏りを避ける
- 締めの一言・言い回しも毎回変える。最後に主な出典を「（出典: Reuters、BBC ほか）」のようにまとめて記載
${recentOpeners ? '- 冒頭の書き出しが以下と似た表現・構成にならないようにすること: ' + recentOpeners : ''}
${TOPIC_HINT ? `- 今回は特に「${TOPIC_HINT}」に関する話題を中心に取り上げること（20問の半分程度以上を目安に。他ジャンルも少し混ぜてよい）` : ''}

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
async function generateRecap(state, now) {
  const recentOpeners = (state.recentOpeners || []).join(' / ');
  const todayKey = jstDateKey(now);
  const todaysBreaking = [...new Set(
    (state.postHistory || [])
      .filter(p => (p.kind === 'breaking' || p.kind === 'feature') && jstDateKey(p.postedAt) === todayKey)
      .map(p => p.category)
      .filter(Boolean)
  )].join(' / ');
  const prompt = `${CHARACTER}

【本日の日付】${jstDateLabel(now)}（日本時間）。曜日や日付に言及する場合は必ずこの情報を使うこと。Web検索結果や自身の記憶に基づく曜日推定がこれと食い違っても、この日付情報を優先すること（誤った曜日を投稿してしまう事故が過去に発生したため）。

Web検索で「今日（日本時間の本日）の主要ニュース」を国内外・経済・社会・スポーツから幅広く調べてください。

それを元に、1日を振り返る「一問一答おさらいクイズ」を1本作ってください（朝のブリーフィングと同じ一問一答形式・全20問）:
- 全20問。1問は「Q: 質問文」「A: 答え＋一言解説」の2〜3行で完結（タイパ重視）
- 冒頭2〜3行は、今日いちばん印象に残ったニュースへの一言リアクションから始めるなど、日によって書き方を変える（「今日も一日おつかれさまでした。今日のニュース、どれだけ覚えてる？」のような同じ言い回しの繰り返しは避ける。ただし労いの気持ちは入れてよい）
- 各問は番号付き（Q1〜Q20）。今日1日の出来事から、ジャンルの偏りを避けて幅広く選ぶ
- 締めの一言・言い回しも毎回変える。最後に主な出典を「（出典: NHK、Reuters ほか）」のようにまとめて記載
${recentOpeners ? '- 冒頭の書き出しが以下と似た表現・構成にならないようにすること: ' + recentOpeners : ''}
${TOPIC_HINT ? `- 今回は特に「${TOPIC_HINT}」に関する話題を中心に取り上げること（20問の半分程度以上を目安に。他ジャンルも少し混ぜてよい）` : ''}
${todaysBreaking ? `- 本日は次の速報・続報を扱いました。特に生活への影響が大きかったものは3〜5問程度を割いて、原因・影響・解決策・現在の状況まで深掘りして扱うこと（他の話題と同列の1問で済ませない）: ${todaysBreaking}` : ''}

出力形式（JSONにしない。本文中の引用符「"」はそのまま自由に使ってよい）:
まず ---POST-START--- とだけ書いた行、続けて投稿本文、続けて ---POST-END--- とだけ書いた行、続けて次の2行を書いてください。---POST-START--- より前には何も書かないこと（前置き・確認・作業報告は一切禁止）:
---POST-START---
（ここに投稿本文）
---POST-END---
source: 使った主な出典メディアの一覧
category: 夜の振り返り`;
  return callClaudePlain(prompt, 6000, 8);
}

// ===== 生成: 特集記事（手動実行のFEATURE_TOPIC指定時のみ） =====
async function generateFeature(topic) {
  const prompt = `${CHARACTER}

Web検索を使って、「${topic}」について詳しく調べてください。

それを元に、この話題を深掘りする「特集記事」を1本作ってください（クイズ形式にはしない。通常の記事文体で）:
- 見出し（1行目）は、意外性のある事実・劇的な展開・印象的な数字など、読者の興味を強く引くフックにする（単なる結果報告で終わらせない）
- 本文は3〜6段落程度。最後まで読みたくなるよう、山場（決定的な瞬間・逆転劇・記録更新など）を具体的に描写する
- 結果・スコア・決定的な場面など事実は正確に。数字や選手名・固有名詞は検索結果に忠実に
- 印象的なシーンや選手のコメント・記録があれば盛り込む
- 今後の展開（次の試合・決勝の対戦カードなど）に触れる場合は、日本時間での放送・配信予定（テレビ局名や配信サービス名、開始時刻）を検索して必ず本文に含めること。この話題自体が試合中継なら、その中継が日本時間で何時に放送・配信されたか／されるかも明記する
- 全体で400〜800文字程度。読み物として自然な文章にする

出力形式（JSONにしない。本文中の引用符「"」はそのまま自由に使ってよい）:
まず ---POST-START--- とだけ書いた行、続けて投稿本文、続けて ---POST-END--- とだけ書いた行、続けて次の2行を書いてください。---POST-START--- より前には何も書かないこと（前置き・確認・作業報告は一切禁止）:
---POST-START---
（ここに投稿本文）
---POST-END---
source: 使った主な出典メディアの一覧
category: 特集記事`;
  return callClaudePlain(prompt, 3000, 8);
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

breakingがtrueの場合、さらに次の2点も判定してください:
- followUp: 決済・交通・通信・災害・health/safetyなど「生活に直結する話題」で、30分後に詳しい続報記事を出す価値があるか
- uncertain: 原因・影響範囲・復旧見込みなど未確定情報が多く、時間経過で状況が変わりうるか（trueの場合は30分後に加えて2時間後・5時間後にも続報を出す）

以下のJSON形式のみで返答してください:
{
  "breaking": true または false,
  "text": "速報ポストの全文（breakingがfalseなら空文字）",
  "headline": "話題の見出し（重複チェック用の短い要約）",
  "source": "出典メディア名",
  "followUp": true または false,
  "uncertain": true または false
}`;
  return callClaude(prompt, 1000, 4);
}

// ===== 生成: 手動指定の速報（BREAKING_TOPIC指定時のみ） =====
async function generateManualBreaking(state, topic) {
  const recentBreaking = (state.recentBreaking || []).join(' / ');
  const prompt = `${CHARACTER}

Web検索で「${topic}」について詳しく調べてください。関連する複数の報道・一次情報を集め、正確な事実関係を把握してください。

それを元に、この話題を伝える速報ポストを1本作ってください:
- 冒頭は「🚨 速報」または「📈 いま話題」から始める
- 何が起きたかを3〜5行で簡潔に。数字や固有名詞は正確に
- 最後に「（出典: メディア名）」
- 全体で200文字以内

${recentBreaking ? `【既に投稿済みの速報（同じ話題は不可）】: ${recentBreaking}` : ''}

さらに次の2点も判定してください:
- followUp: 決済・交通・通信・災害・health/safetyなど「生活に直結する話題」で、30分後に詳しい続報記事を出す価値があるか
- uncertain: 原因・影響範囲・復旧見込みなど未確定情報が多く、時間経過で状況が変わりうるか（trueの場合は30分後に加えて2時間後・5時間後にも続報を出す）

以下のJSON形式のみで返答してください:
{
  "breaking": true,
  "text": "速報ポストの全文",
  "headline": "話題の見出し（重複チェック用の短い要約）",
  "source": "出典メディア名",
  "followUp": true または false,
  "uncertain": true または false
}`;
  return callClaude(prompt, 1000, 5);
}

// フォローアップ記事の予約。生活直結の話題(followUp)なら30分後、未確定情報が多い場合(uncertain)は
// 2時間後・5時間後にも積む。topicは検索精度のため、手動指定時は元のBREAKING_TOPIC文言を渡す
export function scheduleFollowUps(state, headline, topic, now, followUp, uncertain) {
  if (!followUp) return;
  state.breakingFollowUps = state.breakingFollowUps || [];
  const stages = uncertain
    ? [[30, '30分後'], [120, '2時間後'], [300, '5時間後']]
    : [[30, '30分後']];
  for (const [min, stageLabel] of stages) {
    state.breakingFollowUps.push({ headline, topic, stageLabel, dueAt: now + min * 60000, attempts: 0 });
  }
}

// ===== 生成: 速報のフォローアップ記事（30分後・2時間後・5時間後） =====
async function generateFollowUp(state, entry) {
  const prompt = `${CHARACTER}

Web検索で「${entry.topic}」の最新状況を調べてください（速報から${entry.stageLabel}時点）。
先ほど速報した内容: 「${entry.headline}」

それを元に、続報記事を1本作ってください（クイズ形式にはしない。通常の記事文体で）:
- 見出し（1行目）は、新たに分かったこと・進展・変化を伝えるフックにする
- 本文は3〜6段落程度。原因・影響範囲・対応状況・今後の見通しなど生活者が知りたい実用的な情報を具体的に
- 対処法・回避策・解決策がある場合は必ず盛り込む（読者がフォローするきっかけになる重要な情報）
- 事実・数字・固有名詞は検索結果に忠実に。全体で400〜800文字程度
- 前回の速報時点から本質的に新しい情報が無い場合（同じ内容の繰り返しにしかならない場合）は、無理に記事化せず本文を空にすること

出力形式（JSONにしない。本文中の引用符「"」はそのまま自由に使ってよい）:
まず ---POST-START--- とだけ書いた行、続けて投稿本文（更新なしの場合は何も書かない）、続けて ---POST-END--- とだけ書いた行、続けて次の3行を書いてください。---POST-START--- より前には何も書かないこと（前置き・確認・作業報告は一切禁止）:
---POST-START---
（ここに投稿本文）
---POST-END---
update: 新しい情報があれば yes、無ければ no
source: 使った主な出典メディアの一覧
category: 続報（${entry.stageLabel}）`;
  return callClaudePlain(prompt, 3000, 8, true);
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
  state.postHistory.unshift({ tweetId, kind, category: category || '', textPreview: safeSlice(textPreview || '', 80), postedAt });
  state.postHistory = state.postHistory.slice(0, 30);
}

// 直近の新規投稿からMIN_POST_GAP_MS以上経っているか（速報とスロット投稿が接近しすぎるのを防ぐ）
function spacingOk(state, now) {
  return (now - (state.lastAnyPostAt || 0)) >= MIN_POST_GAP_MS;
}

// Pollクイズを生成して投稿する（12時/17時の通常スロットと、朝の速報チェックポイントで
// 速報が無かった場合の代替枠の両方から呼ばれる）。DRY_RUN時は投稿せずfalseを返す
async function postPollQuiz(state, genre, now) {
  const quiz = await generatePollQuiz(state, genre);
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
    return false;
  }

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
      question: safeSlice(quiz.question || '', 60),
      postedAt: now,
      dueAt: now + ANSWER_DELAY_MS,
      isPoll: !!poll,
    });
  }
  state.recentTopics = [quiz.source || quiz.category || '', ...state.recentTopics].filter(Boolean).slice(0, 8);
  state.recentOpeners = [safeSlice(quiz.question || '', 40), ...state.recentOpeners].filter(Boolean).slice(0, 5);
  state.lastPostedAt = now;
  countPost(state, now);
  recordPost(state, { tweetId, kind: 'quiz', category: quiz.category, textPreview: quiz.question, postedAt: now });
  return true;
}

// ===== メイン =====
async function main() {
  const DELETE_TWEET_ID = (process.env.DELETE_TWEET_ID || '').trim();
  const GET_TWEET_ID = (process.env.GET_TWEET_ID || '').trim();
  const missing = [];
  if (!ANTHROPIC_API_KEY && !process.env.MOCK_QUIZ_JSON && !TEST_POST) missing.push('ANTHROPIC_API_KEY');
  if (!DRY_RUN || TEST_POST || DELETE_TWEET_ID || GET_TWEET_ID) {
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

  // 投稿内容確認モード: GET_TWEET_ID が指定された時だけ、その投稿の本文全文を表示して終了する（保守用・読み取りのみ）
  if (GET_TWEET_ID) {
    // 280文字を超える長文投稿（note tweet）は通常のtextフィールドが280文字で切り詰められるため、
    // note_tweet.textを優先的に見る（無ければ通常のtextにフォールバック）
    const json = await apiGet('/2/tweets', { ids: GET_TWEET_ID, 'tweet.fields': 'text,note_tweet' });
    const text = json.data?.[0]?.note_tweet?.text || json.data?.[0]?.text || '(取得できませんでした)';
    console.log(`📄 tweet ${GET_TWEET_ID} の本文:\n${text}`);
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

  // 特集記事モード: FEATURE_TOPIC が指定された時だけ、番組表とは無関係にその話題の特集記事を1本投稿する（保守用）
  const FEATURE_TOPIC = (process.env.FEATURE_TOPIC || '').trim();
  if (FEATURE_TOPIC) {
    if (!DRY_RUN && !canPost(state, now)) {
      console.log('⚠️ 月間投稿上限に達したため特集記事の投稿を見送ります');
      return;
    }
    if (!DRY_RUN && !spacingOk(state, now)) {
      console.log('⏳ 前回の投稿から30分経っていないため特集記事の投稿を見送ります');
      return;
    }
    const feature = await generateFeature(FEATURE_TOPIC);
    if (!feature.text) throw new Error('生成結果に text がありません');
    console.log(`🧠 生成した特集記事（${feature.text.length}文字）:\n${feature.text}\n`);
    if (DRY_RUN) {
      console.log(`🧪 [DRY_RUN] 投稿はスキップします`);
    } else {
      const tweetId = await postTweet(feature.text, null);
      console.log(`🐦 特集記事を投稿しました（tweet: ${tweetId}）`);
      state.lastPostedAt = now;
      countPost(state, now);
      recordPost(state, { tweetId, kind: 'feature', category: feature.category || FEATURE_TOPIC, textPreview: feature.text, postedAt: now });
      saveState(state);
      console.log('💾 state.json を更新しました');
    }
    return;
  }

  // 手動指定の速報モード: BREAKING_TOPIC が指定された時だけ、その話題の速報を1本投稿する（保守用）
  const BREAKING_TOPIC = (process.env.BREAKING_TOPIC || '').trim();
  if (BREAKING_TOPIC) {
    const today0 = jstDateKey(now);
    if (state.breakingDate !== today0) { state.breakingDate = today0; state.breakingCount = 0; }
    if (!DRY_RUN && !canPost(state, now)) {
      console.log('⚠️ 月間投稿上限に達したため速報の投稿を見送ります');
      return;
    }
    if (!DRY_RUN && state.breakingCount >= BREAKING_MAX_PER_DAY) {
      console.log(`⚠️ 本日の速報投稿上限（1日${BREAKING_MAX_PER_DAY}回）に達しているため見送ります`);
      return;
    }
    if (!DRY_RUN && !spacingOk(state, now)) {
      console.log('⏳ 前回の投稿から30分経っていないため速報の投稿を見送ります');
      return;
    }
    const b = await generateManualBreaking(state, BREAKING_TOPIC);
    if (!b.text) throw new Error('生成結果に text がありません');
    console.log(`🧠 生成した速報（${b.text.length}文字）:\n${b.text}\n`);
    if (DRY_RUN) {
      console.log(`🧪 [DRY_RUN] 投稿はスキップします`);
    } else {
      const tweetId = await postTweet(b.text, null);
      console.log(`🐦 速報を投稿しました（tweet: ${tweetId}）`);
      state.recentBreaking = [b.headline, ...state.recentBreaking].filter(Boolean).slice(0, 10);
      state.breakingCount++;
      state.lastPostedAt = now;
      countPost(state, now);
      recordPost(state, { tweetId, kind: 'breaking', category: b.headline, textPreview: b.text, postedAt: now });
      scheduleFollowUps(state, b.headline, BREAKING_TOPIC, now, b.followUp, b.uncertain);
      saveState(state);
      console.log('💾 state.json を更新しました');
    }
    return;
  }

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
      const gen = profile.kind === 'briefing' ? await generateBriefing(state, now) : await generateRecap(state, now);
      if (!gen.text) throw new Error('生成結果に text がありません');
      console.log(`🧠 生成した${gen.category}（${gen.text.length}文字）:\n${safeSlice(gen.text, 300)}…\n`);
      if (DRY_RUN) {
        console.log(`🧪 [DRY_RUN] 全文:\n${gen.text}`);
      } else {
        const tweetId = await postTweet(gen.text, null);
        console.log(`🐦 Xに投稿しました（tweet: ${tweetId}）`);
        state.recentTopics = [gen.source || gen.category, ...state.recentTopics].filter(Boolean).slice(0, 8);
        state.recentOpeners = [safeSlice(gen.text, 40), ...state.recentOpeners].filter(Boolean).slice(0, 5);
        state.lastPostedAt = now;
        countPost(state, now);
        recordPost(state, { tweetId, kind: profile.kind, category: gen.category, textPreview: gen.text, postedAt: now });
        stateChanged = true;
      }

    } else { // quiz（Poll形式）
      const posted = await postPollQuiz(state, profile.genre, now);
      if (posted) stateChanged = true;
    }
  } else if (slotUnposted && tooLate) {
    console.log(`⏭ ${slotStr} のスロットは未投稿ですが、${delayMin}分経過しているため見送ります（次のスロットから再開）`);
  } else {
    console.log('⏭ 直近スロットは投稿済み（返信キューと速報チェックのみ）');
  }

  // --- 2.5. 速報のフォローアップ記事（生活直結の速報のみ・30分後、未確定なら2時間後・5時間後にも） ---
  state.breakingFollowUps = state.breakingFollowUps || [];
  const followUpIdx = state.breakingFollowUps.findIndex(f => f.dueAt <= now);
  if (followUpIdx !== -1 && !process.env.MOCK_QUIZ_JSON) {
    const entry = state.breakingFollowUps[followUpIdx];
    if (!DRY_RUN && !canPost(state, now)) {
      console.log(`⚠️ 月間投稿上限のためフォローアップ記事（${entry.headline}）を見送ります`);
      state.breakingFollowUps.splice(followUpIdx, 1);
      stateChanged = true;
    } else if (!DRY_RUN && !spacingOk(state, now)) {
      // 連投リスクを避けるため無理に投稿せず、まず後ろにずらす（最大4回=最大2時間分。それでも空かなければ諦める）
      entry.attempts = (entry.attempts || 0) + 1;
      if (entry.attempts > 4) {
        console.log(`⏭ フォローアップ記事（${entry.headline}・${entry.stageLabel}）は間隔調整が続いたため中止します`);
        state.breakingFollowUps.splice(followUpIdx, 1);
      } else {
        entry.dueAt = now + MIN_POST_GAP_MS;
        console.log(`⏳ 投稿間隔が足りないため、フォローアップ記事（${entry.headline}）を後ろにずらします（試行${entry.attempts}/4）`);
      }
      stateChanged = true;
    } else {
      try {
        const followUp = await generateFollowUp(state, entry);
        state.breakingFollowUps.splice(followUpIdx, 1);
        stateChanged = true;
        if (!followUp.text) {
          console.log(`📡 フォローアップ記事（${entry.headline}・${entry.stageLabel}）: 新しい情報が無いため見送ります`);
        } else if (DRY_RUN) {
          console.log(`🧪 [DRY_RUN] フォローアップ記事:\n${followUp.text}`);
        } else {
          const tweetId = await postTweet(followUp.text, null);
          console.log(`🐦 フォローアップ記事を投稿しました（tweet: ${tweetId}）`);
          state.lastPostedAt = now;
          countPost(state, now);
          recordPost(state, { tweetId, kind: 'feature', category: followUp.category || `続報（${entry.stageLabel}）`, textPreview: followUp.text, postedAt: now });
        }
      } catch (e) {
        console.error(`⚠️ フォローアップ記事の生成に失敗（${entry.headline}）: ${e.message}（このステージは見送ります）`);
        state.breakingFollowUps.splice(followUpIdx, 1);
        stateChanged = true;
      }
    }
  }

  // --- 3. 速報チェック（固定時刻: 深夜2:00/4:00・朝9:30〜11:00・午後14〜16時） ---
  const today = jstDateKey(now);
  if (state.breakingDate !== today) { state.breakingDate = today; state.breakingCount = 0; }
  state.breakingCheckpointsDone = (state.breakingCheckpointsDone || []).filter(k => k.startsWith(today));
  const checkpoint = BREAKING_ENABLED ? findDueCheckpoint(now, state.breakingCheckpointsDone) : null;
  if (checkpoint && !process.env.MOCK_QUIZ_JSON) { // MOCKテスト時はスロット側のみ検証
    if (state.breakingCount >= BREAKING_MAX_PER_DAY) {
      console.log(`⏭ 固定時刻チェック(${checkpoint.hm})は本日の速報投稿上限（${BREAKING_MAX_PER_DAY}回）に達しているため見送ります`);
      state.breakingCheckpointsDone.push(checkpoint.key);
      stateChanged = true;
    } else if (!DRY_RUN && !spacingOk(state, now)) {
      // 直前にスロット投稿等があった場合は間隔を優先しスキップ。猶予時間内なら次回の実行で再試行
      console.log(`⏳ 固定時刻チェック(${checkpoint.hm})は投稿間隔が足りないため、猶予時間内に次回再試行します`);
    } else {
      state.breakingCheckpointsDone.push(checkpoint.key);
      stateChanged = true;
      try {
        const b = await checkBreaking(state);
        if (b.breaking && b.text) {
          console.log(`🚨 速報を検知（${checkpoint.hm}チェック）: ${b.headline}`);
          if (DRY_RUN) {
            console.log(`🧪 [DRY_RUN] 速報投稿:\n${b.text}`);
          } else if (canPost(state, now)) {
            const tweetId = await postTweet(b.text, null);
            console.log(`🐦 速報を投稿しました（tweet: ${tweetId}）`);
            state.recentBreaking = [b.headline, ...state.recentBreaking].filter(Boolean).slice(0, 10);
            state.breakingCount++;
            countPost(state, now);
            recordPost(state, { tweetId, kind: 'breaking', category: b.headline, textPreview: b.text, postedAt: now });
            // forceArticleの枠（深夜）はAIの自己判定に関わらず必ず続報を予約する
            scheduleFollowUps(state, b.headline, b.headline, now, checkpoint.forceArticle || b.followUp, b.uncertain);
            state.lastPostedAt = now;
          }
        } else if (checkpoint.fallback === 'quiz') {
          console.log(`📡 固定時刻チェック(${checkpoint.hm}): 速報なし → 代わりに軽めのクイズを投稿します`);
          if (!DRY_RUN && !canPost(state, now)) {
            console.log('⚠️ 月間投稿上限に達したためクイズ投稿を見送ります');
          } else {
            const posted = await postPollQuiz(state, '午前のちょっとした時事・スポーツ・エンタメの軽い話題', now);
            if (posted) stateChanged = true;
          }
        } else {
          console.log(`📡 固定時刻チェック(${checkpoint.hm}): 該当なし`);
        }
      } catch (e) {
        console.error(`⚠️ 固定時刻チェック(${checkpoint.hm})に失敗: ${e.message}（次回に再試行）`);
      }
    }
  }

  if (stateChanged && !DRY_RUN) {
    saveState(state);
    console.log('💾 state.json を更新しました');
  }
  console.log('✅ 完了');
}

// テストからこのファイルをimportした際に自動実行されないよう、直接実行時のみmain()を起動する
if (import.meta.url === `file://${process.argv[1]}`) {
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
}
