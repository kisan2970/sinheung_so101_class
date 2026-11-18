import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from so101demo import JOINTS  # noqa: E402
from so101demo import controller as C  # noqa: E402
from so101demo import program as P  # noqa: E402
from so101demo.backends import SimBackend  # noqa: E402
from so101demo.config import load_config  # noqa: E402


def make_ctl():
    c = load_config()
    c["robot"]["backend"] = "sim"
    c["home"] = None
    ctl = C.ArmController(c, SimBackend(c))
    ctl.start()
    assert ctl.wait_ready(3)
    return ctl


def pose(**kw):
    p = {j: 0.0 for j in JOINTS}
    p["gripper"] = 30.0
    p.update(kw)
    return p


def run_player(pl, timeout):
    t0 = time.time()
    visited = []
    while pl.running and time.time() - t0 < timeout:
        pl.update()
        visited.append(dict(pl.ctl.state.commanded))
        time.sleep(0.02)
    return visited, time.time() - t0


def test_save_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "PROGRAM_DIR", tmp_path)
    prog = P.Program("1팀")
    prog.add_pose(pose(shoulder_pan=10))
    prog.add_wait(0.5)
    prog.add_wait(0.5)  # merges
    prog.add_pose(pose(shoulder_pan=-10))
    path = prog.save()
    assert path.name == "1팀.json"
    back = P.Program.load("1팀")
    assert back.steps[1] == {"wait": 1.0}
    assert back.n_poses == 2


def test_player_visits_every_pose_in_order_with_waits():
    ctl = make_ctl()
    try:
        prog = P.Program("t", [])
        prog.add_pose(pose(shoulder_pan=20, gripper=60))
        prog.add_wait(0.4)
        prog.add_pose(pose(shoulder_pan=-15, elbow_flex=10, gripper=2))
        pl = P.Player(ctl, prog, speed=1.0)
        pl.start()
        visited, dt = run_player(pl, 15)
        assert pl.status == "완료"
        pans = [v["shoulder_pan"] for v in visited]
        assert max(pans) > 19.5 and min(pans) < -14.5
        assert pans.index(max(pans)) < pans.index(min(pans))
        assert abs(ctl.state.commanded["gripper"] - 2) < 0.6
        assert dt > 0.4
    finally:
        ctl.stop()


def test_estop_stops_playback():
    ctl = make_ctl()
    try:
        prog = P.Program("t", [])
        prog.add_pose(pose(shoulder_pan=60))
        prog.add_pose(pose(shoulder_pan=-60))
        pl = P.Player(ctl, prog, speed=0.5, loop=True)
        pl.start()
        for _ in range(20):
            pl.update()
            time.sleep(0.02)
        ctl.estop()
        time.sleep(0.05)
        pl.update()
        assert not pl.running
    finally:
        ctl.stop()


def test_compliant_mode_tracks_measured_and_reenables_without_jump():
    ctl = make_ctl()
    try:
        be = ctl.backend
        ctl.set_compliant(True)
        time.sleep(0.1)
        assert ctl.state.compliant and be.torque is False
        be.q["shoulder_pan"] = be.goal["shoulder_pan"] = 25.0  # student moves the arm by hand
        time.sleep(0.1)
        assert abs(ctl.state.commanded["shoulder_pan"] - 25.0) < 0.5
        ctl.set_compliant(False)
        time.sleep(0.1)
        assert not ctl.state.compliant and be.torque is True
        assert abs(ctl.state.commanded["shoulder_pan"] - 25.0) < 0.5
        ctl.set_compliant(True)
        time.sleep(0.1)
        ctl.estop()  # e-stop while limp -> torque back on
        time.sleep(0.1)
        assert not ctl.state.compliant
    finally:
        ctl.stop()
