# PCでモンゴル帝国の動画を作る手順（Windows）

運用は豆知識と同じです。

| 段階 | 担当 | 内容 |
|---|---|---|
| 素材 | 機械 | `素材メモ.md`（事実の一覧）と図解 `mongol_empire.png` |
| **ナレーション** | **👤 人** | `narration.txt` に自分の言葉で書く |
| 動画化 | PC | `run.bat` で声（Cloud TTS Chirp 3: HD）と映像を合成 |
| **投稿文・投稿** | **👤 人** | 投稿文を自分で書き、**X公式アプリから手動で投稿** |

> AIが書いた文をそのまま・少し直しただけで使うと、X の Original Content Rewards の対象外になるおそれがあります（`cloud-bot/README.md` 参照）。

---

## 初回だけ

### 1. Python を入れる
1. https://www.python.org/downloads/ から Python 3.11 以降をインストール
2. インストーラの最初の画面で **「Add python.exe to PATH」にチェック**

### 2. このフォルダを PC に置く
GitHub Desktop で `mitsuru-quiz` をクローンするか、GitHub の「Code → Download ZIP」で展開します。
以降は `infographics\mongol-empire` フォルダで作業します。

### 3. 必要なライブラリを入れる
フォルダのアドレスバーに `cmd` と入力して Enter → 開いた黒い画面で:
```
py -m pip install -r requirements.txt
```

### 4. Google Cloud の API キーを用意する
1. https://console.cloud.google.com/ でプロジェクトを作成（既存でも可）
2. 「APIとサービス」→「ライブラリ」→ **Cloud Text-to-Speech API** を有効にする
3. 「認証情報」→「認証情報を作成」→「APIキー」
4. 作ったキーの「キーを制限」で、API の制限を **Cloud Text-to-Speech API のみ** にする（漏れた時の被害を抑えるため）
5. `.env.example` をコピーして `.env` という名前にし、`GOOGLE_TTS_API_KEY=` の後ろにキーを貼る

`.env` は Git に入らない設定になっています。チャットやメールには貼らないでください。

---

## 毎回の流れ

1. **`run.bat` をダブルクリック**
   初回は `narration.txt` の雛形ができて止まります（2回目以降は不要）
2. **`素材メモ.md` を見ながら `narration.txt` を書く**
   - 1行＝1場面、`番号: 本文` の形。場面は8つ
   - 目安は1場面30〜60字、全体で50〜60秒
   - 空欄の場面は無音で約4秒映ります
3. **（任意）画面の確認**：`cmd` で `run.bat preview` → 各場面の静止画 `preview_1〜8.png` ができます
4. **`run.bat` をダブルクリック** → 数分で `out\mongol_empire_日付_時刻.mp4` ができます
   動画の長さはナレーションの長さに合わせて自動で決まります
5. **Googleドライブに入れる**（生成物の置き場はドライブに統一）
   パソコン版の「Google ドライブ」アプリを入れ、`.env` に `VIDEO_OUT_DIR=G:\マイドライブ\解説動画\モンゴル帝国` のように書くと、
   できた動画がそのままドライブに同期され、スマホのドライブアプリから投稿に使えます
6. **投稿文を自分で書いて、X公式アプリから投稿**

---

## 声を変えたい
`.env` に `TTS_VOICE=ja-JP-Chirp3-HD-Charon` のように書きます。
Chirp 3: HD の日本語の声は複数あります（Aoede・Kore など女性、Charon・Puck など男性）。一覧は Google Cloud のドキュメント「Chirp 3: HD voices」を参照してください。

## 料金の目安
1本あたりの読み上げは約500字です。Chirp 3: HD の料金は Google Cloud の料金ページで確認してください。無料枠の範囲に収まる可能性が高い量です（推定）。
同じ文面は `.cache` に保存され、2回目以降は API を呼びません。

## うまくいかない時
| 症状 | 対処 |
|---|---|
| `GOOGLE_TTS_API_KEY が未設定です` | `.env` の名前（`.env.txt` になっていないか）と中身を確認 |
| `HTTP Error 403` | Text-to-Speech API が有効か、キーの制限が正しいか確認 |
| `HTTP Error 400` で声の名前のエラー | `TTS_VOICE` の綴りを確認 |
| 文字が □ になる | Windows 10/11 標準の「BIZ UDゴシック」「游ゴシック」を使います。入っていなければ Windows Update で日本語フォントを追加 |
| 図解の中身を変えたい | `make_infographic.py` を編集 → `py make_infographic.py` で PNG を作り直す（動画も自動で新しい図を使います） |
