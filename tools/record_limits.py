"""1단계-3: 현장 작업공간 한계 + 홈 자세 기록 → config/local.yaml

follower 토크를 끄고 '손으로' 팔을 안전하다고 생각하는 범위 안에서만 움직입니다.
(테이블, 모니터, 관객 쪽 등 닿으면 안 되는 곳 바로 앞까지)
기록된 min/max 에서 안쪽으로 margin_deg 만큼 더 깎아 safety.joint_limits 로 저장합니다.

    python tools/record_limits.py [--margin 3]

키:  h = 지금 자세를 홈으로 기록   Enter = 저장 후 종료   q = 저장 안 하고 종료
!! 토크가 꺼지므로 시작 전에 팔을 손으로 받치고 있으세요 !!
"""

import argparse
import time

import _bootstrap  # noqa: F401
from so101demo import JOINTS
from so101demo.backends import RealBackend
from so101demo.config import load_config, update_local
from so101demo.keys import KeyReader


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--margin", type=float, default=3.0)
    args = ap.parse_args()

    cfg = load_config()
    be = RealBackend(cfg)
    be.connect()
    input("팔을 손으로 받치세요. Enter 를 누르면 토크가 꺼집니다...")
    be.robot.bus.disable_torque()
    q = be.read()
    lo, hi = dict(q), dict(q)
    home = None
    print("팔을 안전 범위 안에서 크게 움직이세요. (h=홈 기록, Enter=저장, q=취소)\n")
    save = False
    try:
        with KeyReader() as kr:
            while True:
                q = be.read()
                for j in JOINTS:
                    lo[j], hi[j] = min(lo[j], q[j]), max(hi[j], q[j])
                print("  " + " | ".join(f"{j[:8]} {q[j]:7.1f} [{lo[j]:6.1f},{hi[j]:6.1f}]" for j in JOINTS),
                      end="\r", flush=True)
                k = kr.get()
                if k == "h":
                    home = {j: round(q[j], 2) for j in JOINTS}
                    print("\n  홈 기록:", home)
                elif k in ("\r", "\n"):
                    save = True
                    break
                elif k == "q":
                    break
                time.sleep(0.03)
    finally:
        print()
        input("팔을 안전한 자세(받침대/접힌 자세)에 내려놓고 Enter...")
        be.disconnect()

    if not save:
        print("저장하지 않았습니다.")
        return
    limits = {}
    for j in JOINTS:
        m = 0.0 if j == "gripper" else args.margin
        a, b = lo[j] + m, hi[j] - m
        if b - a < 5:
            print(f"  !! {j} 범위가 너무 좁습니다 ({a:.1f}~{b:.1f}). 이 관절은 캘리브레이션 범위만 사용합니다.")
            continue
        limits[j] = [round(a, 2), round(b, 2)]
    patch = {"safety": {"joint_limits": limits}}
    if home:
        patch["home"] = home
    update_local(patch)
    print("저장 완료 (config/local.yaml):")
    for j, v in limits.items():
        print(f"  {j:<14} {v}")
    if home:
        print("  home:", home)
    else:
        print("  홈은 기록하지 않음 (데모 시작 시 자세가 홈이 됩니다)")


if __name__ == "__main__":
    main()
