const express = require('express');
const { WebSocketServer } = require('ws');
const fs = require('fs');
const path = require('path');
const https = require('https');
const crypto = require('crypto');

// .env ファイルがあれば読み込む（dotnet不要の簡易実装）
const envFile = path.join(__dirname, '.env');
if (fs.existsSync(envFile)) {
  fs.readFileSync(envFile, 'utf8').split('\n').forEach(line => {
    const [k, ...v] = line.trim().split('=');
    if (k && v.length && !process.env[k]) process.env[k] = v.join('=');
  });
}

const PORT = process.env.PORT || 3000;
const AUTH_TOKEN = process.env.AUTH_TOKEN;
const STATE_FILE = path.join(__dirname, 'state.json');

if (!AUTH_TOKEN) {
  console.error('ERROR: AUTH_TOKEN 環境変数が必要です。');
  console.error('例: AUTH_TOKEN=<secret> node server.js');
  console.error('トークン生成: node -e "console.log(require(\'crypto\').randomBytes(32).toString(\'hex\'))"');
  process.exit(1);
}

// Twitter OAuth 1.0a 設定（.envで任意設定）
const TW_CONSUMER_KEY    = process.env.TWITTER_CONSUMER_KEY || '';
const TW_CONSUMER_SECRET = process.env.TWITTER_CONSUMER_SECRET || '';
const TW_ACCESS_TOKEN    = process.env.TWITTER_ACCESS_TOKEN || '';
const TW_ACCESS_SECRET   = process.env.TWITTER_ACCESS_TOKEN_SECRET || '';
const twitterEnabled = !!(TW_CONSUMER_KEY && TW_CONSUMER_SECRET && TW_ACCESS_TOKEN && TW_ACCESS_SECRET);

// メール設定（.envで任意設定）
const SMTP_HOST = process.env.SMTP_HOST || '';
const SMTP_PORT = parseInt(process.env.SMTP_PORT || '587', 10);
const SMTP_USER = process.env.SMTP_USER || '';
const SMTP_PASS = process.env.SMTP_PASS || '';
const NOTIFY_TO   = process.env.NOTIFY_EMAIL_TO || '';
const NOTIFY_FROM = process.env.NOTIFY_EMAIL_FROM || SMTP_USER;
const emailEnabled = SMTP_HOST && SMTP_USER && SMTP_PASS && NOTIFY_TO;

const app = express();
app.use(express.json());
app.use(express.static(__dirname));

// API認証ミドルウェア
function requireToken(req, res, next) {
  const token = req.headers['x-auth-token'];
  if (token !== AUTH_TOKEN) return res.status(401).json({ ok: false, error: 'Unauthorized' });
  next();
}

// ===== Twitter API: ツイート投稿 =====
app.post('/api/tweet', requireToken, async (req, res) => {
  if (!twitterEnabled) {
    return res.json({ ok: false, error: 'Twitter API未設定' });
  }
  const { text, replyToId } = req.body;
  if (!text) return res.status(400).json({ ok: false, error: 'text is required' });

  try {
    const tweetId = await postTweet(text, replyToId || null);
    res.json({ ok: true, tweetId });
  } catch (e) {
    console.error('Twitter投稿エラー:', e.message);
    res.status(500).json({ ok: false, error: e.message });
  }
});

// ===== Twitter API 設定確認 =====
app.get('/api/twitter-status', requireToken, (req, res) => {
  res.json({ enabled: twitterEnabled });
});

// ===== メール通知 =====
app.post('/api/notify', requireToken, async (req, res) => {
  if (!emailEnabled) {
    return res.json({ ok: false, reason: 'not_configured' });
  }
  const { subject, body } = req.body;
  if (!subject) return res.status(400).json({ ok: false, error: 'subject is required' });

  try {
    await sendEmail(subject, body || '');
    res.json({ ok: true });
  } catch (e) {
    console.error('メール送信エラー:', e.message);
    res.status(500).json({ ok: false, error: e.message });
  }
});

