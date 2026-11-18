"""수업 1회차: 로봇에게 동작 가르치기 (티칭 & 재생)

    python tools/teach.py --name 1팀                  # leader 팔로 자세 잡기 (기본)
    python tools/teach.py --name 1팀 --input hand     # 토크 끄고 follower 를 손으로 잡아 자세 잡기
    python tools/teach.py --name 1팀 --input keys     # 키보드로 관절 하나씩 움직이기 (leader 없을 때)
    python tools/teach.py --name 1팀 --play --loop    # 저장된 프로그램 재생만 (발표용)
    python tools/teach.py --sim --input keys          # 로봇 없이 연습

프로그램은 바뀔 때마다 programs/<이름>.json 으로 자동 저장됩니다.
"""

import argparse
import time

import _bootstrap  # noqa: F401
from so101demo import JOINTS
from so101demo import controller as C
from so101demo.backends import LeaderArm, make_backend
from so101demo.config import load_config
from so101demo.keys import KeyReader
from so101demo.program import Player, Program

HELP = """
 ┌───────────────────────────── 키 안내 ─────────────────────────────┐
 │  s  지금 자세 저장          w  0.5초 기다리기 추가     u  마지막 것 지우기 │
 │  p  재생 / 멈춤             l  반복재생 켜기/끄기      + -  재생 속도      │
 │  x  두 번 누르면 전체 삭제   SPACE  비상정지           r  재개            │
 │  q  종료                                                               │
 │ [hand 모드]  t  토크 끄기/켜기 (끄기 전에 팔을 꼭 잡으세요!)                │
 │ [keys 모드]  1~6 관절 선택   a / d  선택 관절 -/+   o / c  그리퍼 열기/닫기  │
 └──────────────────────────────────────────────────────────────────┘"""

JOG_STEP = 3.0  # deg per key press (key repeat gives continuous motion)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="practice")
    ap.add_argument("--input", choices=["leader", "hand", "keys"], default="leader")
    ap.add_argument("--play", action="store_true", help="저장된 프로그램을 불러와 바로 재생")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--speed", type=float, default=0.6)
    ap.add_argument("--sim", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    if args.sim:
        cfg["robot"]["backend"] = "sim"
        if args.input == "leader":
            args.input = "keys"
    mode_in = "keys" if args.play else args.input

    try:
        prog = Program.load(args.name)
        print(f"기존 프로그램 '{args.name}' 불러옴: 자세 {prog.n_poses}개")
    except FileNotFoundError:
        prog = Program(args.name)
        if args.play:
            print(f"프로그램 '{args.name}' 이 없습니다 (programs/ 폴더 확인)")
            return

    leader = None
    if mode_in == "leader":
        leader = LeaderArm(cfg)
        leader.connect()

    ctl = C.ArmController(cfg, make_backend(cfg))
    ctl.start()
    if not ctl.wait_ready(15):
        print("로봇 연결 실패:", ctl.state.message)
        ctl.stop()
        return

    player = Player(ctl, prog, speed=args.speed, loop=args.loop)
    jog = dict(ctl.state.commanded)
    sel = 0
    catch_up = True  # leader mode: approach the leader pose slowly first
    msg = ""
    x_armed = 0.0
    print(HELP)
    if args.play:
        player.start()

    try:
        with KeyReader() as kr:
            while True:
                k = kr.get()
                st = ctl.state
                if k == " ":
                    ctl.estop()
                    player.stop("비상정지")
                    msg = "비상정지! 정지 후 홈으로 복귀합니다. r = 재개"
                elif k == "r":
                    ctl.resume()
                    jog, catch_up, msg = dict(ctl.state.commanded), True, "재개"
                elif k == "q":
                    break
                elif k == "p":
                    if player.running:
                        player.stop("멈춤")
                        catch_up = True
                    elif st.state == C.RUN:
                        if st.compliant:
                            ctl.set_compliant(False)
                            time.sleep(0.1)
                        player.start()
                elif k == "l":
                    player.loop = not player.loop
                elif k in ("+", "="):
                    player.speed = round(min(1.0, player.speed + 0.1), 1)
                elif k in ("-", "_"):
                    player.speed = round(max(0.1, player.speed - 0.1), 1)
                elif not player.running and not args.play:
                    if k == "s" and st.measured:
                        pose = st.measured if st.compliant else st.commanded
                        prog.add_pose(pose)
                        prog.save()
                        msg = f"자세 {prog.n_poses} 저장!"
                    elif k == "w":
                        prog.add_wait(0.5)
                        prog.save()
                        msg = f"기다리기 {prog.steps[-1]['wait']}초"
                    elif k == "u":
                        prog.undo()
                        prog.save()
                        msg = "마지막 단계 삭제"
                    elif k == "x":
                        if time.time() - x_armed < 1.5:
                            prog.steps.clear()
                            prog.save()
                            msg = "전체 삭제됨"
                        else:
                            x_armed = time.time()
                            msg = "한 번 더 x 를 누르면 전체 삭제"
                    elif k == "t" and mode_in == "hand":
                        ctl.set_compliant(not st.compliant)
                        msg = "토크 켜기" if st.compliant else "토크 끄기 — 팔을 잡고 움직이세요"
                    elif mode_in == "keys" and k:
                        if k in "123456":
                            sel = int(k) - 1
                        elif k in ("a", "d"):
                            j = JOINTS[sel]
                            jog[j] += JOG_STEP * (1 if k == "d" else -1)
                            jog = ctl.limiter.clamp(jog)
                        elif k == "o":
                            jog["gripper"] = cfg["gripper"]["open"]
                        elif k == "c":
                            jog["gripper"] = cfg["gripper"]["closed"]

                # --- drive the arm
                if player.running:
                    player.update()
                    if not player.running:
                        catch_up = True
                        jog = dict(ctl.state.commanded)
                elif st.state == C.RUN and not st.compliant and not args.play:
                    if mode_in == "leader":
                        try:
                            lp = leader.read()
                            ctl.set_target(lp, 0.3 if catch_up else 1.0)
                            if catch_up and all(abs(st.commanded.get(j, 1e9) - lp[j]) < 3 for j in JOINTS):
                                catch_up = False
                        except Exception as e:  # noqa: BLE001
                            msg = f"leader 읽기 실패: {e}"
                    elif mode_in == "keys":
                        ctl.set_target(jog, 1.0)

                # --- status line
                extra = f" 관절:{JOINTS[sel]}" if mode_in == "keys" and not args.play else ""
                torque = " 토크OFF" if st.compliant else ""
                line = (f"[{st.state}{torque}] 자세 {prog.n_poses}개 | 속도 {player.speed:.1f}"
                        f" | 반복 {'ON' if player.loop else 'off'} | {player.status}{extra} | {msg}")
                print(f"\r{line[:118]:<118}", end="", flush=True)
                if args.play and not player.running and player.status == "완료":
                    break
                time.sleep(0.02)
    finally:
        print()
        if prog.steps and not args.play:
            print("저장됨:", prog.save())
        if ctl.state.compliant:
            input("토크가 꺼져 있습니다. 팔을 안전한 자세로 내려놓고 Enter...")
        ctl.stop()
        if leader:
            leader.disconnect()


if __name__ == "__main__":
    main()
