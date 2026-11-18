"""1단계-0: PC 환경 점검. 결과를 화면에 출력하고 logs/env_report.json 으로 저장.

    python tools/check_env.py
"""

import importlib
import json
import platform
import shutil
import subprocess
import sys

import _bootstrap  # noqa: F401

LITE = "--lite" in sys.argv  # student PC: simulation + webcam only, no robot / torch
from so101demo.config import LOG_DIR

# Feetech / Waveshare 서보 보드에 흔한 USB-시리얼 칩
SERIAL_CHIPS = {
    (0x1A86, 0x55D3): "CH343 (Waveshare/Feetech 보드)",
    (0x1A86, 0x7523): "CH340",
    (0x1A86, 0x55D4): "CH9102",
    (0x0403, 0x6001): "FTDI FT232",
    (0x10C4, 0xEA60): "CP210x",
}

report = {}
ok = True


def line(name, status, detail=""):
    global ok
    mark = {"OK": "[ OK ]", "WARN": "[WARN]", "FAIL": "[FAIL]"}[status]
    if status == "FAIL":
        ok = False
    print(f"{mark} {name:<22} {detail}")
    report[name] = {"status": status, "detail": detail}


print("=" * 70)
print(" SO-101 DEMO — 환경 점검")
print("=" * 70)

line("OS", "OK", f"{platform.system()} {platform.release()} ({platform.version()})")
py = sys.version_info
line("Python", "OK" if (3, 10) <= py[:2] <= (3, 12) else "FAIL",
     f"{platform.python_version()} @ {sys.executable}  (3.10~3.12 필요: lerobot>=3.10, mediapipe<=3.12)")

# GPU
smi = shutil.which("nvidia-smi")
if smi:
    try:
        out = subprocess.run([smi, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        line("NVIDIA GPU", "OK", out)
    except Exception as e:  # noqa: BLE001
        line("NVIDIA GPU", "WARN", f"nvidia-smi 실행 실패: {e}")
else:
    line("NVIDIA GPU", "WARN", "nvidia-smi 없음 (드라이버 확인)")

for mod, need, hint in [
    ("torch", not LITE, ""),
    ("lerobot", not LITE, "0.3.3 권장 (GR00T N1.5 / v2 데이터셋 호환)"),
    ("scservo_sdk", not LITE, "pip install feetech-servo-sdk  (lerobot[feetech])"),
    ("serial", True, "pyserial"),
    ("yaml", True, "pyyaml"),
    ("cv2", True, "opencv"),
    ("mediapipe", True, "pip install mediapipe==0.10.21"),
    ("websockets", False, "4단계에서 설치"),
]:
    try:
        m = importlib.import_module(mod)
        ver = getattr(m, "__version__", "")
        detail = ver
        if mod == "torch":
            cuda = m.cuda.is_available()
            detail += f"  CUDA={'yes ' + m.cuda.get_device_name(0) if cuda else 'NO'}"
            line(mod, "OK" if cuda else "WARN", detail + ("" if cuda else "  (CPU 빌드? 데모 1~4단계는 무관)"))
            continue
        if mod == "lerobot":
            from importlib.metadata import version
            detail = version("lerobot")
            line(mod, "OK" if detail.startswith("0.3.") else "WARN", f"{detail}  {hint}")
            continue
        line(mod, "OK", detail)
    except Exception as e:  # noqa: BLE001
        line(mod, "FAIL" if need else "WARN", f"없음 — {hint or e}")

# Serial ports
try:
    from serial.tools import list_ports

    ports = list(list_ports.comports())
    cands = []
    for p in ports:
        chip = SERIAL_CHIPS.get((p.vid, p.pid)) if p.vid else None
        tag = f"  <== 서보 보드 후보: {chip}" if chip else ""
        print(f"        {p.device:<10} {p.description}  VID:PID={p.vid and hex(p.vid)}:{p.pid and hex(p.pid)} SN={p.serial_number}{tag}")
        if chip:
            cands.append({"port": p.device, "chip": chip, "serial": p.serial_number})
    report["serial_candidates"] = cands
    if len(cands) == 0:
        line("Servo boards", "WARN" if LITE else "FAIL",
             "서보 보드로 보이는 포트 없음" + (" (연습용 PC 는 정상)" if LITE else " (USB/전원/CH343 드라이버 확인)"))
    elif len(cands) == 1:
        line("Servo boards", "WARN", f"1개 발견 {cands[0]['port']} (leader 미연결?)")
    else:
        line("Servo boards", "OK", f"{len(cands)}개 발견: {', '.join(c['port'] for c in cands)} → find_port.py 로 구분")
except Exception as e:  # noqa: BLE001
    line("Servo boards", "FAIL", str(e))

# Cameras
try:
    import cv2

    backend = cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_ANY
    cams = []
    for i in range(5):
        cap = cv2.VideoCapture(i, backend)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret and frame is not None:
                h, w = frame.shape[:2]
                cams.append({"index": i, "w": w, "h": h})
                cv2.imwrite(str(LOG_DIR / f"camera_{i}.jpg"), frame)
        cap.release()
    report["cameras"] = cams
    if cams:
        line("Cameras", "OK", ", ".join(f"#{c['index']} {c['w']}x{c['h']}" for c in cams)
             + f"  (스냅샷: logs/camera_*.jpg)")
    else:
        line("Cameras", "FAIL", "열리는 카메라 없음 (다른 앱이 사용 중인지 확인)")
except Exception as e:  # noqa: BLE001
    line("Cameras", "FAIL", str(e))

# Power plan hint (Windows laptop)
if platform.system() == "Windows":
    try:
        out = subprocess.run(["powercfg", "/getactivescheme"], capture_output=True, text=True, timeout=5).stdout
        line("Power plan", "OK", out.strip())
    except Exception:  # noqa: BLE001
        pass

LOG_DIR.mkdir(exist_ok=True)
with open(LOG_DIR / "env_report.json", "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print("-" * 70)
print("결과 저장: logs/env_report.json  →", "모두 통과" if ok else "FAIL 항목을 해결하세요")
sys.exit(0 if ok else 1)
