# 이 브랜치를 이어서 작업하는 Claude에게

## 이 브랜치(`feat/dan-tuning-20261105`)의 출처
- **집 PC에서 폰 카메라로 쓰면서 맞춘 값이다.** 원래 개발하던 PC·웹캠에서 한 작업이 아니다.
  - PC: 집 PC (녹화·모델 정보에는 별명 `home-pc`, 이전 녹화는 코드 `pc-ded5`로 표시. 이 저장소는 공개라 실제 PC 이름·사용자 이름은 적지 않는다), 작업 폴더 `Documents\claude code\hand-mouse-main` (GitHub `main` 4124a0f를 내려받은 것)
  - 카메라: 휴대폰 카메라를 **카메라 번호 0**으로 연결, 1280×720 @ 30fps, 거울 모드, 조작 손 = 오른손 (`--ui qt`, 손바닥(Dan) 모드)
  - 기간: 2026-11-04 저녁 ~ 11-05 새벽
  - 이 카메라에서는 손이 작게 찍혔다: 손 크기(손목→손가락 뿌리 중 가장 긴 것)가 화면 폭의 약 0.09~0.16.
- 판단 근거는 그 PC의 `logs/failures/*.json`(손을 놓치거나 클릭할 때 앞뒤 3초 관절 좌표)을 같은 코드로 다시 돌린 결과다.
- **그 기록의 사본이 `field-logs/2026-11-04-home-pc-phone/failures/`에 있다**(JSON 200개 + `index.csv`, 약 36 MB). 앱은 최근 200개만 남기므로 11-04 22:24 ~ 11-05 00:30 것뿐이고, 그 앞(19시~22시)의 기록은 이미 지워졌다. 영상은 없고 관절 좌표·판정 값만 있다(창 제목·페이지 이름 없음 확인).
  - 다시 돌리는 법: 파일마다 `trigger_t + frames[i].t`가 시각, `frames[i].lm`이 21개 관절(x, y, z, 1280×720 기준 정규화). `GestureEngine.process(lm, timestamp=시각)`에 시간 순서대로 넣고, `engine.frame_aspect = 720/1280`. 파일끼리 시간이 겹치므로 시각으로 중복을 없앨 것.
  - 앱의 `logs/`(`.gitignore`)와 섞이지 않게 일부러 다른 폴더에 두었다. 새 PC에서 쌓이는 기록과 합치지 말 것.
- 한 사람, 한 카메라 배치의 기록이다. 수치는 정확도가 아니라 "같은 기록에서 전후 비교"다. 자세한 근거는 `docs/` 각 문서의 날짜별 절에 있다.

## 이 환경에 맞춘 값 (`config/gestures.json`)
- 핀치가 손 크기에 비례해 시작: `pinch_size_ratio` 0.2, `click_size_ratio` 0.22, `ring_click_size_ratio` / `pinky_click_size_ratio` 0.25 (손이 작게 찍혀 고정 거리 기준이 너무 넓었음)
- 반주먹: `curled_moving_speed` 0.3, `curled_pinch_size_ratio` 0.13, `curled_click_size_ratio` 0.15, `side_pinch_after_curl` 0.4, `side_rearm_ratio` 0.35, 배율 곡선 `shape_dpi_curve` 0.5, 주먹 배율 `fist_dpi_multiplier` 35
- 핀치 브라우징: `drag_hold_size_ratio` 0.15, `scroll_return_open` 0.012, `scroll_return_distance` 0.015
- 주먹 커서 궤적: `path_smoothing` true, `path_follow` 0.5, `path_reverse_deg` 30
- 방향 보정: `palm_axes`는 이 자세에서 잰 값(위아래 약 50° 기울어짐)인데 **꺼 둠**(`palm_axes_strength` 0). 팔꿈치 보정도 꺼 둠(`elbow_pivot` false). 둘 다 커서를 엉뚱하게 휘게 했다(`docs/path-smoothing.md`).
- Pose 팔 표시: `pose_enabled` true, `pose_smooth` 0.25 (`models/pose_landmarker_lite.task`)
- 바탕화면 보기·V 사인·모션 모드 기준도 이 기록으로 조정했다(`docs/motion-mode.md`, `docs/toggle-sign.md`).

## 다른 PC·카메라에서 이어서 할 때
- 손 크기에 비례하는 기준은 카메라가 바뀌어도 어느 정도 따라가지만, 배율(`fist_dpi_multiplier`, `shape_dpi_curve`)과 화면 단위 고정 기준은 카메라·거리에 따라 다르게 느껴질 수 있다. 사용자가 불편을 말하면 **그 PC에서 새로 쌓인 `logs/failures`로** 다시 판단하고, 이 PC의 결과와 섞지 말 것.
- `palm_axes`는 이 PC의 자세에서 잰 값이라 다른 자리에서는 의미가 없다. 켜려면 그 자리에서 Qt 화면의 "커서 방향 보정"을 다시 한다.
- `tests/fixtures/*.json`은 이 PC 기록에서 잘라 낸 관절 좌표다(영상 없음, 1280×720). 회귀 시험용이다.
- 알려진 실패: `tests/test_motion_mode.py::test_the_corner_badge_text_follows_the_mode`는 이 작업 전부터 실패한다(Qt가 설치된 환경에서만 돌고, 시험용 객체에 `close_state`가 없음).
- Qt 화면 실행: `uv run --locked --extra qt python main.py --ui qt` (`--extra qt` 없이 실행하면 PySide6가 없다).

