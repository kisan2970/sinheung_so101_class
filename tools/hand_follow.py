"""수업 2회차: AI 눈으로 로봇 조종하기 (손동작 따라하기)

    python tools/hand_follow.py --setup     # 처음 1회: 손 위치 ↔ 팔 자세 매핑 기록 (토크 OFF, 손으로 팔 잡기)
    python tools/hand_follow.py             # 실행
    python tools/hand_follow.py --sim       # 로봇 없이 (웹캠만) 체험
    python tools/hand_follow.py --camera 1  # 다른 카메라

화면 키:  SPACE 비상정지   r 재개   p 따라하기 일시정지/재개   m 좌우반전   f 전체화면   q/ESC 종료

손 위치(좌우) → 몸통 회전, 손 높이 → 팔 들기/내리기, 손목 기울이기 → 손목 회전, 주먹 → 그리퍼 닫기.
손이 안 보이면 천천히 홈 자세로 돌아갑니다.
"""

import argparse
import platform
import time

import _bootstrap  # noqa: F401
from so101demo import JOINTS
from so101demo import controller as C
from so101demo.backends import make_backend
from so101demo.config import load_config, update_local

NEON = (255, 220, 0)      # BGR cyan
WARN = (0, 80, 255)
OK = (120, 255, 60)
WIN = "SO-101 HAND FOLLOW"


# ------------------------------------------------------------------ setup (mapping capture)
def run_setup(cfg):
    from so101demo.keys import KeyReader

    print(__doc__)
    print("""
[설정] 토크가 꺼지면 follower 팔을 손으로 잡고 아래 자세를 만든 뒤 키를 누르세요.
   l : '손이 화면 아래'일 때 팔 자세 (예: 팔을 앞으로 낮게 뻗은 자세)
   h : '손이 화면 위'일 때 팔 자세   (예: 팔을 높이 든 자세)
   a : 손이 화면 왼쪽 끝일 때 몸통 방향     d : 오른쪽 끝일 때 몸통 방향
   c : 그리퍼 닫힘                          o : 그리퍼 열림 (너무 크게 말고 적당히)
   Enter : 저장    q : 취소
""")
    ctl = C.ArmController(cfg, make_backend(cfg))
    ctl.start()
    if not ctl.wait_ready(15):
        print("연결 실패:", ctl.state.message)
        ctl.stop()
        return
    input("팔을 손으로 잡으세요. Enter 를 누르면 토크가 꺼집니다...")
    ctl.set_compliant(True)
    got = {}
    try:
        with KeyReader() as kr:
            while True:
                q = ctl.state.measured
                k = kr.get()
                if k == "l":
                    got["pose_low"] = {j: round(q[j], 2) for j in JOINTS}
                elif k == "h":
                    got["pose_high"] = {j: round(q[j], 2) for j in JOINTS}
                elif k == "a":
                    got["pan_left"] = round(q["shoulder_pan"], 2)
                elif k == "d":
                    got["pan_right"] = round(q["shoulder_pan"], 2)
                elif k == "c":
                    got["g_closed"] = round(q["gripper"], 1)
                elif k == "o":
                    got["g_open"] = round(q["gripper"], 1)
                elif k in ("\r", "\n"):
                    break
                elif k == "q":
                    got = {}
                    break
                have = " ".join(n for n in ("pose_low", "pose_high", "pan_left", "pan_right", "g_closed", "g_open")
                                if n in got)
                print("\r  " + " ".join(f"{j[:5]}:{q[j]:6.1f}" for j in JOINTS) + f"  기록됨: {have:<55}",
                      end="", flush=True)
                time.sleep(0.03)
    finally:
        print()
        input("팔을 안전한 자세에 놓고 Enter (토크가 다시 켜지고 그 자세를 유지합니다)...")
        ctl.set_compliant(False)
        time.sleep(0.2)
        ctl.stop()
    if not got:
        print("저장하지 않았습니다.")
        return
    patch = {"hand_follow": {k: v for k, v in got.items() if not k.startswith("g_")}}
    if "g_closed" in got or "g_open" in got:
        patch["gripper"] = {}
        if "g_closed" in got:
            patch["gripper"]["closed"] = got["g_closed"]
        if "g_open" in got:
            patch["gripper"]["open"] = got["g_open"]
    update_local(patch)
    print("저장 완료 (config/local.yaml):", patch)
    missing = [k for k in ("pose_low", "pose_high", "pan_left", "pan_right") if k not in got]
    if missing:
        print("아직 기록 안 된 항목:", missing, "→ 다시 --setup 하면 나머지만 추가 기록해도 됩니다")


