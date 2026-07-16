# 📁 共有フォルダAI検索

共有フォルダ内の **Excel（.xlsx）・Word（.docx）・PDF・テキスト（.txt/.md/.csv）** を読み取り、
「〇〇はどのファイルに書いてある？」という質問に Claude AI が日本語で答えるWebアプリです。

## 仕組み

1. 起動時（と「再スキャン」ボタン）で共有フォルダを再帰的にスキャンし、各ファイルの文字を抽出してメモリに保持（ファイルの更新日時で差分更新）
2. 質問すると、キーワード（日本語は2文字単位）で関連ファイルを絞り込み
3. 上位ファイルの該当箇所の抜粋だけを Claude API に渡し、「どのファイルに何が書いてあるか」を出典付きで回答

外部に送信されるのは api.anthropic.com への「質問と関連ファイルの抜粋」のみです。

## セットアップ（Windows）

1. [Python](https://www.python.org/downloads/) をインストール（「Add python.exe to PATH」にチェック）
2. `start-search.bat` をダブルクリック
3. 初回はメモ帳で `.env` が開くので、2か所を書き換えて保存:
   - `SEARCH_FOLDER=\\サーバー名\共有名\フォルダ` （検索したい共有フォルダ）
   - `ANTHROPIC_API_KEY=sk-ant-api03-...` （console.anthropic.com で取得）
4. ブラウザで <http://localhost:5000> を開く

APIキーが未設定でも、キーワード検索（該当ファイルと該当箇所の一覧）までは動きます。

## 手動起動（Mac/Linux）

```bash
cd folder-search
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 編集して SEARCH_FOLDER と ANTHROPIC_API_KEY を設定
python app.py
```

## 注意

- `.env` は APIキーを含むため、共有フォルダや Git に置かないでください
- 対応形式: `.xlsx` `.xlsm` `.docx` `.pdf` `.txt` `.md` `.csv`（画像だけのスキャンPDFは文字を取れません）
- ファイルを追加・更新したら画面の「🔄 再スキャン」を押してください
