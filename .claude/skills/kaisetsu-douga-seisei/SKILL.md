---
name: kaisetsu-douga-seisei
description: 【解説動画生成】 歴史・地理・地学のテーマ（帝国の興亡、国境や大陸の変化、漫画や小説の時代背景など）を、地図入りの図解PNGと、その図解をカメラワーク＋ナレーションで見せる約1分の解説動画にし、Xに手動投稿できる形（1080p/720p mp4・素材メモ・投稿導入文の材料）まで仕上げ、Google ドライブに納品する。「解説動画を作って」「〇〇を図解にして」「〇〇の拡大と衰退」「〇〇の時代背景」「地図で説明して」「1分動画にして」「ナレーションを付けて」「投稿できるように」という場面で、動画と明言されていなくても積極的に起動すること。mitsuru-quiz リポジトリの infographics/ 配下の既存スクリプトを土台にする。
---

# 解説動画生成

`infographics/mongol-empire/` と `infographics/jadugal-era/` で確立した手順をまとめたもの。
新しいテーマは、この2つを土台にして**差分だけ書く**。一から作り直さない（既に踏んだ不具合を再発させないため）。

## 運用の前提（最優先）

このアカウントは X の Original Content Rewards を狙っており、「created **or** posted using automated means」は対象外になる（`cloud-bot/README.md`）。豆知識と同じ分担にする。

| 段階 | 担当 |
|---|---|
| 事実の収集・図解・動画のレンダリング | 機械（このスキル） |
| **ナレーション本文・投稿文** | **人**（`素材メモ.md` を見て自分の言葉で書く） |
| **投稿** | **人**（X公式アプリから手動） |

- 素材メモは**事実の列挙（体言止め＋確度◎○△）**にし、そのまま読める完成文にしない。コピペ防止のため。
- ユーザーに頼まれて仮ナレーションや投稿文案を書く場合は、「AI作成の仮版。そのまま使うと収益対象外のおそれ」と毎回明記する。
- 作品（漫画・映画など）が題材の時は、**作品の画像・キャラクターは使わない**（著作権）。作品名・作者名の文字表記だけにし、**ネタバレになる時期以降は省く**。

## 手順

### 1. 図解を作る（`infographics/<slug>/make_infographic.py`）
- 構成の型: タイトル＋一行要約／左に地図（勢力範囲・遠征矢印・都市・✕印）／右に人物や要因のパネル／下に年表／脚注に出典と「模式図」表記。2000×1400。
- 地図部品（`load_land` `smooth` `fill` `halo`、配色定数）は `mongol-empire/make_infographic.py` から**別名で読み込んで**再利用する（→ gotchas 1）。見本は `jadugal-era/make_infographic.py`。
- 勢力範囲は手描き多角形を `smooth()` で丸め、Natural Earth の陸地で切り抜く。境界は不正確なので脚注に「おおよその範囲（模式図）」と必ず書く。
- `build()` が `(fig, 地図のax)` を返す形にする（動画側がカメラ座標に使う）。
- 色を増やす時は dataviz スキルの参照パレットから選び、`validate_palette.js --pairs all` で検証する（地図は全ペアが隣接しうる）。
- 描いたら必ず PNG を Read で見て、**文字の重なり**を直してから次へ進む（毎回どこかで重なる）。

### 2. 素材メモを作る（`素材メモ.md`）
- 場面ごと（動画の8場面に対応）に年号・出来事・数字を箇条書き。確度（◎定説 ○通説 △推定・諸説）を付ける。
- 「投稿文に使える数字・接点」「書くときの注意」（推定値には「約」、諸説ある点、呼称の揺れ）を末尾に。
- 見本: `mongol-empire/素材メモ.md`。

### 3. 動画化の設定（`infographics/<slug>/make_video.py`）
- `mongol-empire/make_video.py` を**別名で読み込み、差し替えるだけ**にする。見本は `jadugal-era/make_video.py`（`mv.info` `mv.SCENES` `mv.PREFIX` `mv.WORK_DIR` `mv.NARRATION_FILE` `mv.OUT_DIR` を上書き）。
- `SCENES` は8場面前後。各場面は `[(区間内の割合, 注目点, 横幅px), ...]`、注目点は `("map", 経度, 緯度)` か `("fig", x, y)`（図全体を0〜1で）。最初と最後は全体表示（幅2000）。
- `python make_video.py --preview` で各場面の中間フレームを `preview_N.png` に出し、**8枚をグリッドにまとめて Read で確認**する。狙った場所が映っていなければ座標か幅を直す。

