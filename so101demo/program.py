"""Teach & replay: a program is a list of steps, each either a pose or a wait.

    {"name": "team1", "steps": [{"pose": {...joint: deg...}}, {"wait": 1.0}, ...]}

Player is non-blocking: call update() from your loop (~50 Hz). Between poses the safety limiter
generates a smooth trapezoidal move; the arm briefly stops at every saved pose.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import JOINTS
from . import controller as C
from .config import DEMO_ROOT

PROGRAM_DIR = DEMO_ROOT / "programs"


@dataclass
class Program:
    name: str = "untitled"
    steps: list = field(default_factory=list)

    @property
    def n_poses(self) -> int:
        return sum(1 for s in self.steps if "pose" in s)

    def add_pose(self, pose: dict[str, float]) -> None:
        self.steps.append({"pose": {j: round(float(pose[j]), 2) for j in JOINTS}})

    def add_wait(self, seconds: float) -> None:
        if self.steps and "wait" in self.steps[-1]:
            self.steps[-1]["wait"] = round(self.steps[-1]["wait"] + seconds, 2)
        else:
            self.steps.append({"wait": round(seconds, 2)})

    def undo(self) -> dict | None:
        return self.steps.pop() if self.steps else None

    def path(self) -> Path:
        safe = re.sub(r"[^\w\-가-힣]", "_", self.name) or "untitled"
        return PROGRAM_DIR / f"{safe}.json"

    def save(self) -> Path:
        PROGRAM_DIR.mkdir(exist_ok=True)
        p = self.path()
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"name": self.name, "steps": self.steps}, f, ensure_ascii=False, indent=1)
        return p

    @classmethod
    def load(cls, name_or_path: str) -> "Program":
        p = Path(name_or_path)
        if not p.exists():
            p = PROGRAM_DIR / (name_or_path if name_or_path.endswith(".json") else name_or_path + ".json")
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        steps = []
        for s in d.get("steps", []):  # validate: drop malformed steps instead of crashing a class
            if "pose" in s and all(j in s["pose"] for j in JOINTS):
                steps.append({"pose": {j: float(s["pose"][j]) for j in JOINTS}})
            elif "wait" in s:
                steps.append({"wait": max(0.0, min(30.0, float(s["wait"])))})
        return cls(d.get("name", p.stem), steps)


class Player:
    MOVE_TIMEOUT_S = 15.0

    def __init__(self, ctl: C.ArmController, program: Program, speed: float = 0.6, loop: bool = False):
        self.ctl = ctl
        self.program = program
        self.speed = speed
        self.loop = loop
        self.i = -1
        self.running = False
        self.status = "idle"
        self._seq = 0
        self._t_step = 0.0
        self._pose: dict | None = None

    def start(self) -> None:
        if not self.program.steps:
            self.status = "프로그램이 비어 있음"
            return
        self.running = True
        self.i = -1
        self._next()

    def stop(self, why: str = "stopped") -> None:
        self.running = False
        self.status = why

    def _next(self) -> None:
        self.i += 1
        if self.i >= len(self.program.steps):
            if self.loop:
                self.i = 0
            else:
                self.stop("완료")
                return
        step = self.program.steps[self.i]
        self._t_step = time.perf_counter()
        if "pose" in step:
            self._pose = step["pose"]
            self._seq = self.ctl.set_target(self._pose, self.speed)

    def update(self) -> None:
        if not self.running:
            return
        st = self.ctl.state
        if st.state != C.RUN:
            self.stop("비상정지로 재생 중단")
            return
        step = self.program.steps[self.i]
        n = len(self.program.steps)
        elapsed = time.perf_counter() - self._t_step
        if "pose" in step:
            self._seq = self.ctl.set_target(self._pose, self.speed)  # keep target fresh
            self.status = f"{self.i + 1}/{n} 자세로 이동"
            reached = st.at_target and st.target_seq >= self._seq - 1 and elapsed > 0.1
            if reached or elapsed > self.MOVE_TIMEOUT_S:
                self._next()
        else:
            if self._pose:
                self.ctl.set_target(self._pose, self.speed)  # hold the last pose
            self.status = f"{self.i + 1}/{n} 대기 {max(0.0, step['wait'] - elapsed):.1f}s"
            if elapsed >= step["wait"]:
                self._next()