# ------------------------------------------------------------------ camera
class Camera:
    """Webcam with automatic re-open; read() returns None instead of raising."""

    def __init__(self, index: int):
        self.index = index
        self.cap = None
        self.fail = 0
        self._next_open = 0.0

    def _open(self):
        import cv2

        api = cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_ANY
        self.cap = cv2.VideoCapture(self.index, api)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.cap.set(cv2.CAP_PROP_FPS, 30)

    def read(self):
        if self.cap is None or not self.cap.isOpened():
            if time.time() < self._next_open:
                return None
            self._open()
            self._next_open = time.time() + 1.0
        ok, frame = self.cap.read()
        if not ok or frame is None:
            self.fail += 1
            if self.fail > 15:
                self.cap.release()
                self.cap = None
                self.fail = 0
            return None
        self.fail = 0
        return frame

    def release(self):
        if self.cap is not None:
            self.cap.release()


# ------------------------------------------------------------------ HUD drawing
def draw_hud(img, st, follow, status, obs, fps, mapper_ok, sim):
    import cv2

    h, w = img.shape[:2]
    overlay = img.copy()
    cv2.rectangle(overlay, (0, 0), (w, 46), (20, 10, 0), -1)
    cv2.rectangle(overlay, (0, h - 120), (250, h), (20, 10, 0), -1)
    cv2.addWeighted(overlay, 0.55, img, 0.45, 0, img)
    color = {"TRACKING": OK, "SEARCHING": NEON, "PAUSED": NEON}.get(status, WARN)
    title = f"HAND FOLLOW  //  {status}"
    cv2.putText(img, title, (12, 31), cv2.FONT_HERSHEY_DUPLEX, 0.7, color, 1, cv2.LINE_AA)
    right = f"ARM {st.state}{' SIM' if sim else ''}  {fps:4.1f} FPS"
    (rw, _), _ = cv2.getTextSize(right, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    cv2.putText(img, right, (w - rw - 12, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.5, NEON, 1, cv2.LINE_AA)
    # joint bars
    if st.commanded:
        for i, j in enumerate(JOINTS):
            v = st.commanded[j]
            y = h - 108 + i * 18
            cv2.putText(img, j[:11], (8, y + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.38, NEON, 1, cv2.LINE_AA)
            lo, hi = (0, 100) if j == "gripper" else (-120, 120)
            t = (v - lo) / (hi - lo)
            cv2.rectangle(img, (100, y), (240, y + 10), (90, 60, 0), 1)
            cv2.rectangle(img, (100, y), (100 + int(140 * max(0, min(1, t))), y + 10), NEON, -1)
    if obs is not None:
        bar = int(obs.openness * 100)
        cv2.putText(img, f"GRIP {'OPEN' if obs.openness > 0.5 else 'CLOSE'} {bar:3d}%", (w - 200, h - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, OK if obs.openness > 0.5 else WARN, 1, cv2.LINE_AA)
    if not mapper_ok:
        cv2.putText(img, "SETUP NEEDED: hand_follow.py --setup", (12, 72), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    WARN, 2, cv2.LINE_AA)
    if st.state != C.RUN:
        msg = {"ESTOP_HOLD": "EMERGENCY STOP", "HOMING": "RETURNING HOME",
               "HOLD_HOME": "STOPPED - press R", "FAULT": "ROBOT LINK LOST - reconnecting"}.get(st.state, st.state)
        (tw, _), _ = cv2.getTextSize(msg, cv2.FONT_HERSHEY_DUPLEX, 1.1, 2)
        cv2.putText(img, msg, ((w - tw) // 2, h // 2), cv2.FONT_HERSHEY_DUPLEX, 1.1, WARN, 2, cv2.LINE_AA)


# ------------------------------------------------------------------ main loop
def run(cfg, args):
    import cv2

    from so101demo.hand import HandMapper, HandTracker

    hc = cfg["hand_follow"]
    ctl = C.ArmController(cfg, make_backend(cfg))
    ctl.start()
    if not ctl.wait_ready(15):
        print("로봇 연결 실패:", ctl.state.message, "→ 계속 재연결을 시도하며 카메라만 표시합니다")
    home = dict(ctl.home) if ctl.home else None

    mapper = None
    if home:
        mapper = HandMapper(hc, home, cfg["gripper"])
        if not mapper.configured and not args.sim:
            print("!! 매핑이 설정되지 않았습니다. 먼저: python tools/hand_follow.py --setup")
            print("   (지금은 몸통 회전 ±30°, 손목, 그리퍼만 따라합니다)")
    mirror = bool(hc.get("mirror", True))
    tracker = HandTracker(mirror=mirror)
    cam = Camera(args.camera if args.camera is not None else int(hc.get("camera_index", 0)))

    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WIN, 960, 720)
    fullscreen = False
    follow = True
    seen = 0
    last_seen = 0.0
    acquired_t = 0.0
    fps, t_prev = 0.0, time.perf_counter()
    lost_timeout = float(hc.get("lost_timeout_s", 0.7))
    need = int(hc.get("acquire_frames", 4))
    homing_scale = float(cfg["safety"]["homing_speed_scale"])
    drawing = tracker.mp.solutions.drawing_utils
    conns = tracker.mp.solutions.hands.HAND_CONNECTIONS
    spec_pt = drawing.DrawingSpec(color=OK, thickness=2, circle_radius=3)
    spec_ln = drawing.DrawingSpec(color=NEON, thickness=2)

    try:
        while True:
            frame = cam.read()
            now = time.perf_counter()
            obs = None
            if frame is None:
                import numpy as np

                frame = np.zeros((480, 640, 3), np.uint8)
                cv2.putText(frame, "CAMERA OFFLINE - reconnecting...", (60, 240), cv2.FONT_HERSHEY_SIMPLEX,
                            0.8, WARN, 2, cv2.LINE_AA)
            else:
                try:
                    obs = tracker.process(frame)
                except Exception as e:  # noqa: BLE001 - never let vision kill the loop
                    print("hand tracker error:", e)
                    obs = None
                if mirror:
                    frame = cv2.flip(frame, 1)
                if obs is not None and obs.landmarks is not None:
                    if mirror:  # landmarks are in un-mirrored image coords
                        for q in obs.landmarks.landmark:
                            q.x = 1.0 - q.x
                    drawing.draw_landmarks(frame, obs.landmarks, conns, spec_pt, spec_ln)

            # ---- decide what the arm should do
            if obs is not None:
                seen += 1
                last_seen = now
            else:
                seen = 0
            st = ctl.state
            if not follow:
                status = "PAUSED"
            elif obs is not None and seen >= need:
                status = "TRACKING"
            elif now - last_seen < lost_timeout:
                status = "TRACKING" if acquired_t else "SEARCHING"
            else:
                status = "SEARCHING"

            if mapper and st.state == C.RUN:
                if status == "TRACKING" and obs is not None:
                    if not acquired_t:
                        acquired_t = now
                        mapper.reset()  # start filters fresh at the new hand position
                    # ramp speed in over 1.5 s after (re)acquiring so the arm never lunges
                    ramp = min(1.0, 0.25 + (now - acquired_t) / 1.5)
                    ctl.set_target(mapper.map(obs, now), ramp)
                elif status == "TRACKING":
                    pass  # dropout shorter than lost_timeout: controller brakes and holds the pose
                else:
                    acquired_t = 0.0
                    ctl.set_target(home, homing_scale)  # no hand / paused: drift home slowly
            elif st.state != C.RUN:
                acquired_t = 0.0

            dt = now - t_prev
            t_prev = now
            fps = 0.9 * fps + 0.1 * (1.0 / dt if dt > 0 else 0)
            draw_hud(frame, st, follow, status, obs, fps, mapper is not None and mapper.configured, args.sim)
            cv2.imshow(WIN, frame)

            k = cv2.waitKey(1) & 0xFF
            if k == ord(" "):
                ctl.estop()
            elif k == ord("r"):
                ctl.resume()
            elif k == ord("p"):
                follow = not follow
            elif k == ord("m"):
                mirror = not mirror
                tracker.mirror = mirror
            elif k == ord("f"):
                fullscreen = not fullscreen
                cv2.setWindowProperty(WIN, cv2.WND_PROP_FULLSCREEN,
                                      cv2.WINDOW_FULLSCREEN if fullscreen else cv2.WINDOW_NORMAL)
            elif k in (ord("q"), 27):
                break
            if cv2.getWindowProperty(WIN, cv2.WND_PROP_VISIBLE) < 1:
                break
            if mapper is None and ctl.home:  # robot came online late
                home = dict(ctl.home)
                mapper = HandMapper(hc, home, cfg["gripper"])
    finally:
        print("종료: 홈으로 복귀 중...")
        if ctl.state.state == C.RUN and home:
            t0 = time.time()
            while time.time() - t0 < 6:
                ctl.set_target(home, homing_scale)
                if ctl.state.at_target:
                    break
                time.sleep(0.05)
        cam.release()
        tracker.close()
        cv2.destroyAllWindows()
        ctl.stop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--setup", action="store_true")
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("--camera", type=int, default=None)
    args = ap.parse_args()
    cfg = load_config()
    if args.sim:
        cfg["robot"]["backend"] = "sim"
    if args.setup:
        if args.sim:
            print("--setup 은 실제 팔에서만 의미가 있습니다")
            return
        run_setup(cfg)
    else:
        run(cfg, args)


if __name__ == "__main__":
    main()
