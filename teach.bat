@echo off
chcp 65001 >nul
cd /d %~dp0
call .venv\Scripts\activate.bat
set TEAM=%1
if "%TEAM%"=="" set /p TEAM=Team name (english/number, e.g. team1): 
if "%TEAM%"=="" set TEAM=practice
python tools\teach.py --name %TEAM% %2 %3 %4
pause
