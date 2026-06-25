const express = require('express');
const { WebSocketServer } = require('ws');
const fs = require('fs');
const path = require('path');

const PORT = process.env.PORT || 3000;
const AUTH_TOKEN = process.env.AUTH_TOKEN;
const STATE_FILE = path.join(__dirname, 'state.json');

if (!AUTH_TOKEN) {
  console.error('ERROR: AUTH_TOKEN 環境変数が必要です。');
  console.error('例: AUTH_TOKEN=<secret> node server.js');
  console.error('トークン生成: node -e "console.log(require(\'crypto\').randomBytes(32).toString(\'hex\'))"');
  process.exit(1);
}

const app = express();
app.use(express.static(__dirname));

const server = app.listen(PORT, () => {
  console.log(`クイズBot サーバー起動: http://localhost:${PORT}`);
  console.log('外部公開: cloudflared tunnel --url http://localhost:' + PORT);
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
