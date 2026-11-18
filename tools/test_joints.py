"""1단계-4: 관절 읽기/쓰기 + 안전장치 테스트.

    python tools/test_joints.py            # 실제 팔
    python tools/test_joints.py --sim      # 로봇 없이 로직만 확인
    python tools/test_joints.py --amp 15

A) 읽기: 3초간 관절값 출력 (팔을 살짝 건드려 값이 변하는지 확인)
B) 쓰기: 관절을 하나씩 현재 자세 기준 ±amp 도 왕복 (속도/가속 제한 적용)
C) 비상정지: 움직이는 중 스페이스 → 정지 유지 → 천천히 홈 복귀 확인, r = 재개

키: space = 비상정지, r = 재개, n = 다음 관절로 건너뛰기, q = 종료
"""

import argparse
import math
import time

import _bootstrap  # noqa: F401
from so101demo import JOINTS
from so101demo import controller as C
from so101demo.backends import make_backend
from so101demo.config import load_config
from so101demo.keys import KeyReader


def status(ctl, extra=""):
    st = ctl.state
    m = st.measured
    if not m:
        return f"[{st.state}] {st.message}"
    s = " ".join(f"{j[:5]}:{m[j]:6.1f}" for j in JOINTS)
    return f"[{st.state:<10}] {st.loop_hz:4.0f}Hz {s} {extra}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("--amp", type=float, default=10.0, help="관절 왕복 진폭 (deg)")
    ap.add_argument("--period", type=float, default=3.0, help="왕복 주기 (s)")
    args = ap.parse_args()

    cfg = load_config()
    if args.sim:
        cfg["robot"]["backend"] = "sim"
    ctl = C.ArmController(cfg, make_backend(cfg))
    ctl.start()
    if not ctl.wait_ready(15):
        print("연결 실패:", ctl.state.message)
        ctl.stop()
        return
    lim = ctl.limiter.limits
    print("\n적용된 관절 한계 / 속도 / 가속:")
    for j in JOINTS:
        L = lim[j]
        print(f"  {j:<14} [{L.lo:7.1f}, {L.hi:7.1f}]  vmax {L.vmax:5.0f}/s  amax {L.amax:5.0f}/s²")

    # ---- A) read
    print("\nA) 읽기 테스트 (3초) — 팔을 손으로 살짝 밀어보세요 (토크는 켜져 있음)")
    t0 = time.time()
    while time.time() - t0 < 3:
        print("  " + status(ctl), end="\r", flush=True)
        time.sleep(0.05)
    print()

    input("\nB) 쓰기 테스트: 각 관절을 ±%.0f° 천천히 왕복합니다. 주변을 비우고 Enter..." % args.amp)
    start = dict(ctl.state.commanded)
    report = {}
    quit_ = False
    with KeyReader() as kr:
        for j in JOINTS:
            amp = 30.0 if j == "gripper" else args.amp
            center = min(lim[j].hi - amp, max(lim[j].lo + amp, start[j]))
            errs = []
            t0 = time.time()
            print(f"\n  -> {j}  (center {center:.1f}, ±{amp:.0f})")
            while time.time() - t0 < args.period * 2:
                k = kr.get()
                if k == " ":
                    ctl.estop()
                    print("\n  !! 비상정지 — 정지 유지 후 홈 복귀. r=재개, q=종료")
                elif k == "r":
                    ctl.resume()
                    t0 = time.time()
                elif k == "n":
                    break
                elif k == "q":
                    quit_ = True
                    break
                st = ctl.state
                if st.state == C.RUN:
                    ph = (time.time() - t0) / args.period * 2 * math.pi
                    ctl.set_target({j: center + amp * math.sin(ph)})
                    if st.measured:
                        errs.append(abs(st.commanded[j] - st.measured[j]))
                print("  " + status(ctl), end="\r", flush=True)
                time.sleep(0.02)
            # back to the start value of this joint
            ctl.set_target({j: start[j]})
            t1 = time.time()
            while time.time() - t1 < 1.5 and ctl.state.state == C.RUN:
                ctl.set_target({j: start[j]})
                time.sleep(0.02)
            if errs:
                errs.sort()
                report[j] = (errs[len(errs) // 2], errs[-1])
            if quit_:
                break

        print("\n\nC) 비상정지 테스트: shoulder_pan 이 움직이는 동안 스페이스를 누르세요 (10초, 건너뛰려면 q)")
        if ctl.state.state != C.RUN:
            ctl.resume()
        t0 = time.time()
        pressed = False
        while time.time() - t0 < 10 and not quit_:
            k = kr.get()
            if k == "q":
                break
            if k == " " and not pressed:
                ctl.estop()
                pressed = True
                print("\n  E-STOP 입력됨")
            if k == "r":
                ctl.resume()
            st = ctl.state
            if st.state == C.RUN and not pressed:
                ph = (time.time() - t0) / 4 * 2 * math.pi
                c0 = start["shoulder_pan"]
                ctl.set_target({"shoulder_pan": min(lim["shoulder_pan"].hi, max(lim["shoulder_pan"].lo,
                                                                              c0 + 15 * math.sin(ph)))})
            print("  " + status(ctl), end="\r", flush=True)
            if pressed and st.state == C.HOLD_HOME:
                print("\n  홈 도착 — 비상정지 시퀀스 정상")
                break
            time.sleep(0.02)

    print("\n\n추종 오차 (명령 - 실제, deg)  중앙값 / 최대")
    bad = False
    for j, (med, mx) in report.items():
        flag = "OK" if med < (8.0 if j == "gripper" else 3.0) else "CHECK"
        bad |= flag != "OK"
        print(f"  {j:<14} {med:5.2f} / {mx:5.2f}   {flag}")
    print("=> 정상" if report and not bad else "=> CHECK 항목: 배선/전원(12V 5A 이상)/캘리브레이션 확인")
    ctl.stop()


if __name__ == "__main__":
    main()
