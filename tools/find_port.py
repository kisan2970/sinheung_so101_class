"""1단계-1: follower / leader 포트 찾기 (USB 뽑았다 꽂기 방식) → config/local.yaml 에 저장.

    python tools/find_port.py
"""

import time

import _bootstrap  # noqa: F401
from so101demo.config import update_local
from so101demo.ports import list_ports


def snapshot():
    return {p.device: p for p in list_ports()}


def detect(label: str):
    input(f"\n[{label}] 팔의 USB 케이블이 꽂혀 있는 상태에서 Enter...")
    before = snapshot()
    input(f"[{label}] 이제 {label} 팔의 USB 케이블만 뽑고 Enter...")
    time.sleep(1.0)
    after = snapshot()
    gone = [d for d in before if d not in after]
    if len(gone) != 1:
        print(f"  !! 사라진 포트가 {len(gone)}개입니다: {gone}. 다시 시도하세요.")
        return None
    dev = gone[0]
    p = before[dev]
    print(f"  => {label} = {dev}  ({p.description}, SN={p.serial_number})")
    input(f"[{label}] 케이블을 다시 꽂고 Enter...")
    time.sleep(1.5)
    now = snapshot()
    # COM number may change after re-plugging; follow the serial number
    if p.serial_number:
        for d, q in now.items():
            if q.serial_number == p.serial_number:
                dev = d
    if dev not in now:
        print(f"  !! 다시 꽂은 뒤 {dev} 가 안 보입니다. 케이블을 확인하세요.")
    return dev, p.serial_number


def main():
    print("현재 포트:")
    for p in list_ports():
        print(f"  {p.device:<10} {p.description}  SN={p.serial_number}")
    patch = {"robot": {}}
    r = None
    while r is None:
        r = detect("follower")
    patch["robot"]["port"], patch["robot"]["port_serial"] = r
    if input("\nleader 팔도 찾을까요? [Y/n] ").strip().lower() != "n":
        r = None
        while r is None:
            r = detect("leader")
        patch["robot"]["leader_port"], patch["robot"]["leader_port_serial"] = r
    update_local(patch)
    print("\n저장 완료: config/local.yaml", patch)
    if patch["robot"].get("port_serial") is None:
        print("참고: 보드에 USB 시리얼번호가 없어 COM 번호가 바뀌면 다시 실행해야 합니다.")


if __name__ == "__main__":
    main()
