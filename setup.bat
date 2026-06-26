@echo off
chcp 65001 > nul
echo ===================================
echo  クイズBot サーバー セットアップ
echo ===================================
echo.

:: Node.js チェック
node --version > nul 2>&1
if errorlevel 1 (
  echo [エラー] Node.js が見つかりません。
  echo https://nodejs.org から LTS版をインストールしてください。
  pause
  exit /b 1
)
echo [OK] Node.js が見つかりました。

:: npm install
echo.
echo パッケージをインストールしています...
npm install
if errorlevel 1 (
  echo [エラー] npm install に失敗しました。
  pause
  exit /b 1
)
echo [OK] インストール完了。

:: トークン生成
echo.
echo 認証トークンを生成しています...
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"  > token.txt
set /p TOKEN=<token.txt
del token.txt

echo.
echo ===================================
echo  生成されたトークン:
echo  %TOKEN%
echo ===================================
echo.
echo このトークンをメモしておいてください。
echo スマホから接続するときに必要です。
echo.

:: トークンを .env ファイルに保存
echo AUTH_TOKEN=%TOKEN%> .env
echo PORT=3000>> .env
echo.
echo ===================================
echo  X自動投稿を使う場合（任意）
echo ===================================
echo Twitter Developer Portal でアプリを作成し
echo Consumer Key / Secret / Access Token / Secret を取得してください。
echo 取得後、.env ファイルに以下を追記します:
echo.
echo   TWITTER_CONSUMER_KEY=xxx
echo   TWITTER_CONSUMER_SECRET=xxx
echo   TWITTER_ACCESS_TOKEN=xxx
echo   TWITTER_ACCESS_TOKEN_SECRET=xxx
echo.
echo ===================================
echo  メール通知を使う場合（任意）
echo ===================================
echo Gmail のアプリパスワードを取得し、.env ファイルに追記します:
echo.
echo   NOTIFY_EMAIL_TO=受信先メールアドレス
echo   SMTP_HOST=smtp.gmail.com
echo   SMTP_PORT=587
echo   SMTP_USER=Gmailアドレス
echo   SMTP_PASS=Gmailアプリパスワード
echo.
echo [OK] .env ファイルを保存しました。
echo.
echo セットアップ完了！次回からは start-server.bat で起動できます。
echo.
pause
