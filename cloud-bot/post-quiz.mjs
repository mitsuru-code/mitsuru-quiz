// ============================================================
// クラウドBot: 時事クイズを生成してXへ自動投稿する（GitHub Actions用）
//
// PC常駐だった server.js（X投稿）とブラウザ側の生成ロジックを
// GitHub Actions の定時実行に移設したもの。
//
// 動作:
//   1. state.json の返信キューを確認し、期限が来た正解をスレッド返信
//   2. 現在時刻(JST)が POST_SLOTS に該当すれば、クイズを生成してXへ投稿
//      投稿した正解文は返信キューに登録（ANSWER_DELAY_HOURS 後に返信）
//
// 環境変数:
//   ANTHROPIC_API_KEY            … クイズ生成用（必須）
//   TWITTER_CONSUMER_KEY/SECRET  … X API OAuth 1.0a（必須）
//   TWITTER_ACCESS_TOKEN/SECRET  … X API OAuth 1.0a（必須）
//   POST_SLOTS                   … 投稿するJST時刻（既定 "7,12,17,21"）
//   ANSWER_DELAY_HOURS           … 正解返信までの時間（既定 2）
//   GENRE                        … 出題ジャンル（既定 mixed）
//   DRY_RUN                      … "true" なら生成のみ・投稿せずログ出力
//   FORCE_POST                   … "true" ならスロット外でも投稿（手動テスト用）
//   MOCK_QUIZ_JSON               … テスト用: APIを呼ばずこのJSONを生成結果として使う
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
const POST_SLOTS = (process.env.POST_SLOTS || '7,12,17,21').split(',').map(s => parseInt(s.trim(), 10)).filter(n => !isNaN(n));
const ANSWER_DELAY_MS = (parseFloat(process.env.ANSWER_DELAY_HOURS || '2')) * 3600 * 1000;
const GENRE = process.env.GENRE || 'mixed';

// Secretsコピペ時の前後空白・改行はOAuth署名を壊すため必ず除去する
const cleanEnv = k => (process.env[k] || '').trim();
const ANTHROPIC_API_KEY = cleanEnv('ANTHROPIC_API_KEY');
const TW_CONSUMER_KEY    = cleanEnv('TWITTER_CONSUMER_KEY');
const TW_CONSUMER_SECRET = cleanEnv('TWITTER_CONSUMER_SECRET');
const TW_ACCESS_TOKEN    = cleanEnv('TWITTER_ACCESS_TOKEN');
const TW_ACCESS_SECRET   = cleanEnv('TWITTER_ACCESS_TOKEN_SECRET');
const TEST_POST = process.env.TEST_POST === 'true';

// ===== JSTスロット計算 =====
function jstHourOf(ms) {
  return parseInt(new Intl.DateTimeFormat('ja-JP', { timeZone: 'Asia/Tokyo', hour: 'numeric', hour12: false }).format(new Date(ms)), 10);
}

