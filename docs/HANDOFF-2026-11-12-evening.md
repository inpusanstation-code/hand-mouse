# 인수인계 (2026-11-12 오전 ~ 저녁, PC 별명 `pc-rtx3060`, CPU로 실행)

다음 작업자(Claude Code)가 이어받기 위한 요약이다. 앞 단계(11-11 저녁 ~ 11-12 새벽)는 `docs/HANDOFF-2026-11-12.md`에 있다. 날짜별 근거·수치는 `CLAUDE.md`의 각 절과 `docs/motion-mode.md`·`docs/virtual-hand.md` 끝 절들에 있다. 이 문서는 "무엇이 됐고, 무엇을 확인 못 했고, 다음에 무엇을 할지"만 모았다.

- 브랜치: `feat/hand-mouse-20261112-evening` (같은 날 11시대에 올린 `feat/hand-mouse-20261112` 위에 그 뒤 작업을 한 커밋으로 얹음)
- 실행: `uv sync --locked --extra qt --extra train --extra llm` 후 `uv run --locked --extra qt --extra train --extra llm python main.py --ui qt` (`--extra`를 빼면 PySide6·torch·anthropic이 지워진다)
- 시험: 같은 명령으로 `python -m pytest -q` → 이 PC에서 **1,237개 통과**(실제 시간을 쓰는 시험 몇 개가 전체 실행에서 가끔 한 번 실패했다가 다시 돌리면 통과: `test_moving_pinch`, `test_point_area`, `test_sequence`).
- 사용자 환경: 가상 손 모드, 오른손 조작, 거울 모드, 웹캠 1280×720@30. 오늘 오후부터 **왼손을 "다른 손 모션"과 다이얼로 함께 쓴다.**

## 1. 오늘 만든 것 (오전, 11시대 커밋에 이미 들어 있음)

| 항목 | 핵심 파일 | CLAUDE.md 절 |
|---|---|---|
| onnx 후보 옆에 "사례 없이 같은 방식으로 학습한 기준" | `scripts/onnx_auto_update.py`, `onnx_candidate.py` | onnx 후보 옆에 "같은 방식의 기준" |
| 가르친 손 모양이 견본에서 안 펴졌던 손가락을 보면 거절 (검지만 펴기 ↔ 락 사인) | `posture_teach.finger_stats/fingers_ok` | '검지만 펴기'와 창 닫기 |
| 수정 메뉴의 추가 학습, 겹치는 동작 알림 | `gesture_overlap.py` | 수정 메뉴의 추가 학습 |
| 확인 모델이 볼 맥락 길이를 동작마다 고름 (0.5~2.5초) | `online/verifier.py`, `safety.OnlineGate` | 확인 모델이 볼 맥락 길이 |
| 두 손 모드는 별개의 세계 표시, 가상 손 엄지+새끼 집기(`vh_pinky`) | `action_bindings.gesture_mode`, `virtual_hand.ShapePinky` | 두 손 모드는 별개의 세계 |
| 포인팅: 꺾인 손목, 웹 페이지 요소 탭 | `point_mode.shape`, `uia_tap_at` | 포인팅 두 절 |
| 손 펴기를 손바닥 방향 넷으로 나눔 | `pose_probe.faced` | 손 펴기를 손바닥 방향으로 |
| 끌기 바꾸기, 거부된 저장 표시, AI 연결 목록 = 등록 동작 전체 | `default_moves.py`, `llm_binding.History` | 끌기 바꾸기 / AI 연결 목록 |

## 2. 오늘 만든 것 (오후~저녁, 이번 커밋)

