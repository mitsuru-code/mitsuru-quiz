# つまずきやすい点（マルコ・ポーロ動画の制作で実際に起きたこと）

PC 側の画面は Claude から見えない。ユーザーには「黒い画面の最後の数行」か `エラーログ.txt`、診断 `check.bat` の画面を送ってもらう。
その際、APIキーが写らないよう毎回ひと言添える（過去にキーの大部分が写った画像が送られてきた）。

| 症状 | 原因 | 対処 |
|---|---|---|
| 「ファイルをブロックされた」 | ダウンロードした ZIP に Windows が付ける「インターネットから来た」印 | ZIP を右クリック →「プロパティ」→「許可する」にチェック → OK → 展開し直す。青い画面なら「詳細情報」→「実行」 |
| 「許可する」の後もブロックされる | 展開済みファイル一つずつに印が残っている／スマート アプリ コントロール（推定） | フォルダのアドレス欄に `powershell` → `Get-ChildItem -Recurse \| Unblock-File`。bat を使わず `py make_video.py --check` でも動く。スマート アプリ コントロールはオフにすると戻せないので勝手に切らせない |
| `can't open file …make_video.py` / `Could not open requirements file` | cmd が `C:\Users\<名前>` など別の場所で開いている | 展開したフォルダをエクスプローラーで開き、アドレス欄に `cmd` と入力して Enter（そのフォルダで開く） |
| 画像を置いたのに「画像の無い場面」に出る | 前の版の展開フォルダの scenes に置いた | `check.bat` の「保存先」行で今のフォルダを確認し、そこの scenes にコピー |
| 直したはずの表示が出ない | ダウンロードフォルダの古い ZIP（`xxx (1).zip` など）を展開している | 更新日時が最新の ZIP を、今のフォルダの1つ上に「ファイルを置き換える」で展開。ZIP 名に版番号（`-v2` など）を付けて渡すと取り違えにくい |
| `HTTP 402 … prepayment credits are depleted` | Gemini の音声生成（TTS）は無料枠では使えない（2026年9月時点。「無料枠」のキーでも 402 になる） | 既定の Cloud TTS（Chirp 3 HD）を使う。Gemini を使うなら AI Studio でクレジット追加（最低5ドル） |
| Gemini で `HTTP 404` | TTS モデルの廃止・改名（例: gemini-2.5-flash-preview-tts は廃止、後継は gemini-3.8-flash-tts） | スクリプトは使えるモデル一覧から自動で選び直す。直らなければ `.env` の `GEMINI_TTS_MODEL=` を消す |
| `GOOGLE_TTS_API_KEY が未設定です` | `.env` が `.env.txt` になっている／キーの行が無い | エクスプローラーの「表示」→「ファイル名拡張子」で本当の名前を確認 |
| キーを替えたのに結果が変わらない | Windows の環境変数に古いキーが残っていた | スクリプトは `.env` を優先するようにしてある。`check.bat` でキー末尾4文字と読み込み元を確認 |
| Cloud TTS で `HTTP 403` | API 未有効／請求先アカウント未紐づけ／キーの制限 | Google Cloud で Text-to-Speech API を有効化し、プロジェクトに請求先を紐づけ、キーの制限に Text-to-Speech を含める |
| `Python not found` | PATH 未設定 | Python を入れ直し「Add python.exe to PATH」にチェック |
| 文字が □ | 日本語フォントが無い | Windows 標準の BIZ UDゴシック／游ゴシックを自動で探す。無ければ Windows Update で日本語フォントを追加 |
| 動画が見つからない | 出力先の勘違い | `run.bat` のあるフォルダの `out\`。`.env` の `VIDEO_OUT_DIR=` を書いていればそこ。正確な場所は黒い画面の最後の `done:` の行 |

## 渡し方の原則

- ユーザーは PC（Windows）中心で作業する。GitHub の PR 運用は使わない。成果物は ZIP をチャットで渡す。
- 完成動画（mp4）はリポジトリに入れない（数十MBあり、作り直すたびに履歴が重くなる）。
- 30MB を超えるファイルはチャットで送れない。ZIP は画像込みで 20MB 前後に収まる。