// 現在時刻以前で最も新しい投稿スロットの時刻(epoch ms)を返す
function latestSlotEpoch(nowMs) {
  const jst = new Date(nowMs + 9 * 3600 * 1000); // JSTの壁時計をUTCメソッドで読むためのシフト
  const sorted = [...POST_SLOTS].sort((a, b) => a - b);
  let slotHour = null;
  let dayOffset = 0;
  for (const s of sorted) {
    if (s <= jst.getUTCHours()) slotHour = s;
  }
  if (slotHour === null) { // 今日のスロットがまだ来ていない → 前日の最終スロット
    slotHour = sorted[sorted.length - 1];
    dayOffset = -1;
  }
  // JSTのslotHour:00 をUTCに戻す
  return Date.UTC(jst.getUTCFullYear(), jst.getUTCMonth(), jst.getUTCDate() + dayOffset, slotHour - 9, 0, 0);
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

function postTweet(text, replyToId) {
  return new Promise((resolve, reject) => {
    const apiUrl = 'https://api.twitter.com/2/tweets';
    const body = JSON.stringify(replyToId
      ? { text, reply: { in_reply_to_tweet_id: replyToId } }
      : { text }
    );
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

// ===== クイズ生成（index.html の generateQuiz テーマモードを移植） =====
const genreMap = {
  mixed:   '直近2〜3日の重要な時事問題（国内・国際・経済・科学などバランス良く。Reuters/AP/NHK/日経/BBCを幅広く検索すること）',
  world:   '直近2〜3日の国際ニュース（Reuters/AP/BBC/CNN/Bloomberg/Al Jazeera等の英語メディアを優先検索し、海外目線の話題を取り上げること）',
  japan:   '直近2〜3日の日本国内ニュース（NHK/日経/朝日/共同通信等）',
  economy: '直近2〜3日の経済・ビジネスニュース（国内外含む。Bloomberg/日経/Reutersを検索）',
  science: '直近の科学・テクノロジーニュース（Nature/Science/TechCrunch/国内IT媒体を含む）',
  sports:  '直近のスポーツニュース（国内外含む。MLB/NBA/欧州サッカー/大相撲等も対象）'
};

const pick = arr => arr[Math.floor(Math.random() * arr.length)];

function buildPrompt(recentTopics, recentOpeners) {
  const quizFormat = pick([
    { name: '4択', instruction: `【形式: 4択クイズ】
- 選択肢は4つ（記号は ${pick(['A/B/C/D', '①②③④', '1)/2)/3)/4)', 'ア/イ/ウ/エ'])} を使う）
- ダミー選択肢も"ありそうで紛らわしい"ものにする
- 正解の位置（何番目か）を毎回変える` },
    { name: '二択', instruction: `【形式: 二択クイズ】
- 選択肢は2つだけ（例: A か B か、増加か減少か、日本か海外か、など対比が明確なもの）
- 「どちらでしょう？」「AとBどっち？」のように問いかける
- シンプルで答えやすく、返信率が上がる形式` },
    { name: '空欄埋め', instruction: `【形式: 空欄埋めクイズ】
- 文章の重要な部分を「【　】」や「○○」で伏せて、その答えを問う
- 例: 「○○国が△△を発表。○○に入る国名は？」
- 選択肢は付けず、回答者にリプライで答えてもらう形式（正解は返信で発表）
- 「リプライで答えてみて！」の一言を入れる` },
    { name: '数字当て', instruction: `【形式: 数字当てクイズ】
- 具体的な数字（割合・人数・金額・順位・年数など）を問う
- 選択肢なしか、あるいは数字の範囲を3〜4択で提示する
- 例: 「日本の〇〇は世界何位？」「〇〇の利用者数は何万人？」
- 数字の意外性が「へぇ」を生みやすい` },
    { name: '○×', instruction: `【形式: ○×クイズ】
- 1つの文章が「正しいか間違いか」を問う
- 「〇か✕か」「本当？嘘？」「正しい？間違い？」のような問いかけ
- 選択肢は「〇（正しい）」「✕（間違い）」の2択のみ
- 最もシンプルで参加しやすく、幅広い層が答えやすい` },
    { name: 'ディエゴ（間違い探し）', instruction: `【形式: ディエゴ（間違い探し）クイズ】
- A・B・Cの3つの文を提示し、「このうち間違っているのはどれ？」と問う
- 2つは正しく、1つだけ事実と異なる内容にする
- 例: 「次のうち間違っているのはどれでしょう？A:〜 B:〜 C:〜」
- 上級者向けで他との差別化になる。正解発表時に全文の解説を入れる` }
  ]);

  const styleOpener = pick([
    '時事ネタを軽い驚きとともに切り出す（例:「え、これ知ってた？」）',
    'ニュースを見た感想から入る（例:「これ朝のニュースで気になった話」）',
    'いきなり本題の問いかけから入る（前置きを省く）',
    'クイズ好きに語りかける感じ（例:「今日の一問いきます」）',
    '時事の背景を一文添えてから問う',
    'ちょっと意外性を強調する（例:「意外と間違える人多いやつ」）'
  ]);
  const styleLength = pick(['短めにテンポよく', '少し丁寧に背景も添えて', 'ごく簡潔に', '会話するように自然な長さで']);
  const styleEmoji = pick(['絵文字は1個だけ控えめに', '絵文字なしで文章勝負', '絵文字を2個ほど効果的に', '顔文字や記号で表情をつける']);

  const humanizeBlock = `【キャラクター設定】
あなたはX(Twitter)の時事クイズアカウント「クイズハム🐹」の中の人です。キンクマハムスターがモチーフですが、キャラは"ほんのり"効かせる程度に抑え、誰が読んでも自然で親しみやすい文章にします:
- 基本は親しみやすく丁寧な口調。時々「🐹」の絵文字や軽い一言で愛嬌を出す程度に留める
- 「〜なのだ」「ハムっ」「むしゃむしゃ」などの濃いキャラ語尾は多用しない（ごくたまに、自然な範囲で）
- 出題は「今日の一問です🐹」「これ、わかりますか？」のように、親しみはありつつ読みやすさ優先
- 解答は「正解は○○でした！」のように素直に。できた人を軽く褒め、外した人も励ます一言を添える
- キャラより「内容の分かりやすさ」と「読みやすさ」を優先する

${quizFormat.instruction}

【スタイル（今回）】
- 書き出し: ${styleOpener}
- 文章量: ${styleLength}
- 絵文字: ${styleEmoji}（🐹は時々でよい）
- 「問題:」「クイズ:」のような機械的な見出しは使わない
- 改行位置や句読点も毎回変え、定型パターンにならないようにする`;

  return `あなたはX(Twitter)で時事クイズを毎日出している、人気アカウントの「中の人」です。Web検索で${genreMap[GENRE] || genreMap.mixed}を1件調べ、それを元に【${quizFormat.name}】形式のクイズを1問作ってください。

${humanizeBlock}

【厳守事項】
- 必ずWeb検索を実行し、信頼できる報道機関（Reuters、AP通信、NHK、日経、BBC、共同通信等）や公式発表を根拠にすること。推測や古い知識で作らない
- 事実（数字・固有名詞・日付）は正確に
- クイズ本文は日本語で全体220文字以内（出典ハッシュタグ含む）
- 文末に出典を「#出典 メディア名」の形で必ず記載
- 解説（正解返信用）は雑学を含めて220文字程度まで
${recentTopics ? '- 【重複禁止・トピック】以下と異なるニュースを選ぶこと（同じ人物・企業・事件はNG）: ' + recentTopics : ''}
${recentOpeners ? '- 【重複禁止・文章表現】以下は直近の問題文の冒頭。これらと書き出し・文体・構成が被らないようにすること: ' + recentOpeners : ''}
- 選択肢の並び順・正解の位置（A/B/C/Dのどれか）・ダミー選択肢の内容も毎回変える。正解が同じ記号（例:常にB）にならないこと

以下のJSON形式のみで返答してください。前置きやMarkdownのコードブロックは不要です:
{
  "question": "クイズ投稿の全文（【${quizFormat.name}】形式で、自然で親しみやすい口調のツカミ＋問いかけ＋#出典）",
  "answer": "正解返信用の全文。次の3部構成で：①『正解は○○でした！』のように素直に答え合わせ（軽く褒める/励ます一言を添える）②なぜその答えなのか簡潔な解説 ③『🌰豆知識』として、思わず『へぇ』と言いたくなる関連雑学を1つ添える。全体で200文字程度。キャラは控えめに、読みやすさ優先",
  "source": "出典メディア名と記事タイトル",
  "sourceUrl": "出典記事の正確なURL（Web検索で得た実在するURLのみ。不明な場合は空文字）",
  "category": "ジャンル名（形式も含める例:『経済・二択』）"
}`;
}

async function generateQuiz(state) {
  // テスト用フック: MOCK_QUIZ_JSON があればAPIを呼ばない
  if (process.env.MOCK_QUIZ_JSON) {
    return JSON.parse(process.env.MOCK_QUIZ_JSON);
  }

  const recentTopics = (state.recentTopics || []).join(' / ');
  const recentOpeners = (state.recentOpeners || []).join(' / ');
  const prompt = buildPrompt(recentTopics, recentOpeners);

  const res = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': ANTHROPIC_API_KEY,
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify({
      model: 'claude-sonnet-4-6',
      max_tokens: 1200,
      messages: [{ role: 'user', content: prompt }],
      tools: [{ type: 'web_search_20250305', name: 'web_search' }]
    })
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error?.message || `Anthropic APIエラー (${res.status})`);
  }
  const data = await res.json();
  const text = data.content.filter(i => i.type === 'text').map(i => i.text).join('');
  const clean = text.replace(/```json|```/g, '').trim();
  const match = clean.match(/\{[\s\S]*\}/);
  if (!match) throw new Error('生成結果にJSONが見つかりません');
  return JSON.parse(match[0]);
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

// ===== メイン =====
async function main() {
  const missing = [];
  if (!ANTHROPIC_API_KEY && !process.env.MOCK_QUIZ_JSON && !TEST_POST) missing.push('ANTHROPIC_API_KEY');
  if (!DRY_RUN || TEST_POST) {
    if (!TW_CONSUMER_KEY) missing.push('TWITTER_CONSUMER_KEY');
    if (!TW_CONSUMER_SECRET) missing.push('TWITTER_CONSUMER_SECRET');
    if (!TW_ACCESS_TOKEN) missing.push('TWITTER_ACCESS_TOKEN');
    if (!TW_ACCESS_SECRET) missing.push('TWITTER_ACCESS_TOKEN_SECRET');
  }
  if (missing.length) {
    console.error('❌ 環境変数が不足しています: ' + missing.join(', '));
    process.exit(1);
  }

  // 接続テストモード: クイズ生成をスキップし、X認証だけを検査する
  if (TEST_POST) {
    console.log(`🔧 X API接続テスト（キー長: CK=${TW_CONSUMER_KEY.length} / CS=${TW_CONSUMER_SECRET.length} / AT=${TW_ACCESS_TOKEN.length} / AS=${TW_ACCESS_SECRET.length}）`);
    const text = `🔧 クラウドBot接続テスト ${new Date().toISOString()}`;
    const id = await postTweet(text, null);
    console.log(`✅ X APIの接続テストに成功しました（tweet: ${id}）。このテスト投稿はXアプリから削除して構いません`);
    return;
  }

  const state = loadState();
  state.pendingAnswers = state.pendingAnswers || [];
  state.recentTopics = state.recentTopics || [];
  state.recentOpeners = state.recentOpeners || [];

  const now = parseInt(process.env.NOW_MS || '', 10) || Date.now(); // NOW_MSはテスト用フック
  const jstHour = jstHourOf(now);
  const slotEpoch = latestSlotEpoch(now);
  const slotStr = new Intl.DateTimeFormat('ja-JP', { timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(new Date(slotEpoch));
  console.log(`⏰ JST ${jstHour}時 / 投稿スロット: [${POST_SLOTS.join(', ')}] / 直近スロット: ${slotStr} / DRY_RUN=${DRY_RUN} / FORCE_POST=${FORCE_POST}`);

  let stateChanged = false;

  // --- 1. 期限が来た正解をスレッド返信 ---
  const due = state.pendingAnswers.filter(a => a.dueAt <= now);
  for (const item of due) {
    let answerText = item.answer;
    if (item.sourceUrl) answerText += `\n\n📰 詳しくはこちら→ ${item.sourceUrl}`;
    if (DRY_RUN) {
      console.log(`🧪 [DRY_RUN] 正解返信（→ ${item.tweetId}）:\n${answerText}\n`);
    } else {
      try {
        const replyId = await postTweet(answerText, item.tweetId);
        console.log(`💬 正解を返信しました（tweet: ${replyId} → 元: ${item.tweetId}）`);
        state.pendingAnswers = state.pendingAnswers.filter(a => a !== item);
        stateChanged = true;
      } catch (e) {
        console.error(`⚠️ 正解返信に失敗（元: ${item.tweetId}）: ${e.message} — 次回の実行で再試行します`);
      }
    }
  }

  // --- 2. 直近スロットが未投稿ならクイズを生成して投稿（キャッチアップ方式） ---
  // GitHub Actionsのcronは大幅に遅延・スキップされることがあるため、
  // 「起動時刻がスロットと一致したら投稿」ではなく
  // 「直近のスロット時刻以降にまだ投稿していなければ、遅れてでも投稿」する。
  // 取りこぼした古いスロットは追いかけない（直近1回分のみ）ので連投にはならない。
  const delayMin = Math.round((now - slotEpoch) / 60000);
  const tooLate = delayMin > 360; // 6時間超の遅延は深夜投稿等になり逆効果なので見送る
  const slotUnposted = (state.lastPostedAt || 0) < slotEpoch;
  const shouldPost = FORCE_POST || (slotUnposted && !tooLate);
  if (shouldPost) {
    if (!FORCE_POST) {
      console.log(`📮 ${slotStr} のスロットが未投稿のため投稿します（スロットから${delayMin}分経過）`);
    }
    const quiz = await generateQuiz(state);
    if (!quiz.question) throw new Error('生成結果に question がありません');
    console.log(`🧠 生成したクイズ（${quiz.category || '時事'} / ${quiz.question.length}文字）:\n${quiz.question}\n`);

    if (DRY_RUN) {
      console.log(`🧪 [DRY_RUN] 投稿はスキップしました。正解文:\n${quiz.answer || '(なし)'}\n出典: ${quiz.source || '(なし)'} ${quiz.sourceUrl || ''}`);
    } else {
      const tweetId = await postTweet(quiz.question, null);
      console.log(`🐦 Xに投稿しました（tweet: ${tweetId}）`);

      if (quiz.answer) {
        state.pendingAnswers.push({
          tweetId,
          answer: quiz.answer,
          sourceUrl: quiz.sourceUrl || '',
          question: (quiz.question || '').slice(0, 60),
          postedAt: now,
          dueAt: now + ANSWER_DELAY_MS,
        });
      }
      state.recentTopics = [quiz.source || quiz.category || '', ...state.recentTopics].filter(Boolean).slice(0, 8);
      state.recentOpeners = [(quiz.question || '').slice(0, 40), ...state.recentOpeners].filter(Boolean).slice(0, 5);
      state.lastPostedAt = now;
      stateChanged = true;
    }
  } else if (slotUnposted && tooLate) {
    console.log(`⏭ ${slotStr} のスロットは未投稿ですが、${delayMin}分経過しているため見送ります（次のスロットから再開）`);
  } else {
    console.log('⏭ 直近スロットは投稿済みのため、クイズ生成はスキップ（返信キューの処理のみ）');
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
  3. 上記キー長（CK≈25 / CS≈50 / AT≈50 / AS≈45 が目安）が極端に違う場合は値が別物`);
  } else if (e.message.includes('HTTP 403')) {
    console.error(`💡 403(権限拒否)の主な原因:
  1. アプリがProjectに紐付いていない（Developer PortalでProject配下にアプリを作る）
  2. 同一内容の重複投稿
  3. APIプランの制限`);
  }
  process.exit(1);
});