## 지금 상태와 다음 할 일 (2026-11-05 새벽, 브랜치 `feat/tcn-training-app-transition`)
- 된 것: 학습 데이터 녹화(`docs/recording.md`, Qt "학습 데이터 녹화"), 첫 안내 녹화 1개(`recordings/20261105-030947-guided.jsonl.gz`, 폰 카메라 17분, 엄지+약지·엄지+검지·반주먹 이동 × 자세 3), TCN 학습 스크립트(`scripts/train_tcn.py`), 모델(`models/gesture_tcn.onnx` + `.json`), 앱의 손짓 확인기(`src/gesture_gate.py`, Qt "손짓 확인 (TCN)"). 결과·수치는 `docs/recording.md`.
- **2026-11-05 새벽 4시대: "TCN 학습 앱" 1차 완료** (`docs/training-studio.md`): `studio.bat`/`studio.py` 번호 메뉴(명령·옵션 설명), 앱 위쪽 [학습 센터](동작별 데이터·인식률·학습 정확도·오작동·조언, [집중 녹화], [학습 시작] 진행·손실 곡선, [내보내기]), `scripts/training_report.py`, `scripts/export_model.py`, `train_tcn.py --progress`, `src/training_center.py`. 아래 1~4는 이 요청의 원문 요약이다. 아직 GitHub에 올리지 않았다(사용자가 "올려"라고 할 때만).
- **학습 데이터 공유 방식(사용자 결정, 2026-11-05)**: 녹화(`recordings/*.jsonl.gz`)는 코드와 같은 브랜치에 계속 함께 올린다. 학습 센터가 총량을 보여 주고 500 MB를 넘으면 전용 저장소 분리를 권한다. 파일 이름에 PC 이름, 녹화 중엔 `.part`, 학습은 완성된 파일만(`src/recorder.finished_recordings`). `docs/training-studio.md` 6절.
- 사용자가 요청했던 작업: 이 앱을 "TCN 학습 앱"으로 바꾸기.
  1. 긴 실행 명령(`uv run --locked --extra qt --extra train python main.py --ui qt`)을 쉽게: 무엇을 하는지, 어떤 옵션이 어떤 효과인지 바로 알 수 있게(예: 실행 메뉴·바로가기 배치 파일, 옵션 설명).
  2. 동작별 **학습 정도(데이터 양·학습 손실)**와 **인식률(학습에 안 쓴 자세에서의 인식·오작동)**을 앱 화면에서 바로 보이게. 사용자가 "이 동작은 데이터가 더 필요하다"를 알아보고 그 동작만 골라 집중 녹화할 수 있게.
  3. 녹화 → 데이터셋 → TCN 학습 → 평가 → **다른 앱에 옮길 수 있는 형태로 내보내기(export)**를 앱 안에서 한 흐름으로. 틈날 때마다 녹화해서 학습시키는 앱.
  4. 학습 중인 TCN의 동작별 학습률·인식률을 사용자가 볼 수 있게.
- 함께 하기로 한 인식률 개선(아직 안 함): 실제로 닿은 구간만 정답으로 다시 표시, 동작별 판정 기준 조정, 두 동작은 모델이 직접 판정하는 선택지, 평소 녹화 + F 표시 데이터로 주기적 재학습, 다른 날 추가 녹화. 확인기만으로는 인식률이 규칙 수준(약 55%)에 묶인다(모델 단독은 처음 보는 자세에서 82%).

## 다른 PC에서 같은 환경 만들기 (TCN 학습 준비 포함, 2026-11-05)
- 손짓 판정을 학습 모델(TCN)로 보완하는 작업을 시작한다. 학습용 라이브러리는 선택 묶음 `train`에 있다: `torch`(CPU 판, 약 200 MB), `onnx`(학습한 모델 내보내기), `onnxruntime`(앱에서 모델 실행).
- 설치: 저장소 폴더에서
  ```
  uv sync --locked --extra qt --extra train
  ```
  uv가 없으면 `run.bat`이 먼저 설치한다. GPU는 필요 없다(이 PC도 CPU로 학습).
- **주의:** `uv run`/`uv sync`에 `--extra`를 빼면 uv가 환경을 기본 묶음에 맞추면서 PySide6·torch를 지운다. 이 작업에서는 늘 `--extra qt --extra train`을 붙인다.
- 이 PC에서 확인한 버전: torch 2.15.0+cpu, onnx 1.23.2, onnxruntime 1.31.1, mediapipe 1.2.0, PySide6 6.12.0, Python 3.12. 시험 359개 통과(위의 알려진 실패 1개 제외).
- 계획(사용자와 합의): 앱을 TCN 학습 데이터 제조기로 확장 → 오류가 많은 동작부터(엄지+약지 우클릭, 엄지+검지 스크롤, 반주먹 이동="아무것도 아님") 3가지 각도 × 15회 + 반주먹 이동 15분 녹화 → 규칙 엔진 위에 "의도한 동작인지" 확인기로 붙여 같은 기록에서 규칙과 비교 → 좋아지면 다른 동작으로 넓힌다. 녹화에는 화면 좌표뿐 아니라 3D 관절(world landmarks), Pose 어깨, PC·카메라·사람·날짜를 처음부터 함께 저장한다.
