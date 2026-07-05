# ☁️ クラウドBot — 時事クイズのX自動投稿（GitHub Actions）

PC常駐だった自動投稿サーバー（server.js）を GitHub Actions に移設したものです。
**PCの電源を切っても、クラウド上で自動投稿が続きます。**

## 仕組み

```
GitHub Actions（毎時0分に起動）
   │
   ├─ 返信期限が来た正解があれば → 元ポストへスレッド返信
   │
   └─ JSTの投稿スロット（既定: 7時・12時・17時・21時）なら
        Claude API（Web検索付き）でクイズ生成 → X API で投稿
        → 正解文を返信キュー（state.json）に登録（既定: 2時間後に返信）
```

- 出題履歴（直近のトピック・書き出し）を `state.json` に記録し、重複した出題を避けます
- Pixelのクイズボットアプリ（PWA）はこれまで通り、監視・手動投稿・収益化トラッカーとして併用できます

## 初期設定（1回だけ・スマホのブラウザでも可能）

### 1. Secrets の登録

GitHubリポジトリの **Settings → Secrets and variables → Actions → New repository secret** で、以下の5つを登録します:

| Name | 値の取得場所 |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com → API Keys（`sk-ant-` で始まる） |
| `X_API_KEY` | developer.x.com → プロジェクトのアプリ → Keys and tokens → API Key（Consumer Key） |
| `X_API_SECRET` | 同上 → API Key Secret（Consumer Secret） |
| `X_ACCESS_TOKEN` | 同上 → Access Token（**Read and Write権限**で発行したもの） |
| `X_ACCESS_TOKEN_SECRET` | 同上 → Access Token Secret |

> 💡 PC側の `.env` に設定していたものと同じ値を使えます。ワークフロー内部では `TWITTER_*` という名前に読み替えていますが、GitHubへの登録名は上記の `X_*` で統一しています。

### 2. テスト実行

1. リポジトリの **Actions** タブ → 左の「Cloud Bot」→ **Run workflow**
2. `dry_run` に✔が入ったまま実行 → ログに生成されたクイズが表示される（投稿はされない）
3. 内容に問題なければ、`dry_run` の✔を外して再度実行 → 実際にXへ1回投稿される
4. Xのプロフィールで投稿を確認。約2時間後の定時実行で正解がスレッド返信される

### 3. PC側の停止

テストが確認できたら、PC側の server.js（と自動投稿に使っていたブラウザ）を停止してください。
以後、定時投稿はすべてクラウド側で行われます。

## 設定の変更

`.github/workflows/cloud-bot.yml` の `env:` セクションのコメントを外して編集します:

| 環境変数 | 既定値 | 意味 |
|---|---|---|
| `POST_SLOTS` | `7,12,17,21` | 投稿する時刻（JST・カンマ区切り） |
| `GENRE` | `mixed` | 出題ジャンル（mixed / world / japan / economy / science / sports） |
| `ANSWER_DELAY_HOURS` | `2` | 投稿から正解返信までの時間 |

## 停止方法

- **一時停止**: Actions タブ → Cloud Bot → 右上「…」→ **Disable workflow**
- **再開**: 同じ場所から **Enable workflow**

## 注意事項

- 定時実行（cron）は **mainブランチにあるworkflowだけ**が動きます。ブランチで編集した場合はmainへマージしてください
- GitHub Actions の cron は数分〜十数分遅れることがあります（Xの投稿時刻が多少ずれても実用上は問題ありません）
- このリポジトリはpublicのため、Botのプロンプトと出題履歴（state.json）は公開されます。**秘密情報はSecretsにのみ保存**されるため漏洩はしません
- X APIの利用枠（無料プランは投稿数上限あり）と、Anthropic APIの残高に注意してください
- Xの[自動化ルール](https://help.x.com/ja/rules-and-policies/x-automation)に従い、アカウントの自動化ラベル設定を推奨します