// ===== OAuth 1.0a 署名生成 =====
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
  const headerValue = 'OAuth ' + Object.keys(oauthParams).sort().map(k =>
    encodeURIComponent(k) + '="' + encodeURIComponent(oauthParams[k]) + '"'
  ).join(', ');
  return headerValue;
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
          else reject(new Error(json.detail || JSON.stringify(json)));
        } catch { reject(new Error(data)); }
      });
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

// ===== メール送信（nodemailerを動的require） =====
async function sendEmail(subject, body) {
  const nodemailer = require('nodemailer');
  const transporter = nodemailer.createTransport({
    host: SMTP_HOST,
    port: SMTP_PORT,
    secure: SMTP_PORT === 465,
    auth: { user: SMTP_USER, pass: SMTP_PASS },
  });
  await transporter.sendMail({
    from: NOTIFY_FROM,
    to: NOTIFY_TO,
    subject,
    text: body,
  });
}

const server = app.listen(PORT, () => {
  console.log(`クイズBot サーバー起動: http://localhost:${PORT}`);
  console.log('外部公開: cloudflared tunnel --url http://localhost:' + PORT);
  console.log('X自動投稿: ' + (twitterEnabled ? '✅ 有効' : '⬜ 未設定（.envにTwitterキーを追加）'));
  console.log('メール通知: ' + (emailEnabled ? '✅ 有効' : '⬜ 未設定（.envにSMTP設定を追加）'));
});

const wss = new WebSocketServer({ server });

let currentState = loadStateFromDisk();
const authenticated = new Set();

wss.on('connection', (ws) => {
  const msgCounts = { count: 0, resetAt: Date.now() };

  ws.on('message', (raw) => {
    // DoSガード: 10秒に100メッセージ超は切断
    const now = Date.now();
    if (now - msgCounts.resetAt > 10000) {
      msgCounts.count = 0;
      msgCounts.resetAt = now;
    }
    msgCounts.count++;
    if (msgCounts.count > 100) { ws.close(); return; }

    // サイズガード: 1MB超は切断
    if (raw.length > 1_000_000) { ws.close(); return; }

    let msg;
    try { msg = JSON.parse(raw); } catch { ws.close(); return; }

    if (msg.type === 'auth') {
      if (msg.token === AUTH_TOKEN) {
        authenticated.add(ws);
        ws.send(JSON.stringify({ type: 'auth_ok' }));
        // 現在の状態を送信
        if (currentState && Object.keys(currentState).length > 0) {
          ws.send(JSON.stringify({ type: 'state_init', state: currentState }));
        }
      } else {
        ws.send(JSON.stringify({ type: 'auth_fail', reason: 'Invalid token' }));
        ws.close();
      }
      return;
    }

    if (!authenticated.has(ws)) { ws.close(); return; }

    if (msg.type === 'state_push' && msg.state) {
      const incoming = msg.state;
      const localVer = currentState.stateVersion || 0;
      const incomingVer = incoming.stateVersion || 0;

      if (incomingVer > localVer) {
        currentState = incoming;
        saveStateToDisk(currentState);

        // 他の認証済みクライアントへ中継
        for (const client of wss.clients) {
          if (client !== ws && client.readyState === 1 && authenticated.has(client)) {
            client.send(JSON.stringify({ type: 'state_push', state: currentState }));
          }
        }
      }
    }
  });

  ws.on('close', () => authenticated.delete(ws));
  ws.on('error', () => authenticated.delete(ws));
});

function loadStateFromDisk() {
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
  } catch {
    return {};
  }
}

function saveStateToDisk(state) {
  const tmp = STATE_FILE + '.tmp';
  try {
    fs.writeFileSync(tmp, JSON.stringify(state));
    fs.renameSync(tmp, STATE_FILE);
  } catch (e) {
    console.error('状態の保存に失敗:', e.message);
  }
}
