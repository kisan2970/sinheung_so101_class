"""Robot backends. Both expose: connect(), read() -> {joint: deg}, write({joint: deg}), disconnect().

RealBackend wraps lerobot 0.3.3 SO101Follower in degree mode and writes hardware speed/accel/torque
limits into the STS3215 registers. SimBackend is a kinematic stand-in so the whole demo (dashboard,
modes) runs without the arm — useful for development and as an on-site fallback.
"""

from __future__ import annotations

import json
import logging
import random
import time
from pathlib import Path

from . import JOINTS

log = logging.getLogger(__name__)


def calibration_path(robot_id: str, kind: str = "robots", name: str = "so101_follower") -> Path:
    from lerobot.constants import HF_LEROBOT_CALIBRATION  # honours HF_LEROBOT_HOME

    return Path(HF_LEROBOT_CALIBRATION) / kind / name / f"{robot_id}.json"


def load_calibration(robot_id: str) -> dict | None:
    p = calibration_path(robot_id)
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


class RealBackend:
    name = "real"

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.robot = None

    @property
    def calibration(self) -> dict | None:
        return load_calibration(self.cfg["robot"]["id"])

    def connect(self) -> None:
        from lerobot.robots.so101_follower import SO101Follower, SO101FollowerConfig

        from .ports import resolve_port

        rc = self.cfg["robot"]
        rc["port"] = resolve_port(rc.get("port"), rc.get("port_serial"))
        if not rc.get("port"):
            raise RuntimeError("robot.port 가 설정되지 않았습니다. tools/find_port.py 를 먼저 실행하세요.")
        if self.calibration is None:
            raise RuntimeError(
                f"캘리브레이션 파일이 없습니다: {calibration_path(rc['id'])}\n"
                "tools/calibrate.py 를 먼저 실행하세요."
            )
        s = self.cfg["safety"]
        robot_cfg = SO101FollowerConfig(
            port=rc["port"],
            id=rc["id"],
            use_degrees=True,
            max_relative_target=s.get("max_relative_target_deg"),
            # 데모 프로세스가 죽어도 팔이 툭 떨어지지 않도록 토크 유지
            disable_torque_on_disconnect=False,
        )
        robot = SO101Follower(robot_cfg)
        # calibrate=False: never block on input() during a show; calibration file must already match.
        robot.connect(calibrate=False)
        if not robot.is_calibrated:
            # motors lost their calibration (e.g. swapped arm) -> write the file into the motors
            robot.bus.write_calibration(robot.calibration)
        self.robot = robot
        self._apply_hw_limits()

    def _apply_hw_limits(self) -> None:
        s = self.cfg["safety"]
        bus = self.robot.bus
        for j in JOINTS:
            bus.write("Acceleration", j, int(s["hw_acceleration"]), num_retry=2)
            bus.write("Goal_Velocity", j, int(s["hw_goal_velocity"]), num_retry=2)
            bus.write("Torque_Limit", j, int(s["hw_torque_limit"][j]), num_retry=2)
        log.info("hardware limits written: acc=%s vel=%s", s["hw_acceleration"], s["hw_goal_velocity"])

    def read(self) -> dict[str, float]:
        pos = self.robot.bus.sync_read("Present_Position")
        return {j: float(pos[j]) for j in JOINTS}

    def write(self, cmd: dict[str, float]) -> None:
        self.robot.send_action({f"{j}.pos": cmd[j] for j in JOINTS})

    def set_torque(self, on: bool) -> None:
        if on:
            self.robot.bus.enable_torque(num_retry=2)
        else:
            self.robot.bus.disable_torque(num_retry=2)

    def disconnect(self) -> None:
        if self.robot is not None:
            try:
                self.robot.disconnect()
            except Exception:  # noqa: BLE001 - best effort on shutdown
                log.exception("disconnect failed")
            self.robot = None


class SimBackend:
    """First-order kinematic arm with slight sensor noise."""

    name = "sim"
    calibration = None

    def __init__(self, cfg: dict, tau: float = 0.08, fail_rate: float = 0.0):
        self.tau = tau
        self.fail_rate = fail_rate  # for tests: probability that a read raises
        self.q = {j: 0.0 for j in JOINTS}
        self.q["gripper"] = 30.0
        self.goal = dict(self.q)
        self.blocked: dict[str, float] = {}  # tests: joint -> max reachable value
        self._t = None

    def connect(self) -> None:
        self._t = time.perf_counter()

    def _advance(self) -> None:
        now = time.perf_counter()
        dt = now - self._t
        self._t = now
        a = min(1.0, dt / self.tau)
        for j in JOINTS:
            self.q[j] += (self.goal[j] - self.q[j]) * a
            if j in self.blocked:
                self.q[j] = min(self.q[j], self.blocked[j])

    def read(self) -> dict[str, float]:
        if self.fail_rate and random.random() < self.fail_rate:
            raise ConnectionError("simulated bus error")
        self._advance()
        return {j: v + random.gauss(0, 0.05) for j, v in self.q.items()}

    def write(self, cmd: dict[str, float]) -> None:
        self.goal = dict(cmd)

    def set_torque(self, on: bool) -> None:
        self.torque = on

    def disconnect(self) -> None:
        pass


def make_backend(cfg: dict):
    kind = cfg["robot"].get("backend", "real")
    if kind == "sim":
        return SimBackend(cfg)
    if kind == "real":
        return RealBackend(cfg)
    raise ValueError(f"unknown backend {kind}")


class LeaderArm:
    """SO-101 leader (torque-free puppet arm) read in degrees, same convention as the follower."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.dev = None

    def connect(self) -> None:
        from lerobot.teleoperators.so101_leader import SO101Leader, SO101LeaderConfig

        from .ports import resolve_port

        rc = self.cfg["robot"]
        port = resolve_port(rc.get("leader_port"), rc.get("leader_port_serial"))
        if not port:
            raise RuntimeError("leader 포트가 없습니다. tools/find_port.py 를 실행하세요.")
        dev = SO101Leader(SO101LeaderConfig(port=port, id=rc["leader_id"], use_degrees=True))
        dev.connect(calibrate=False)
        if not dev.is_calibrated:
            if not dev.calibration:
                raise RuntimeError("leader 캘리브레이션 파일이 없습니다. tools/calibrate.py leader")
            dev.bus.write_calibration(dev.calibration)
        self.dev = dev

    def read(self) -> dict[str, float]:
        a = self.dev.get_action()
        return {j: float(a[f"{j}.pos"]) for j in JOINTS}

    def disconnect(self) -> None:
        if self.dev is not None:
            try:
                self.dev.disconnect()
            except Exception:  # noqa: BLE001
                log.exception("leader disconnect failed")
            self.dev = None
