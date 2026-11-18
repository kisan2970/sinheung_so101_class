import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from so101demo import JOINTS  # noqa: E402
from so101demo.backends import SimBackend  # noqa: E402
from so101demo.config import load_config  # noqa: E402
from so101demo import controller as C  # noqa: E402
from so101demo.safety import SafetyLimiter, build_limits, limits_from_calibration  # noqa: E402


def cfg():
    c = load_config()
    c["robot"]["backend"] = "sim"
    c["robot"]["control_hz"] = 100
    c["home"] = None
    return c


def zero():
    return {j: 0.0 for j in JOINTS}


def run(lim, target, seconds, dt=0.01, scale=1.0):
    traj = []
    for _ in range(int(seconds / dt)):
        traj.append(lim.step(target, dt, scale))
    return traj


def test_velocity_and_acceleration_bounded_and_converges():
    c = cfg()
    lims = build_limits(c, None)
    lim = SafetyLimiter(lims)
    lim.reset(zero())
    target = {j: 80.0 for j in JOINTS}
    dt = 0.01
    traj = [zero()] + run(lim, target, 6.0, dt)
    for j in JOINTS:
        v = [(b[j] - a[j]) / dt for a, b in zip(traj, traj[1:])]
        acc = [(b - a) / dt for a, b in zip(v, v[1:])]
        assert max(abs(x) for x in v) <= lims[j].vmax + 1e-6, j
        assert max(abs(x) for x in acc) <= lims[j].amax * 1.0001 + 1e-6, j
        assert abs(traj[-1][j] - 80.0) < 0.05, (j, traj[-1][j])
        # no overshoot beyond tolerance
        assert max(p[j] for p in traj) < 80.0 + 0.5, j


def test_targets_are_clamped_to_limits_and_nan_ignored():
    c = cfg()
    c["safety"]["joint_limits"] = {"shoulder_pan": [-30, 20]}
    lim = SafetyLimiter(build_limits(c, None))
    lim.reset(zero())
    run(lim, {"shoulder_pan": 999.0, "elbow_flex": float("nan")}, 5.0)
    assert abs(lim.pos["shoulder_pan"] - 20.0) < 1e-6
    assert lim.pos["elbow_flex"] == 0.0
    run(lim, {"shoulder_pan": -999.0}, 5.0)
    assert abs(lim.pos["shoulder_pan"] + 30.0) < 1e-6


def test_calibration_limits_with_margin():
    calib = {j: {"range_min": 1000, "range_max": 3000} for j in JOINTS}
    b = limits_from_calibration(calib, margin_pct=10)
    half = 1000 * 360 / 4095
    assert math.isclose(b["shoulder_pan"][1], half - 2 * half * 0.1)
    assert b["gripper"] == (10.0, 90.0)


def test_starting_outside_box_does_not_jump():
    lim = SafetyLimiter(build_limits(cfg(), None))
    start = zero()
    start["shoulder_lift"] = 130.0  # beyond +110 default box (folded rest pose)
    lim.reset(start)
    p = lim.hold(0.01)
    assert p["shoulder_lift"] == 130.0
    p = lim.step(start, 0.01)  # target gets clamped to 110, but we must walk, not teleport
    assert p["shoulder_lift"] > 129.0


def _controller(**kw):
    c = cfg()
    c["safety"].update(kw)
    be = SimBackend(c)
    ctl = C.ArmController(c, be)
    ctl.start()
    assert ctl.wait_ready(3)
    return ctl, be


def test_estop_holds_then_returns_home_and_resume():
    ctl, be = _controller(estop_hold_s=0.3, homing_speed_scale=1.0)
    try:
        home = dict(ctl.home)
        for _ in range(60):
            ctl.set_target({"shoulder_pan": 40.0, "elbow_flex": -30.0})
            time.sleep(0.01)
        ctl.estop()
        time.sleep(0.05)
        st = ctl.state
        assert st.state == C.ESTOP_HOLD
        frozen = st.commanded["shoulder_pan"]
        ctl.set_target({"shoulder_pan": 80.0})  # modes are ignored during estop
        time.sleep(0.15)
        assert abs(ctl.state.commanded["shoulder_pan"] - frozen) < 1.0
        deadline = time.time() + 5
        while ctl.state.state != C.HOLD_HOME and time.time() < deadline:
            time.sleep(0.05)
        assert ctl.state.state == C.HOLD_HOME
        assert abs(ctl.state.commanded["shoulder_pan"] - home["shoulder_pan"]) < 1.0
        ctl.resume()
        assert ctl.state.state == C.RUN
    finally:
        ctl.stop()


def test_stale_target_holds_pose():
    ctl, be = _controller(target_timeout_s=0.1)
    try:
        ctl.set_target({"shoulder_pan": 50.0})
        time.sleep(0.3)  # target goes stale mid-motion
        p1 = ctl.state.commanded["shoulder_pan"]
        time.sleep(0.5)
        p2 = ctl.state.commanded["shoulder_pan"]
        assert p1 < 50.0
        assert abs(p2 - p1) < 5.0  # only braking distance, no further travel
    finally:
        ctl.stop()


def test_stall_resyncs_command():
    ctl, be = _controller(stall_error_deg=5, stall_time_s=0.1)
    try:
        be.blocked["elbow_flex"] = 5.0  # something blocks the elbow at +5 deg
        deadline = time.time() + 3
        seen = False
        while time.time() < deadline:
            ctl.set_target({"elbow_flex": 60.0})
            if "elbow_flex" in ctl.state.stalled:
                seen = True
                break
            time.sleep(0.01)
        assert seen
        assert ctl.state.commanded["elbow_flex"] < 12.0
    finally:
        ctl.stop()


def test_comm_errors_trigger_reconnect_and_loop_survives():
    ctl, be = _controller(max_comm_errors=3)
    try:
        be.fail_rate = 1.0
        deadline = time.time() + 2
        while ctl.state.state != C.FAULT and time.time() < deadline:
            time.sleep(0.02)
        assert ctl.state.state == C.FAULT
        be.fail_rate = 0.0
        deadline = time.time() + 5
        while ctl.state.state != C.RUN and time.time() < deadline:
            time.sleep(0.05)
        assert ctl.state.state == C.RUN
    finally:
        ctl.stop()
