# 신흥 SO-101 로봇팔 동아리

SO-101 로봇팔(LeRobot)로 하는 동아리 수업 자료입니다.

| 회차 | 활동 | 실행 |
|---|---|---|
| 1 | **로봇에게 동작 가르치기**: 자세를 저장하고 이어서 재생 | `teach.bat` |
| 2 | **AI 눈으로 로봇 조종하기**: 웹캠 손 인식으로 팔 조종 | `hand_follow.bat` |

| 자료 | 내용 |
|---|---|
| **[GUIDE.md](GUIDE.md)** | **따라하기 가이드** — 설치부터 미션까지 한 단계씩 |
| [slides/class_slides.html](slides/class_slides.html) | 수업 슬라이드 (받은 폴더에서 더블클릭하면 브라우저로 열림) |
| [CLASS_GUIDE.md](CLASS_GUIDE.md) | 선생님용 수업 진행 계획 |
| [SETUP.md](SETUP.md) | 선생님용 로봇 연결·설정 |

## 다운로드

- **Git 없이:** 이 페이지 위쪽 초록색 **`Code` → `Download ZIP`** → 압축 풀기
- **Git으로:**
  ```bash
  git clone https://github.com/kisan2970/sinheung_so101_class.git
  ```

## 설치 (Windows 11, 처음 1번)

1. Python 3.10 을 설치합니다 (명령 프롬프트에서):
   ```bat
   winget install -e --id Python.Python.3.10
   ```
2. 압축을 푼 폴더에서 더블클릭합니다.
   - 로봇 없이 연습하는 학생 PC: `setup_student.bat` (약 300MB, 3~5분)
   - 로봇을 연결하는 수업용 PC: `setup_windows.bat` (약 3GB, 10~20분)
3. 마지막에 나오는 환경 점검에서 `[FAIL]` 이 없으면 완료입니다.

## 로봇 없이 연습하기

로봇 팔이 없어도 가상 팔로 연습할 수 있습니다.

```bat
teach.bat practice --sim
```
```bat
hand_follow.bat --sim
```

`hand_follow --sim` 은 노트북 웹캠만 있으면 됩니다.

## 안전 규칙

- 로봇이 움직이는 동안 작업 구역 안에 손을 넣지 않습니다.
- 이상하면 바로 **스페이스바(비상정지)** 를 누릅니다. 멈춘 뒤 천천히 처음 자세로 돌아갑니다. `r` 키를 누르면 다시 시작합니다.
- 그리퍼 사이에 손가락을 넣지 않습니다.

## 폴더 구성

| 경로 | 내용 |
|---|---|
| `tools/` | 실행 프로그램 (`teach.py`, `hand_follow.py`, 설치·점검 도구) |
| `so101demo/` | 안전 제어기, 손 인식, 프로그램 저장/재생 코드 |
| `config/demo.yaml` | 설정 (속도 제한, 카메라 번호 등) |
| `programs/` | 팀별로 저장된 동작 프로그램 |
| `SETUP.md` | 선생님용: 포트 찾기, 캘리브레이션, 안전 범위 설정 |
