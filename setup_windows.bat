@echo off
REM SO-101 demo - Windows 11 setup (1회). demo 폴더에서 실행.
REM Python 3.10 venv + torch 2.7.1(cu126) + lerobot 0.3.3[feetech]
setlocal
chcp 65001 >nul
cd /d %~dp0

where py >nul 2>nul
if errorlevel 1 (
  echo [!] Python launcher 'py' 가 없습니다. 먼저 설치:  winget install -e --id Python.Python.3.10
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
python -m pip install torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cu126 || goto :fail
python -m pip install "lerobot[feetech]==0.3.3" || goto :fail
python -m pip install -r requirements.txt || goto :fail
REM lerobot 은 opencv-python-headless(창 표시 불가), mediapipe 는 opencv-contrib-python 을 설치해
REM 둘이 같은 cv2 폴더를 덮어씀 → 둘 다 지우고 창 표시가 되는 contrib 하나만 다시 설치
python -m pip uninstall -y opencv-python-headless opencv-contrib-python opencv-python
python -m pip install --force-reinstall --no-deps opencv-contrib-python==4.11.0.86 || goto :fail

echo.
echo ==== 설치 완료. 환경 점검 실행 ====
python tools\check_env.py
pause
exit /b 0

:fail
echo.
echo [!] 설치 중 오류가 났습니다. 위의 오류 메시지를 확인하세요.
pause
exit /b 1
