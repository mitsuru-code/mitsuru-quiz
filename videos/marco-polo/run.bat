@echo off
chcp 65001 >nul
cd /d %~dp0
set PY=py
where py >nul 2>nul || set PY=python
where %PY% >nul 2>nul || (
  echo [ERROR] Python not found. Install from python.org and check "Add python.exe to PATH".
  pause
  exit /b 1
)
%PY% -m pip install -q -r requirements.txt
if "%1"=="preview" (
  %PY% make_video.py --preview
) else if "%1"=="check" (
  %PY% make_video.py --check
) else (
  %PY% make_video.py
)
pause
