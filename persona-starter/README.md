# mitsuru-persona — 「第二の甲斐 充」🧑‍💼

甲斐 充さんの分身AI。Claude Codeでこのリポジトリのセッションを開くと、
インタビューで人格を育て、壁打ち相手として対話できます。

> ⚠️ このリポジトリは**必ずprivate**で運用してください。人格データ（価値観・経歴・エピソード）が含まれます。

## 使い方

1. [claude.ai/code](https://claude.ai/code)（またはClaude Code CLI / デスクトップアプリ）でこのリポジトリのセッションを開始
2. **育てる**: `/interview` と入力 — Claudeが質問を1つずつ聞いてきます。答えるほど `persona/mitsuru.md` に人格が蓄積されます。「ここまで」と言えばその時点で反映・保存されます
3. **壁打ちする**: `/kabeuchi` と入力 — 以後Claudeが「甲斐 充」本人として一人称で応答します。考え事の相談、アイデアの壁打ちにどうぞ

インタビューは好きなときに何度でも。育つほど分身が本人らしくなります。

## ファイル構成

| パス | 役割 |
|---|---|
| `persona/mitsuru.md` | 人格文書（9セクション）。分身の記憶・人格のすべて。手動編集も可 |
| `interviews/YYYY-MM-DD.md` | インタビューの生ログ（日付ごと） |
| `.claude/skills/interview/` | `/interview` スキル定義 |
| `.claude/skills/kabeuchi/` | `/kabeuchi` スキル定義 |
| `CLAUDE.md` | Claudeの基本動作・プライバシールール |

## データの持ち出し禁止

人格データはこのprivateリポジトリの中だけで完結させます。
公開リポジトリ（mitsuru-quiz など）や外部サービスへの転記はしない運用です。