| 항목 | 핵심 파일 | 문서 |
|---|---|---|
| 오탐지 검토를 다 하면 "다 했어요" 알림 | `dashboard.qml` `useReviewDone` | — |
| 커서·손 그림 떨림과 늦음 함께 줄임 (필터 값, 1.5 px / 2.5 px 데드존) | `virtual_hand.py` `BoxMapper.DEAD_PX`, `ViewSmoother.DEAD_PX` | `docs/virtual-hand.md`, CLAUDE.md "떨림과 늦음" |
| 주먹 스크롤이 자주 안 걸리던 것 (느슨한 주먹) | `QtRuntime._loose_fist` | CLAUDE.md "주먹 스크롤이 자주 안 걸리던 것" |
| **다른 손(왼손) 모션**: 손을 펴 들면 준비, 쓸기 = 모션 명령, 조작 손은 그대로 | `src/other_hand_motion.py`, `QtRuntime._other_motion_step` | `docs/motion-mode.md` 끝 절들, CLAUDE.md "다른 손으로 모션" |
| 쓸기 손 모양: 손 펴고 좌/우 = 이전/다음 탭, 검지만 좌/우 = 뒤로/앞으로 | `MotionMode.stroke_shape` | 같은 절 |
| 다른 손 고르기 개선 (손날 자세, 이어받기가 왼손을 잡던 것) | `other_hand_motion.other_hand`, `HandFollower.select(avoid=)` | 같은 절 |
| 미리보기·바탕화면에 왼손 스켈레톤, 왼손 영역 상자 | `HandSkeleton.qml`, `otherHandWindow`, `QtRuntime._other_draw` | 같은 절 |
| 스켈레톤 색·불투명도·굵기 설정 (프로필별) | `src/skeleton_style.py` | CLAUDE.md "스켈레톤 색" |
| 유튜브 등록 모션 6개 (샤카 ±5초, 주먹 배속, V = 쇼츠 이전/다음은 휠) | `config/gesture_bindings.json` `motion_yt_*`, `wheel_at_window_middle` | CLAUDE.md "유튜브 손동작" |
| **왼손 다이얼**: 엄지+검지 0.4초 = 배속 다이얼, 엄지+중지 0.4초 = 이동 다이얼, 주먹 = 닫기 | `src/speed_dial.py`, `QtRuntime._speed_dial_step`, `_seek_fire` | `docs/motion-mode.md` 끝 절들, CLAUDE.md "왼손 다이얼" |
| 다이얼: 11시 = 가운데, 손 방향 그대로의 값, 이동은 다이얼이 열린 동안 엄지+검지 집을 때마다 실행, 한 단계 12° | `speed_dial.py` | 같은 절 |
| 다이얼 방향 바꿈: **왼쪽(반시계) = 빠르게·앞으로** | `speed_dial.DIRECTION` | `docs/motion-mode.md` "다이얼 방향 바꿈" |
| 왼손 검지 **왼쪽** 쓸기(뒤로)가 안 되던 것 | `MotionMode.stroke_shape`, `motion_index_gap`, `motion_nav_frac` | `docs/motion-mode.md` 마지막 절 |
| AI 카드의 손 그림 (가상 손 키, 손바닥 방향이 같은 프레임만) | `gesture_preview.py` | CLAUDE.md "지운 동작 보관" |
| 지운 동작 보관과 되살리기 | `llm_binding.History._snapshot/restore`, `config/deleted_gestures.json` | CLAUDE.md "지운 동작 보관과 되살리기" |

## 3. 확인하지 못한 것 (중요)

**전부 시험(가짜 손)과 기록 재생으로만 확인했다. 실제 카메라에서 사용자가 써 보고 "된다"고 한 것은 세로 주먹 스크롤뿐이다.**

- 왼손 다이얼 전체: 실제 유튜브에서 배속·이동이 게이지 숫자대로 되는지 확인하지 못했다. 키가 배속을 곱해 움직이는 것만 youtube.com에서 확인했다.
  - 사용자가 마우스로 배속을 바꾸면 앱은 모른다(`_yt_rate`).
  - 2배속이 아닐 때 이동 초를 정확히 맞추는 보정은 없다(게이지에 "n배속이라 실제 +m초"로만 보여 준다).
- 다이얼 방향을 바꾼 뒤, 시험 손에서는 주먹을 쥐며 **왼쪽으로** 돌 때 넘어간 단계가 되돌려지지 않았다(굽힘 1.47/1.46/1.41, 되돌림 기준 `CURLING` 1.45 바로 위). 실제 손에서도 그런지는 모른다.
- 검지 왼쪽 쓸기 수정: 재생에서 뒤로가기가 0 → 8번으로 늘었다. 늘어난 것 중 의도하지 않은 것이 섞였는지는 모른다.
- 다른 손이 우연히 들어왔을 때 얼마나 오작동하는지 모른다(녹화에는 조작 손만 있다).
- 쇼츠 휠 이동, 왼손 바탕화면 그림, 스켈레톤 설정의 실제 모습은 아직 눈으로 보지 못했다.
- 떨림 줄이기 필터는 녹화 재생으로만 쟀다. 체감 확인은 아직이다.

## 4. 다음에 할 일 (우선순위 순)

