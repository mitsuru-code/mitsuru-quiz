@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   共有フォルダAI検索 を起動します
echo ============================================

where python >nul 2>nul
if errorlevel 1 (
    echo [エラー] Python が見つかりません。https://www.python.org/ からインストールしてください。
    pause
    exit /b 1
)

if not exist venv (
    echo 初回セットアップ: 仮想環境を作成しています…
    python -m venv venv
)

call venv\Scripts\activate.bat
pip install -q -r requirements.txt

if not exist .env (
    copy .env.example .env >nul
    echo.
    echo [初回設定] .env を作成しました。メモ帳が開くので
    echo   SEARCH_FOLDER と ANTHROPIC_API_KEY を書き換えて保存してください。
    notepad .env
)

echo.
echo ブラウザで http://localhost:5000 を開いてください（Ctrl+C で終了）
python app.py
pause
