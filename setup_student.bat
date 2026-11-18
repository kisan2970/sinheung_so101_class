@echo off
REM 학생 연습용 가벼운 설치 (로봇 없이 --sim 연습 + 웹캠 손 인식). 약 300MB.
REM 실제 로봇을 연결하는 PC 는 setup_windows.bat 을 쓰세요.
setlocal
chcp 65001 >nul
cd /d %~dp0

where py >nul 2>nul
if errorlevel 1 (
  echo [!] Python 이 없습니다. 먼저 설치하세요:  winget install -e --id Python.Python.3.10
  pause
  exit /b 1
)
py -3.10 -c "import sys" >nul 2>nul
if errorlevel 1 (
  echo [!] Python 3.10 이 없습니다:  winget install -e --id Python.Python.3.10
  pause
  exit /b 1
)
if not exist .venv (
  py -3.10 -m venv .venv || goto :fail
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt || goto :fail
python -m pip uninstall -y opencv-python-headless opencv-python
python -m pip install --force-reinstall --no-deps opencv-contrib-python==4.11.0.86 || goto :fail

echo.
echo ==== 설치 완료. 환경 점검 ====
python tools\check_env.py --lite
pause
exit /b 0

:fail
echo.
echo [!] 설치 중 오류가 났습니다. 위의 빨간 글씨를 선생님께 보여주세요.
pause
exit /b 1