### 4. ナレーションと音声
- `narration.txt`（Git管理外）に `番号: 本文` を1行1場面。1場面30〜60字、全体50〜60秒が目安。動画の長さは読み上げの長さに合わせて自動で決まる。
- 声は既定で Cloud TTS **Chirp 3: HD**（`GOOGLE_TTS_API_KEY`、`.env` 可）。キーが無い環境（このクラウド環境など）では `TTS_ENGINE=openjtalk`（Open JTalk＋HTS Voice Mei, CC BY 3.0）で仮版を作れ、末尾にクレジットが自動で入る。
- openjtalk を使う時は `pyopenjtalk.g2p(text, kana=True)` で**読みを事前確認**し、誤読はかな書きにする（→ gotchas 3）。

### 5. レンダリングと納品（生成物は Google ドライブへ）
- `TTS_ENGINE=openjtalk python make_video.py`（PCなら `run.bat`）→ `out/<prefix>_日付_時刻.mp4`。
- 確認: ffmpeg で長さ・`volumedetect`（平均 −16〜−18dB、最大 −1dB 以下）、数コマを切り出して Read。
- 720p軽量版を `scale=1280:720 -crf 23` で作り、1080p と両方を納品する（スマホからの投稿は720pを勧める）。
- **納品先は Google ドライブ**。フォルダは `解説動画/<テーマ名>/`（例: `解説動画/モンゴル帝国/`）にまとめ、1080p・720p・図解PNG・素材メモを入れる。
  - **クラウドのセッション**: Google Drive コネクタでアップロードする。コネクタのツールが無い時は `ListConnectors` で状態を確かめ、「接続済みだがこのチャットで無効」ならチャットのコネクタ設定で有効にするよう伝える。それまでは `SendUserFile`（`display: attach`）で渡し、ドライブ未格納であることを報告に書く。
  - **PC**: `.env` の `VIDEO_OUT_DIR` にドライブ for デスクトップの同期フォルダ（例: `G:\マイドライブ\解説動画\<テーマ名>`）を指定すれば、そのまま同期される。
- mp4 は Git には入れない（重いので）。スクリプト・PNG・素材メモはコミットして push、PR に追記する。

### 6. 報告
- 結論（何を作ったか・何秒・何MB）→ 仮版かどうか（声・ナレーションの出所）→ 確認したこと／していないこと（通しで見ていない等）→ 弱点、の順で短く。
- 投稿導入文を頼まれたら、140字以内で3案まで、推奨を1つ明示し、「AI作成の文は書き直すこと」を添える。

## gotchas（実際に踏んだもの）

1. **同名モジュールの衝突**: どのフォルダにも `make_infographic.py` があるため、`import make_infographic` すると別フォルダのものや作りかけの自分自身を拾う。`importlib.util.spec_from_file_location("別名", パス)` で読み込み、`sys.modules` に別名で登録する。
2. **カメラが場面の境目で跳ぶ**: 場面の終わりと次の始まりのキーフレームが同時刻になると、並べ替えで順序が崩れる。`camera_keys` は時刻を単調増加に保つ実装にしてある。キーフレームの作り方を変える時は壊さないこと。
3. **Open JTalk の誤読**: 縁→エン、氷期→コーリキ、日本→ニッポン、南宋→ミナミソー、元は→モトワ、明に→アカリニ、妃→ヒ、都→ト。かな書き（ふち・ひょうき・にほん・なんそう・げんは・みんに・きさき・みやこ）で回避する。
4. **CC BY の表示**: Mei 音声（CC BY 3.0）を使った動画は末尾にクレジットを重ねる（自動）。別の素材を足す時もライセンスと表示義務を確認する。
5. **ネットワーク**: GitHub の raw は取れるが、GitHub Releases・Hugging Face・NOAA・Google TTS（キー無し）は拒否される。Natural Earth は `raw.githubusercontent.com/nvkelso/natural-earth-vector` から取る。
6. **Windows 対応**: フォントは IPA が無いので BIZ UDゴシック／游ゴシック／メイリオを候補に入れてある。並列処理は `fork` が無いので `spawn` にフォールバックする。
7. **matplotlib の imshow** は既定で aspect を equal に戻し、軸範囲も変えるので、画像を重ねる時は `aspect="auto"` と描画後の `set_xlim/ylim` を忘れない（`videos/japan-formation` で発生）。

## 関連ファイル
- `infographics/mongol-empire/` — 図解・動画化の本体（`make_infographic.py` `make_video.py` `素材メモ.md` `PC手順.md` `run.bat`）
- `infographics/jadugal-era/` — 本体を流用した2本目の見本（差分だけの書き方）
- `videos/japan-formation/` — 地図そのものを動かすアニメーション（大陸移動など、図解ではなく地形が動く題材の時の見本）
- `cloud-bot/README.md` — 収益化の条件と「人が書いて人が投稿する」運用の根拠
