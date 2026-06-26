@echo off
chcp 65001 > nul
echo ===================================
echo  クイズBot サーバー 起動
echo ===================================
echo.

:: .env ファイルから設定を読み込む
if not exist .env (
  echo [エラー] .env ファイルが見つかりません。
  echo 先に setup.bat を実行してください。
  pause
  exit /b 1
)

for /f "tokens=1,2 delims==" %%a in (.env) do (
  set %%a=%%b
)

:: Node.js チェック
node --version > nul 2>&1
if errorlevel 1 (
  echo [エラー] Node.js が見つかりません。
  echo https://nodejs.org から LTS版をインストールしてください。
  pause
  exit /b 1
)

:: node_modules チェック
if not exist node_modules (
  echo パッケージをインストールしています...
  npm install
)

echo.
echo サーバーを起動しています...
echo.
echo  ブラウザで開く URL: http://localhost:%PORT%
echo.
echo  外部公開するには別のウィンドウで:
echo  cloudflared tunnel --url http://localhost:%PORT%
echo.
echo  停止するには Ctrl+C を押してください。
echo ===================================
echo.

node server.js
pause
