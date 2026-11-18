"""1단계-2: lerobot 캘리브레이션 (follower → leader). 포트는 config/local.yaml 에서 읽음.

    python tools/calibrate.py            # follower + leader
    python tools/calibrate.py follower   # 하나만

lerobot 안내에 따라:
  1) 모든 관절을 가동 범위의 '중간'에 두고 Enter
  2) 각 관절을 끝에서 끝까지 천천히 전부 움직인 뒤 Enter
이미 Ubuntu 쪽에서 같은 팔을 캘리브레이션 했다면 그 json 을 복사해도 됩니다 (README 참고).
"""

import subprocess
import sys

import _bootstrap  # noqa: F401
from so101demo.config import load_config
from so101demo.ports import resolve_port


def run(args):
    print(">>", " ".join(args))
    return subprocess.call(args)


def main():
    cfg = load_config()["robot"]
    which = sys.argv[1:] or ["follower", "leader"]
    py = sys.executable
    rc = 0
    if "follower" in which:
        port = resolve_port(cfg.get("port"), cfg.get("port_serial"))
        if not port:
            sys.exit("follower 포트 없음 → python tools/find_port.py")
        rc |= run([py, "-m", "lerobot.calibrate", "--robot.type=so101_follower",
                   f"--robot.port={port}", f"--robot.id={cfg['id']}"])
    if "leader" in which:
        port = resolve_port(cfg.get("leader_port"), cfg.get("leader_port_serial"))
        if not port:
            sys.exit("leader 포트 없음 → python tools/find_port.py")
        rc |= run([py, "-m", "lerobot.calibrate", "--teleop.type=so101_leader",
                   f"--teleop.port={port}", f"--teleop.id={cfg['leader_id']}"])
    sys.exit(rc)


if __name__ == "__main__":
    main()
