import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from so101demo import JOINTS  # noqa: E402
from so101demo.filters import OneEuro  # noqa: E402
from so101demo.hand import HandMapper, HandObs, features  # noqa: E402

HOME = {j: 0.0 for j in JOINTS}
HOME["gripper"] = 30.0
LOW = dict(HOME, shoulder_lift=40.0, elbow_flex=-30.0, wrist_flex=10.0)
HIGH = dict(HOME, shoulder_lift=-40.0, elbow_flex=30.0, wrist_flex=-10.0)
HC = {"pose_low": LOW, "pose_high": HIGH, "pan_left": -50.0, "pan_right": 50.0,
      "box": [0.2, 0.8, 0.2, 0.8], "roll_range_deg": 60, "roll_sign": 1}
GRIP = {"open": 60.0, "closed": 2.0}


def settle(m, obs, n=60):
    out = None
    for i in range(n):
        out = m.map(obs, i / 30)
    return out


def test_mapping_extremes():
    m = HandMapper(HC, HOME, GRIP)
    assert m.configured
    a = settle(m, HandObs(x=0.0, y=1.0, roll=0, openness=1.0, score=1))
    assert abs(a["shoulder_pan"] + 50) < 0.5 and abs(a["shoulder_lift"] - 40) < 0.5  # left, low
    assert abs(a["gripper"] - 60) < 0.5
    m.reset()
    b = settle(m, HandObs(x=1.0, y=0.0, roll=60, openness=0.0, score=1))
    assert abs(b["shoulder_pan"] - 50) < 0.5 and abs(b["shoulder_lift"] + 40) < 0.5  # right, high
    assert abs(b["wrist_roll"] - 60) < 0.5 and abs(b["gripper"] - 2) < 0.5


def test_unconfigured_falls_back_to_small_pan_only():
    m = HandMapper({}, HOME, GRIP)
    assert not m.configured
    a = settle(m, HandObs(x=1.0, y=0.0, roll=0, openness=0.5, score=1))
    assert abs(a["shoulder_pan"] - 30) < 0.5
    assert a["shoulder_lift"] == 0.0


def test_one_euro_suppresses_jitter_but_follows_steps():
    f = OneEuro(1.0, 0.02)
    import random
    random.seed(0)
    ys = [f(0.5 + random.gauss(0, 0.01), i / 30) for i in range(90)]
    assert max(ys[30:]) - min(ys[30:]) < 0.02  # raw noise spans ~0.05
    for i in range(90, 150):
        y = f(0.9, i / 30)
    assert abs(y - 0.9) < 0.02


def _hand(cx, cy, open_=True, tilt=0.0):
    import math
    # synthetic 21-point hand pointing up, palm size 0.1
    pts = [(0.0, 0.0)] * 21
    def rot(dx, dy):
        c, s = math.cos(math.radians(tilt)), math.sin(math.radians(tilt))
        return (cx + dx * c - dy * s, cy + dx * s + dy * c)
    pts = list(pts)
    pts[0] = rot(0, 0.05)
    for i, dx in zip((5, 9, 13, 17), (-0.03, 0.0, 0.015, 0.03)):
        pts[i] = rot(dx, -0.05)
    for i, dx in zip((8, 12, 16, 20), (-0.03, -0.01, 0.01, 0.03)):
        pts[i] = rot(dx, -0.12 if open_ else 0.0)
    return pts


def test_features_open_closed_tilt_and_mirror():
    x, y, roll, op = features(_hand(0.3, 0.5, True), aspect=1.0, mirror=False)
    assert op > 0.9 and abs(roll) < 1 and abs(x - 0.3) < 0.02
    _, _, _, op2 = features(_hand(0.3, 0.5, False), aspect=1.0, mirror=False)
    assert op2 < 0.1
    _, _, roll3, _ = features(_hand(0.5, 0.5, True, tilt=30), aspect=1.0, mirror=False)
    assert 25 < roll3 < 35
    xm, _, rollm, _ = features(_hand(0.3, 0.5, True, tilt=30), aspect=1.0, mirror=True)
    assert abs(xm - 0.7) < 0.03 and rollm < -25