1. **사용자에게 실제로 써 보게 하고, 안 되는 것을 `logs/failures`로 확정한다.**
   - 왼손 관련 기록: `motion_other_swipe`(보낸 쓸기), `motion_other_miss`(거절된 큰 쓸기와 그 이유 `why`), `motion_other_enter/exit`.
   - 프레임의 `olm`은 다른 손의 관절이다. 다시 돌리는 법은 아래 5절.
   - 실패 기록에는 쿨다운이 있어 앱이 보낸 쓸기가 다 남지는 않는다. 횟수 비교는 재생으로 한다.
2. **다이얼 실사용 점검**: 게이지 숫자와 유튜브 숫자, 주먹 닫기 때 단계 되돌림(특히 왼쪽으로 돌린 뒤), 저절로 열림(재생 기준 0.07~0.13회/분).
3. **검지 왼쪽 쓸기**: 또 안 되면 `motion_other_miss`의 `why`를 본다.
   - `slow`(0.45폭/초 미만)가 남는 주된 원인이었다.
   - `return_stroke`(쓸고 돌아오는 손)는 의도한 거절이다.
4. **오늘 쌓인 쓰면서 배우기 자료**: 확인 모델 둘(`comp_open_hand_hold@up` 24번, `comp_index_point_hold@up` 39번)이 `waiting/one_day` 상태다. 다른 날 4번 이상 쓰면 앱이 자동으로 검사한다.
   - 오늘 학습 회차 5번은 모두 `rejected`였다(`online/round_times.jsonl`; 내 모델 후보 탈락은 설계대로이고 기존 모델을 유지).
   - 좌클릭 검토가 여전히 적어서, onnx 후보에 "통과한 클릭"이 들어가지 못한다(앞 인수인계 1번 그대로).
5. 남겨 둔 결정(사용자에게 물어볼 것):
   - 지운 예전 동작 10개를 되살릴지. 손 펴기 유지 → Win+D만 되살렸다.
   - 다른 손 아래 방향 쓸기는 뺐다(손을 내리는 동작과 같아서).
   - 다이얼을 여는 방식(0.4초 길게 집기)이 계속 괜찮은지.
6. 앞 인수인계(`docs/HANDOFF-2026-11-12.md`)의 남은 항목: 통과한 클릭이 들어간 onnx 후보, 학습 중 앱을 끄고 이어 하기 실제 확인.

## 5. 이번에 함께 올린 기록: `field-logs/2026-11-12-pc-rtx3060/`

앱의 `logs/`, `data/`는 git에 없어서 사본을 따로 둔다. 새로 쌓이는 기록과 섞지 말 것. 관절 좌표와 판정 값만 있고 영상은 없다.

| 폴더 | 내용 |
|---|---|
| `failures/` | 앱이 남긴 최근 200개(17:03~17:46) + `index.csv`. 왼손 모션 진입·쓸기·거절, 주먹 스크롤 관성, V 사인 등. |
| `use_events/` | 오늘 손 명령마다 앞 3초·뒤 2초 관절(`.jsonl.gz`, 29개 실행) + `reviews.json`(검토 판정), `gate.json`. |
| `virtual_clicks/` | 가상 손 클릭 기록(`.jsonl.gz`). |
| `composite_fires/` | 복합 동작이 실행된 순간의 직전 관절. |
| `pose_probe/` | [손 모양 보여주기] 시도들. |
| `posture_teach/` | 가르친 손 모양 모델(`posture_teach.json`)과 견본(`examples/`). |
| `online/` | 쓰면서 배우기 상태: 기본 모델, 내 모델 버전, 확인 모델 상태, 회차 소요 시간. 표본 저장소(`samples/`, 209 MB)는 기록에서 다시 만들 수 있어 뺐다. |
| `topmost_fixes.log` | 메인 창 "항상 위"를 뗀 시각들. |

- 일부러 뺀 것: `logs/point_trace.jsonl`. 포인팅이 가리킨 파일·링크 이름이 들어 있다.
- 실패 기록 다시 돌리는 법:
  - 파일마다 `trigger_t + frames[i].t`가 시각이다. `lm`은 조작 손, `olm`은 다른 손(21관절, 1280×720 기준 정규화)이다.
  - 파일끼리 시간이 겹치므로 시각으로 중복을 없앤다.
  - 0.2초 넘게 비면 끊긴 구간으로 나눈다.
  - 다른 손 쓸기: `OtherHandMotion().step(t, lm)`
  - 다이얼: `SpeedDial("speed"|"seek").step(t, lm)`
