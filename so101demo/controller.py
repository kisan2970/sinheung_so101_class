"""The single place that talks to the arm.

A background thread runs at `control_hz`:
    read measured pose -> pick target by safety state -> SafetyLimiter -> write.

Safety states
    RUN        follow the latest target from the active mode (hold pose if it goes stale)
    ESTOP_HOLD e-stop pressed: freeze at the pose measured at that instant (torque stays ON)
    HOMING     after estop_hold_s, go home at homing_speed_scale
    HOLD_HOME  at home, wait for resume()
    FAULT      comm lost; keeps reconnecting in the background, re-syncs on success

Modes never write to the bus: they call set_target(). Any exception inside the loop is caught,
counted, and leads to a reconnect - the loop itself never dies.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from . import JOINTS
from .safety import SafetyLimiter, build_limits

log = logging.getLogger(__name__)

RUN, ESTOP_HOLD, HOMING, HOLD_HOME, FAULT, STOPPED = (
    "RUN", "ESTOP_HOLD", "HOMING", "HOLD_HOME", "FAULT", "STOPPED")


@dataclass
class ArmState:
    state: str = STOPPED
    measured: dict = field(default_factory=dict)
    commanded: dict = field(default_factory=dict)
    target: dict = field(default_factory=dict)
    stalled: list = field(default_factory=list)
    loop_hz: float = 0.0
    comm_errors: int = 0
    message: str = ""
    t: float = 0.0
    at_target: bool = False   # commanded pose has reached the (clamped) target and stopped
    target_seq: int = 0       # seq of the set_target() call that the last tick used
    compliant: bool = False   # torque off, arm can be moved by hand


class ArmController:
    def __init__(self, cfg: dict, backend):
        self.cfg = cfg
        self.s = cfg["safety"]
        self.backend = backend
        self.dt = 1.0 / float(cfg["robot"].get("control_hz", 50))
        self.limiter: SafetyLimiter | None = None
        self.home: dict | None = cfg.get("home")
        self._lock = threading.Lock()
        self._target: dict | None = None
        self._target_t = 0.0
        self._speed_scale = 1.0
        self._state = ArmState()
        self._estop_t = 0.0
        self._estop_pose: dict | None = None
        self._stall_since: dict[str, float] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._connected = False
        self._pending_reset: dict | None = None
        self._seq = 0
        self._compliant_req: bool | None = None

    # ------------------------------------------------------------------ public API
    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="arm-control", daemon=True)
        self._thread.start()

    def wait_ready(self, timeout: float = 10.0) -> bool:
        t0 = time.time()
        while time.time() - t0 < timeout:
            st = self.state
            if st.state in (RUN, HOLD_HOME) and st.commanded:  # first tick done
                return True
            time.sleep(0.05)
        return False

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self.backend.disconnect()

    def set_target(self, target: dict[str, float], speed_scale: float = 1.0) -> int:
        """Called by modes. Partial dicts allowed (missing joints keep their current command)."""
        with self._lock:
            base = dict(self._target) if self._target else (dict(self.limiter.pos) if self.limiter and self.limiter.pos else {})
            base.update({k: float(v) for k, v in target.items() if k in JOINTS})
            self._target = base
            self._target_t = time.perf_counter()
            self._speed_scale = speed_scale
            self._seq += 1
            return self._seq

    def set_compliant(self, on: bool) -> None:
        """Torque off (hand-guiding) / back on. While compliant the loop only reads and keeps the
        command synced to the measured pose, so re-enabling torque never jumps."""
        with self._lock:
            self._compliant_req = bool(on)

    def go_home(self, speed_scale: float | None = None) -> None:
        if self.home:
            self.set_target(self.home, speed_scale or self.s["homing_speed_scale"])

    def estop(self) -> None:
        with self._lock:
            if self._state.state in (RUN, HOMING, HOLD_HOME):
                pose = self._state.measured or (self.limiter.pos if self.limiter else None)
                self._estop_pose = dict(pose) if pose else None
                self._estop_t = time.perf_counter()
                self._target = None
                self._state.state = ESTOP_HOLD
                self._state.message = "EMERGENCY STOP"
                log.warning("E-STOP")
                self._pending_reset = self._estop_pose  # applied in the loop thread
                if self._state.compliant:
                    self._compliant_req = False  # e-stop while hand-guiding: torque back ON, hold

    def resume(self) -> None:
        with self._lock:
            if self._state.state in (HOLD_HOME, HOMING, ESTOP_HOLD):
                self._target = None
                self._state.state = RUN
                self._state.message = "resumed"

    @property
    def state(self) -> ArmState:
        with self._lock:
            st = self._state
            return ArmState(st.state, dict(st.measured), dict(st.commanded), dict(st.target),
                            list(st.stalled), st.loop_hz, st.comm_errors, st.message, st.t,
                            st.at_target, st.target_seq, st.compliant)

    # ------------------------------------------------------------------ loop
    def _connect(self) -> None:
        self.backend.connect()
        measured = self.backend.read()
        limits = build_limits(self.cfg, getattr(self.backend, "calibration", None))
        self.limiter = SafetyLimiter(limits)
        self.limiter.reset(measured)
        if self.home is None:
            self.home = dict(measured)
        self.home = self.limiter.clamp(self.home)
        self._connected = True
        with self._lock:
            self._target = None
            self._state.comm_errors = 0
            if self._state.state in (STOPPED, FAULT):
                self._state.state = RUN
            self._state.message = f"connected ({self.backend.name})"
        log.info("arm connected, limits=%s", {j: (round(l.lo, 1), round(l.hi, 1)) for j, l in limits.items()})

    def _run(self) -> None:
        backoff = 0.5
        last = time.perf_counter()
        hz_avg = 0.0
        while not self._stop.is_set():
            if not self._connected:
                try:
                    self._connect()
                    backoff = 0.5
                except Exception as e:  # noqa: BLE001
                    log.error("connect failed: %s", e)
                    with self._lock:
                        self._state.state = FAULT
                        self._state.message = f"connect failed: {e}"
                    try:
                        self.backend.disconnect()
                    except Exception:  # noqa: BLE001
                        pass
                    self._stop.wait(backoff)
                    backoff = min(5.0, backoff * 2)
                    continue
                last = time.perf_counter()

            t0 = time.perf_counter()
            dt = min(0.1, t0 - last)
            last = t0
            if dt > 0:
                hz_avg = 0.9 * hz_avg + 0.1 * (1.0 / dt)
            try:
                self._tick(dt or self.dt)
                with self._lock:
                    self._state.comm_errors = 0
            except Exception as e:  # noqa: BLE001
                with self._lock:
                    self._state.comm_errors += 1
                    n = self._state.comm_errors
                log.warning("control tick error (%d): %s", n, e)
                if n >= int(self.s.get("max_comm_errors", 10)):
                    log.error("too many errors -> reconnect")
                    self._connected = False
                    with self._lock:
                        self._state.state = FAULT
                        self._state.message = f"comm lost: {e}"
                    try:
                        self.backend.disconnect()
                    except Exception:  # noqa: BLE001
                        pass
            with self._lock:
                self._state.loop_hz = hz_avg
            sleep = self.dt - (time.perf_counter() - t0)
            if sleep > 0:
                self._stop.wait(sleep)

    def _tick(self, dt: float) -> None:
        measured = self.backend.read()
        now = time.perf_counter()
        with self._lock:
            state = self._state.state
            target = self._target
            target_age = now - self._target_t
            scale = self._speed_scale
            seq = self._seq
            pending, self._pending_reset = self._pending_reset, None
            comp_req, self._compliant_req = self._compliant_req, None

        lim = self.limiter
        if pending:
            lim.reset(pending)  # e-stop: drop commanded velocity to zero at the measured pose

        if comp_req is not None and comp_req != self._state.compliant:
            self.backend.set_torque(not comp_req)
            lim.reset(measured)
            with self._lock:
                self._state.compliant = comp_req
                self._target = None
                self._state.message = "torque OFF (hand guide)" if comp_req else "torque ON"
        if self._state.compliant:
            lim.reset(measured)
            with self._lock:
                self._state.measured = measured
                self._state.commanded = dict(measured)
                self._state.target = dict(measured)
                self._state.at_target = True
                self._state.t = time.time()
            return
        if state == ESTOP_HOLD:
            target, scale = self._estop_pose or dict(lim.pos), self.s["homing_speed_scale"]
            if now - self._estop_t >= float(self.s["estop_hold_s"]):
                with self._lock:
                    self._state.state = state = HOMING
                    self._state.message = "returning home"
        if state == HOMING:
            target, scale = self.home, float(self.s["homing_speed_scale"])
            if all(abs(lim.pos[j] - self.home[j]) < 1.0 for j in JOINTS) and \
                    all(abs(v) < 1.0 for v in lim.vel.values()):
                with self._lock:
                    self._state.state = state = HOLD_HOME
                    self._state.message = "holding home (press resume)"
        if state == HOLD_HOME:
            target, scale = self.home, float(self.s["homing_speed_scale"])
        if state == RUN and (target is None or target_age > float(self.s["target_timeout_s"])):
            target = None  # no/stale target from the mode: brake and hold the current pose

        cmd = lim.hold(dt) if target is None else lim.step(target, dt, scale)

        # stall / obstruction detection: arm can't reach command -> stop pushing
        stalled = []
        for j in JOINTS:
            if j == "gripper":
                continue  # gripping an object is a normal "stall"; torque limit protects fingers
            if abs(cmd[j] - measured[j]) > float(self.s["stall_error_deg"]):
                t_s = self._stall_since.setdefault(j, now)
                if now - t_s > float(self.s["stall_time_s"]):
                    lim.reset_joint(j, measured[j])
                    cmd[j] = measured[j]
                    stalled.append(j)
            else:
                self._stall_since.pop(j, None)
        if stalled:
            log.warning("stall on %s -> command resynced to measured", stalled)
            with self._lock:
                if self._target:
                    for j in stalled:
                        self._target[j] = measured[j]

        self.backend.write(cmd)
        goal = lim.clamp(target) if target else cmd
        at_target = all(abs(cmd[j] - goal[j]) < 0.5 for j in JOINTS) and \
            all(abs(v) < 0.5 for v in lim.vel.values())
        with self._lock:
            self._state.at_target = at_target
            self._state.target_seq = seq
            self._state.measured = measured
            self._state.commanded = cmd
            self._state.target = dict(target) if target else dict(cmd)
            self._state.stalled = stalled
            self._state.t = time.time()
