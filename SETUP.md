# SO-101 전시 데모 ("미래틱한" 인터랙티브 로봇팔)

> **동아리 수업용:** [CLASS_GUIDE.md](CLASS_GUIDE.md) — 티칭&재생(`teach.bat`), 손동작 따라하기(`hand_follow.bat`)

목표: AI 성능보다 **관객 반응 + 절대 멈추지 않는 안정성**. 모든 동작은 하나의 안전 제어기를 거칩니다.

## 전체 구조 (계획)

```
start_demo.bat ─► supervisor (자식 프로세스 감시 · 자동 재시작)
                   ├─ core      : ArmController(50Hz, 안전계층) + 모드 상태머신 + WebSocket 서버
                   │              키보드: 1~4 모드 전환 / SPACE 비상정지 / R 재개
                   ├─ vision    : 카메라 → MediaPipe Hands/Face → 결과를 core 로 (죽어도 core 는 계속)
                   ├─ voice     : (5단계) 로컬 Whisper → 명령어 매칭
                   └─ dashboard : 정적 HTML (three.js 디지털 트윈, HUD) ← WebSocket
모드:  IDLE(숨쉬기/얼굴 바라보기·손 흔들기) · MIMIC(손동작 따라하기) · VOICE(궤적 재생→ACT 교체 가능) · TELEOP(leader 팔, 백업)
```

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | 설치, 포트 탐지, 캘리브레이션, 관절 읽기/쓰기, **안전 제한** | ✅ 코드 완료 → **실기 확인 필요** |
| 2 | 손동작 따라하기 (MediaPipe Hands, One-Euro 필터, 손 없으면 홈 복귀) | ✅ 코드 완료 (`tools/hand_follow.py`) → 실기 확인 필요 |
| + | 티칭 & 재생 (수업용) | ✅ 코드 완료 (`tools/teach.py`) → 실기 확인 필요 |
| 3 | 대기 모드 (숨쉬기, 얼굴 추적, 손 흔들기) | 대기 |
| 4 | 대시보드 (three.js URDF 트윈, 카메라 오버레이, 그래프, HUD) | 대기 |
| 5 | 음성 명령 (Whisper, 궤적 재생 → 정책 인터페이스로 ACT 교체) | 대기 |
| - | supervisor, start_demo.bat, 현장 체크리스트 | 대기 |

## 안전 설계 (1단계에서 구현됨)

모드 코드는 버스에 직접 쓰지 못하고 `ArmController.set_target()` 만 호출합니다. 명령은 아래 계층을 모두 통과합니다.

1. **작업공간 한계**: 캘리브레이션 범위에서 양끝 8% 마진 ∩ 현장에서 `record_limits.py` 로 기록한 범위(추가 3° 마진). 목표값은 항상 이 박스로 클램프, NaN/누락 값은 무시.
2. **속도·가속 제한**: 관절별 vmax / amax 사다리꼴 프로파일(이산시간 제동식 → 오버슈트 없음). `config/demo.yaml` 의 `max_velocity`, `max_acceleration`.
3. **하드웨어 레지스터**: 연결 시 STS3215 `Acceleration`(lerobot 기본 254=최대 → 40), `Goal_Velocity`(1500 step/s ≈ 132°/s), `Torque_Limit`(그리퍼 50%) 기록. lerobot `max_relative_target`(10°/스텝)도 함께 사용.
4. **막힘 감지**: 명령-실제 오차가 12° 이상 0.4초 지속 → 그 관절 명령을 실제 위치로 되돌려 더 밀지 않음 (사람/물체와 접촉 시).
5. **목표 끊김**: 모드가 0.5초간 목표를 안 보내면 감속 후 현재 자세 유지.
6. **비상정지**: 토크는 끈 채로 두지 않음 → 그 순간 자세에서 정지 유지(1.5초) → 35% 속도로 홈 복귀 → 재개(R) 대기.
7. **통신 오류**: 10회 연속 실패 시 FAULT → 백오프 재연결(포트 COM 번호가 바뀌어도 USB 시리얼번호로 추적) → 측정값으로 재동기화 후 복귀. 제어 루프 스레드는 예외로 죽지 않음.
8. 프로세스가 종료돼도 `disable_torque_on_disconnect=False` → 팔이 떨어지지 않음.

시뮬레이션 테스트: `python -m pytest -q tests` (속도/가속 한계, 클램프, 비상정지 시퀀스, 막힘, 재연결).

## 1단계 실행 순서 (Windows 11, `demo` 폴더에서)

> follower 전원(12V)·USB 연결, leader USB 연결. 팔 주변 반경 50cm 비우기.

```bat
setup_windows.bat
```
설치 후 자동으로 `tools\check_env.py` 실행 → 결과 `logs\env_report.json`, 카메라 스냅샷 `logs\camera_*.jpg`.

이후 매번:
```bat
.venv\Scripts\activate
```

| 순서 | 명령 | 확인할 것 |
|---|---|---|
| 1-1 | `python tools\find_port.py` | follower/leader COM 포트가 `config\local.yaml` 에 저장됨 |
| 1-2 | `python tools\calibrate.py` | lerobot 안내대로 (중간 자세 Enter → 전 관절 끝까지 움직이고 Enter) |
| 1-3 | `python tools\test_joints.py --sim` | 로봇 없이 로직 확인 |
| 1-4 | `python tools\test_joints.py` | A 읽기 값 변화, B 관절별 ±10° 왕복이 부드러움, C 스페이스 → 정지 → 홈 복귀, 추종오차 OK |
| 1-5 | `python tools\record_limits.py` | 토크 OFF, 손으로 안전 범위만 움직이고 `h`로 홈 기록, Enter 저장 |
| 1-6 | `python tools\test_joints.py --amp 20` | 새 한계/홈이 반영되었는지 (시작 시 출력되는 한계 표) |

**Ubuntu 쪽에서 이미 캘리브레이션 했다면** `~/.cache/huggingface/lerobot/calibration/robots/so101_follower/<id>.json` 을
Windows `%USERPROFILE%\.cache\huggingface\lerobot\calibration\robots\so101_follower\demo_follower.json` 으로 복사하면 1-2 생략 가능
(leader 는 `teleoperators\so101_leader\demo_leader.json`).

문제 시: 추종오차 CHECK → 전원 어댑터(12V, 5A 이상)·데이지체인 케이블 확인. 포트가 안 보이면 CH343 드라이버 설치.
