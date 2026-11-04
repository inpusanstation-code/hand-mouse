# 이 브랜치를 이어서 작업하는 Claude에게

## 이 브랜치(`feat/dan-tuning-20261105`)의 출처
- **집 PC에서 폰 카메라로 쓰면서 맞춘 값이다.** 원래 개발하던 PC·웹캠에서 한 작업이 아니다.
  - PC: `DESKTOP-09LB4VQ` (Windows 사용자 `Bob`), 작업 폴더 `Documents\claude code\hand-mouse-main` (GitHub `main` 4124a0f를 내려받은 것)
  - 카메라: 휴대폰 카메라를 **카메라 번호 0**으로 연결, 1280×720 @ 30fps, 거울 모드, 조작 손 = 오른손 (`--ui qt`, 손바닥(Dan) 모드)
  - 기간: 2026-11-04 저녁 ~ 11-05 새벽
  - 이 카메라에서는 손이 작게 찍혔다: 손 크기(손목→손가락 뿌리 중 가장 긴 것)가 화면 폭의 약 0.09~0.16.
- 판단 근거는 그 PC의 `logs/failures/*.json`(손을 놓치거나 클릭할 때 앞뒤 3초 관절 좌표)을 같은 코드로 다시 돌린 결과다. **이 기록은 저장소에 없다**(`.gitignore`). 다른 PC에서는 볼 수 없으니, 그 PC의 기록이 있는 것처럼 말하지 말 것.
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
