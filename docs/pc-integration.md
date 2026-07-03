# 🔗 PC自動化システムとの連携ガイド

クイズBotアプリ（Pixel 10a）と、PCで動かしている自動化システムを連携させるための仕様書です。

## 全体像

```
[Pixel 10a: クイズBot PWA]
   │  クイズ生成 → 人間が承認（スマホで完結）
   │
   ├─① Webhook ──── 承認と同時にJSONをPOST ───→ [PCの受信サーバー / n8n / Make]
   │                                                │ 保存・分析・通知・後続処理
   └─② エクスポート/インポート（JSONファイル） ──→ [PCでの一括分析・バックアップ]
```

- **① Webhook連携（リアルタイム）**: アプリの「🔗 PC連携」カードにURLを設定し「承認時に自動送信」をONにすると、クイズを承認した瞬間にPC側へJSONが飛びます
- **② ファイル連携（バッチ）**: 「⬇️ エクスポート」で全履歴をJSONダウンロード。Google Drive等でPCに渡して分析できます。「⬆️ インポート」で逆方向の取り込み（ID重複は自動スキップ）

## PCと連携が取れなくても運用は止まりません

PC連携は完全に**片方向・非ブロッキング**の設計です。PCの電源が落ちていても、ngrokトンネルが切れていても、スマホが圏外でも、**クイズの生成・承認・投稿はPixel単体でそのまま動き続けます**。

- 送信に失敗したペイロードは端末内の**未送信キュー**（最大100件）に保存されます
- **回線復帰時・アプリ起動時・5分ごと**に自動で再送します。「📤 未送信分を今すぐ再送」ボタンで手動再送も可能
- 未送信が溜まっている間は「🔗 PC連携」カードに件数が表示されます
- 送信は10秒でタイムアウトするため、PCが無応答でもアプリが待たされることはありません

---

## ① Webhook ペイロード仕様

`POST {設定したURL}` / `Content-Type: application/json`

```json
{
  "event": "quiz.approved",
  "app": "quizbot",
  "sentAt": "2026-07-02T22:00:00.000Z",
  "secret": "共有シークレット（設定した場合のみ）",
  "quiz": {
    "id": 1719900000000,
    "question": "【時事クイズ】...（投稿本文そのまま）",
    "answer": "正解は...（noAnswer=true のとき null）",
    "category": "経済",
    "sourceUrl": "https://www3.nhk.or.jp/...",
    "mode": "theme",
    "noAnswer": false,
    "approvedAt": 1719900000000,
    "answerDueAt": 1719907200000
  }
}
```

| event | 意味 |
|---|---|
| `quiz.approved` | クイズが承認された（投稿された） |
| `test.ping` | 「📡 テスト送信」ボタン。`quiz` は `null` |

再送されたペイロードには `"retry": true` が付きます。PC側は `quiz.id` で重複排除してください（再送により同じクイズが2回届く可能性があります）。

- `answerDueAt` は正解返信の予定時刻（epoch ms）。PC側で返信のスケジューリングに使えます
- `secret` はボディに含まれます。PC側で照合し、一致しないリクエストは拒否してください

## PC側の受信サーバー要件

ブラウザ（PWA）からのfetchなので **CORS対応が必須** です:

- `OPTIONS` リクエスト（プリフライト）に `204` を返す
- レスポンスヘッダに `Access-Control-Allow-Origin: *`（またはアプリの配信オリジン）と `Access-Control-Allow-Headers: Content-Type` を付ける
- HTTPSで公開する（PWAがHTTPS配信の場合、http:// への送信はブロックされます）。ローカルPCなら **ngrok / cloudflared** でトンネルするのが簡単:
  ```bash
  ngrok http 5000          # → https://xxxx.ngrok.app をアプリに設定
  ```

### 最小構成サンプル（Python / Flask）

```python
from flask import Flask, request, jsonify

app = Flask(__name__)
SECRET = "アプリに設定したのと同じ値"

@app.after_request
def cors(res):
    res.headers["Access-Control-Allow-Origin"] = "*"
    res.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return res

@app.route("/quiz", methods=["POST", "OPTIONS"])
def quiz():
    if request.method == "OPTIONS":
        return "", 204
    data = request.get_json()
    if SECRET and data.get("secret") != SECRET:
        return jsonify(error="unauthorized"), 401
    if data["event"] == "quiz.approved":
        q = data["quiz"]
        print("承認されたクイズ:", q["question"][:40], "...")
        # ここに後続処理（DB保存、通知、スケジューラ登録など）
    return jsonify(ok=True)

app.run(port=5000)
```

### n8n の場合

1. Webhook ノードを追加（HTTP Method: POST）
2. n8n の設定でCORSを許可（`N8N_CORS_ALLOW_ORIGIN=*` 等）
3. 生成されたURLをアプリの「🔗 PC連携」に貼り付け →「📡 テスト送信」で疎通確認
4. 後続ノードで保存・通知・分析を自由に組む

---

## ② エクスポートJSONの形式

```json
{
  "exportedAt": "2026-07-02T22:00:00.000Z",
  "app": "quizbot",
  "version": 1,
  "quizzes": [ { "id": ..., "question": ..., "answer": ..., "status": ..., ... } ],
  "monetize": { "followers": 350, "impressions": 1200000, "premium": true, "updatedAt": ... },
  "settings": { ... }
}
```

- セキュリティのため **Webhook設定（シークレット含む）はエクスポートに含まれません**
- インポート時は `quizzes` を ID で重複排除してマージ、`monetize` は新しい方を採用します

---

## ⚠️ Xの自動化ルールについて

このアプリが「承認制（人間が最終判断して手動投稿）」なのは意図的な設計です。
PC側と連携する場合も以下を守ってください:

- PC側でX APIを使った自動投稿を行う場合は、Xの[自動化ルール](https://help.x.com/ja/rules-and-policies/x-automation)に従い、公式APIを使用すること
- 同一内容の重複投稿・スパム的な高頻度投稿は収益化審査の否認・アカウント凍結リスクがあります
- 収益化の観点では「スマホで承認 → 手動投稿」のままの方が安全です。PC連携は**保存・分析・通知・返信スケジュール管理**に使うのがおすすめです
