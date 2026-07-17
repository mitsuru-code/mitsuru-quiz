# 「第二の甲斐 充」— 分身AI

## v2: 即起動PWA（メインの使い方）📱

Claude Code方式（下記）はセッション起動に時間がかかるため、**ホーム画面から即起動する単一HTMLのPWA** `mitsuru-ai.html` を追加しました。メモ帳代わりに使えます。

**インストール（1回だけ）**: スマホのChromeで `https://mitsuru-code.github.io/mitsuru-quiz/mitsuru-ai.html` を開く → メニュー（⋮）→「ホーム画面に追加」。以後はアイコンタップで即起動。

**できること**:
- 📝 **メモ** — 起動した瞬間に書ける。API不要・オフラインでも保存可。検索・編集・「🤖 AIで整理」
- 💬 **壁打ち** — 分身（甲斐 充本人の一人称）と対話。人格文書＋直近メモを覚えている
- 🎤 **取材** — AIのインタビューに答えるほど人格文書が育つ（自動で人格に反映）
- 📔 **人格** — 9セクションの閲覧・手動編集。persona-starter形式のmarkdown貼り付けインポート対応
- ⚙️ **設定** — APIキー（クイズBotのキーを自動流用）、エクスポート/インポートで端末移行

**プライバシー**: 人格・メモ・会話はすべて端末内のlocalStorageのみ。外部送信先はAnthropic APIだけで、この公開リポジトリには何も保存されません。

**開発メモ**: `mitsuru-ai.html` はService Worker（`sw.js`）にキャッシュ登録されているため、更新したら `sw.js` の `CACHE` バージョンも上げること。

---

## v1: Claude Codeで壁打ちできる分身AI（じっくり派向け）

Claude Code内で対話できる分身AIの仕組みです。実体（人格データ）は**別のprivateリポジトリ `mitsuru-persona`** に置き、
この公開リポジトリには個人データを一切置きません。ここにあるのはテンプレート一式（[persona-starter/](../persona-starter/)）と、この説明だけです。

## 仕組み

```
mitsuru-persona（privateリポジ）
├── persona/mitsuru.md      ← 人格文書。/interview で育つ
├── interviews/             ← インタビューの生ログ
└── .claude/skills/
    ├── interview/          ← /interview: Claudeが質問を重ねて人格を蒸留・蓄積
    └── kabeuchi/           ← /kabeuchi: Claudeが甲斐 充本人として一人称で壁打ち相手になる
```

- **育てる**: `/interview` — 質問に答えるほど人格文書が充実し、分身が本人らしくなる
- **壁打ち**: `/kabeuchi` — 人格文書を読み込んだClaudeが、本人の口調・価値観で率直に意見を返す。文書に無いことは捏造しない設計
- 変更は毎回コミット＆プッシュで永続化（リモートセッションのコンテナは使い捨てのため）

## 初回セットアップ（1回だけ）

1. **privateリポジトリを作る**: [github.com/new](https://github.com/new) → Repository name: `mitsuru-persona` → **Private** を選択 → Create repository（README等の初期化は不要）
2. **Claudeにアクセス権を付与**: GitHubの Settings → Applications → Claude のGitHub App設定で `mitsuru-persona` を追加
3. **スターターキットを投入**: Claude Codeのセッションで「mitsuru-persona リポジトリをこのセッションに追加して、mitsuru-quiz の persona-starter/ の中身をコミットして」と頼む
   （手動でやる場合: このリポジトリの `persona-starter/` の中身をそのまま `mitsuru-persona` のルートにコピーしてプッシュ）

## 日常の使い方

1. [claude.ai/code](https://claude.ai/code) で `mitsuru-persona` のセッションを開始
2. `/interview` で育てる、`/kabeuchi` で壁打ちする

## プライバシー

- 人格データ（価値観・経歴・エピソード）は private リポジトリ `mitsuru-persona` の中だけで完結
- この公開リポジトリおよび外部サービスへ人格データを転記しない運用（`mitsuru-persona/CLAUDE.md` に明記）
- クイズBot（index.html / cloud-bot / クイズハム🐹）とは完全に独立
