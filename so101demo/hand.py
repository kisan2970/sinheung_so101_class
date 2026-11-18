"""Hand tracking (MediaPipe Hands, pretrained) and hand -> joint mapping.

HandTracker.process(bgr) -> HandObs | None
    x, y      palm centre in the image, 0..1 (x already mirrored if mirror=True)
    roll      hand tilt in degrees (0 = fingers up, + = tilted to the viewer's right)
    openness  0 = fist, 1 = open palm
HandMapper.map(obs) -> joint targets, using poses recorded with `hand_follow.py --setup`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import JOINTS
from .filters import OneEuro

WRIST, THUMB_TIP, INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP = 0, 4, 5, 9, 13, 17
TIPS = (8, 12, 16, 20)


@dataclass
class HandObs:
    x: float
    y: float
    roll: float
    openness: float
    score: float
    landmarks: object = None  # mediapipe landmark list, for drawing


def _d(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def features(pts: list[tuple[float, float]], aspect: float = 4 / 3, mirror: bool = True) -> tuple:
    """pts: 21 normalized (x, y) image coords. Returns (x, y, roll_deg, openness)."""
    p = [(x * aspect, y) for x, y in pts]  # undo non-square normalization for angles/lengths
    palm_ids = (WRIST, INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP)
    cx = sum(pts[i][0] for i in palm_ids) / 5
    cy = sum(pts[i][1] for i in palm_ids) / 5
    vx, vy = p[MIDDLE_MCP][0] - p[WRIST][0], p[MIDDLE_MCP][1] - p[WRIST][1]
    roll = math.degrees(math.atan2(vx, -vy))  # 0 = pointing up in the image
    palm = max(1e-6, _d(p[WRIST], p[MIDDLE_MCP]))
    ratio = sum(_d(p[t], p[WRIST]) for t in TIPS) / len(TIPS) / palm
    # measured on MediaPipe test images: fist 0.8, one finger 1.0, two fingers 1.25, open palm ~1.7
    openness = min(1.0, max(0.0, (ratio - 0.9) / (1.65 - 0.9)))
    if mirror:
        cx, roll = 1.0 - cx, -roll
    return cx, cy, roll, openness


class HandTracker:
    def __init__(self, mirror: bool = True, min_conf: float = 0.6):
        import mediapipe as mp

        self.mp = mp
        self.mirror = mirror
        self.hands = mp.solutions.hands.Hands(
            static_image_mode=False, max_num_hands=1, model_complexity=1,
            min_detection_confidence=min_conf, min_tracking_confidence=0.5)

    def process(self, bgr) -> HandObs | None:
        import cv2

        h, w = bgr.shape[:2]
        res = self.hands.process(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        if not res.multi_hand_landmarks:
            return None
        lm = res.multi_hand_landmarks[0]
        score = res.multi_handedness[0].classification[0].score if res.multi_handedness else 1.0
        pts = [(q.x, q.y) for q in lm.landmark]
        x, y, roll, op = features(pts, aspect=w / h, mirror=self.mirror)
        return HandObs(x, y, roll, op, score, lm)

    def close(self) -> None:
        self.hands.close()


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


class HandMapper:
    """x -> shoulder_pan, y -> blend between 'low' and 'high' arm poses, tilt -> wrist_roll,
    openness -> gripper. All inputs pass through One-Euro filters."""

    BODY = ("shoulder_lift", "elbow_flex", "wrist_flex")

    def __init__(self, hcfg: dict, home: dict, gripper: dict):
        self.c = hcfg
        self.home = home
        self.g = gripper
        self.low = hcfg.get("pose_low") or home
        self.high = hcfg.get("pose_high") or home
        self.pan_l = hcfg.get("pan_left")
        self.pan_r = hcfg.get("pan_right")
        if self.pan_l is None or self.pan_r is None:
            self.pan_l, self.pan_r = home["shoulder_pan"] - 30, home["shoulder_pan"] + 30
        sm = hcfg.get("smoothing", {})
        mk = lambda: OneEuro(sm.get("min_cutoff", 1.0), sm.get("beta", 0.02))  # noqa: E731
        self.f = {k: mk() for k in ("x", "y", "roll", "open")}

    @property
    def configured(self) -> bool:
        c = self.c
        return all(c.get(k) is not None for k in ("pose_low", "pose_high", "pan_left", "pan_right"))

    def reset(self) -> None:
        for f in self.f.values():
            f.reset()

    def map(self, obs: HandObs, t: float) -> dict[str, float]:
        x0, x1, y0, y1 = self.c.get("box", [0.15, 0.85, 0.15, 0.85])
        x = self.f["x"](obs.x, t)
        y = self.f["y"](obs.y, t)
        roll = self.f["roll"](obs.roll, t)
        op = self.f["open"](obs.openness, t)
        tx = min(1.0, max(0.0, (x - x0) / (x1 - x0)))
        ty = min(1.0, max(0.0, (y1 - y) / (y1 - y0)))  # hand up on screen -> 1
        out = dict(self.home)
        out["shoulder_pan"] = _lerp(self.pan_l, self.pan_r, tx)
        for j in self.BODY:
            out[j] = _lerp(self.low[j], self.high[j], ty)
        rr = float(self.c.get("roll_range_deg", 60))
        tilt = max(-1.0, min(1.0, roll / 60.0))
        out["wrist_roll"] = self.home["wrist_roll"] + float(self.c.get("roll_sign", 1)) * rr * tilt
        out["gripper"] = _lerp(self.g["closed"], self.g["open"], op)
        return {j: out[j] for j in JOINTS}
