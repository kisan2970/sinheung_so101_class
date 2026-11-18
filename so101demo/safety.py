"""Software safety layer: joint-space workspace clamp + velocity/acceleration-limited tracking.

Every command that reaches the motors goes through `SafetyLimiter.step()`. The limiter keeps its own
commanded position/velocity state, so even if a mode sends a target far away (or garbage), the arm
moves there smoothly with bounded speed and acceleration, and never outside the joint limits.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import JOINTS

STS3215_RES = 4095  # lerobot uses (resolution - 1) for degree conversion


@dataclass
class JointLimit:
    lo: float
    hi: float
    vmax: float
    amax: float


def limits_from_calibration(calib: dict, margin_pct: float) -> dict[str, tuple[float, float]]:
    """Convert a lerobot calibration json (raw ticks) into degree / gripper-% bounds.

    Body joints use lerobot MotorNormMode.DEGREES: deg = (raw - mid) * 360 / 4095.
    Gripper uses RANGE_0_100.
    """
    out = {}
    for j in JOINTS:
        c = calib[j]
        if j == "gripper":
            lo, hi = 0.0, 100.0
        else:
            half = (c["range_max"] - c["range_min"]) / 2 * 360 / STS3215_RES
            lo, hi = -half, half
        m = (hi - lo) * margin_pct / 100.0
        out[j] = (lo + m, hi - m)
    return out


def build_limits(cfg: dict, calib: dict | None) -> dict[str, JointLimit]:
    s = cfg["safety"]
    if calib is not None:
        bounds = limits_from_calibration(calib, s.get("calib_margin_pct", 8))
    else:  # sim backend / no calibration: generous symmetric defaults
        bounds = {j: (-110.0, 110.0) for j in JOINTS}
        bounds["gripper"] = (0.0, 100.0)
    user = s.get("joint_limits") or {}
    limits = {}
    for j in JOINTS:
        lo, hi = bounds[j]
        if j in user and user[j] is not None:
            ulo, uhi = user[j]
            lo, hi = max(lo, ulo), min(hi, uhi)  # intersection: user limits can only shrink the range
        if lo >= hi:
            raise ValueError(f"Empty joint range for {j}: [{lo}, {hi}]")
        limits[j] = JointLimit(lo, hi, float(s["max_velocity"][j]), float(s["max_acceleration"][j]))
    return limits


class SafetyLimiter:
    """Per-joint second-order rate limiter with braking (trapezoidal velocity profile)."""

    def __init__(self, limits: dict[str, JointLimit]):
        self.limits = limits
        self.pos: dict[str, float] | None = None
        self.vel = {j: 0.0 for j in JOINTS}

    def clamp(self, target: dict[str, float]) -> dict[str, float]:
        out = {}
        for j in JOINTS:
            lim = self.limits[j]
            v = target.get(j)
            if v is None or not math.isfinite(v):
                v = self.pos[j] if self.pos is not None else (lim.lo + lim.hi) / 2
            out[j] = min(lim.hi, max(lim.lo, float(v)))
        return out

    def reset(self, measured: dict[str, float]) -> None:
        """Sync the internal command state to the measured pose (no jump on start/resync)."""
        self.pos = {j: float(measured[j]) for j in JOINTS}
        self.vel = {j: 0.0 for j in JOINTS}

    def reset_joint(self, j: str, value: float) -> None:
        self.pos[j] = float(value)
        self.vel[j] = 0.0

    def step(self, target: dict[str, float], dt: float, speed_scale: float = 1.0) -> dict[str, float]:
        if self.pos is None:
            raise RuntimeError("SafetyLimiter.reset() must be called with the measured pose first")
        goal = self.clamp(target)
        self._prev = dict(self.pos)
        speed_scale = min(1.0, max(0.05, speed_scale))
        for j in JOINTS:
            lim = self.limits[j]
            vmax = lim.vmax * speed_scale
            amax = lim.amax * speed_scale
            err = goal[j] - self.pos[j]
            # max speed that still lets us stop at the goal with amax (discrete-time version of
            # sqrt(2*a*d), so there is no overshoot at the control rate)
            ad = amax * dt
            v_brake = ad * (math.sqrt(0.25 + 2.0 * abs(err) / (ad * dt)) - 0.5)
            v_des = math.copysign(min(vmax, v_brake, abs(err) / dt), err)
            dv = max(-amax * dt, min(amax * dt, v_des - self.vel[j]))
            self.vel[j] += dv
            self.pos[j] += self.vel[j] * dt
            self._keep_inside(j, lim)
        return dict(self.pos)

    def _keep_inside(self, j: str, lim: JointLimit) -> None:
        # never *leave* the box. A joint that starts outside it (e.g. folded rest pose beyond the
        # margin) is not teleported in; it walks in smoothly when given a target.
        p = self.pos[j]
        if p > lim.hi and self._prev[j] <= lim.hi:
            self.pos[j], self.vel[j] = lim.hi, 0.0
        elif p < lim.lo and self._prev[j] >= lim.lo:
            self.pos[j], self.vel[j] = lim.lo, 0.0

    def hold(self, dt: float) -> dict[str, float]:
        """No target: brake to standstill (bounded deceleration) and stay where we are."""
        if self.pos is None:
            raise RuntimeError("SafetyLimiter.reset() must be called first")
        self._prev = dict(self.pos)
        for j in JOINTS:
            lim = self.limits[j]
            dv = max(-lim.amax * dt, min(lim.amax * dt, -self.vel[j]))
            self.vel[j] += dv
            self.pos[j] += self.vel[j] * dt
            self._keep_inside(j, lim)
        return dict(self.pos)
