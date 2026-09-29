@echo off
chcp 65001 >nul
cd /d %~dp0
if "%1"=="preview" (
  py make_video.py --preview
) else if "%1"=="dry" (
  py make_video.py --dry-run
) else (
  py make_video.py
)
pause
