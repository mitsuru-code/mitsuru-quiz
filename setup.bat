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
echo [OK] トークンを .env ファイルに保存しました。
echo.
echo セットアップ完了！次回からは start-server.bat で起動できます。
echo.
pause
