# testing-mlp 병합 (2026-11-10)

이 폴더(`manux-merged-20261110`)는 `manux-manux-preview`(원격 `manux-preview` 7df4fd3, #136까지)의 사본에 `manux-0.5-testing-mlp`의 변경을 골라 넣은 것이다. 원본 두 폴더는 바꾸지 않았다.

- 출처: `v0.5-testing-mlp`는 공통 조상 029af60(#100) 위의 커밋 하나 **d1713f2** "integrate Spatial MLP model datasets and drag/double-click stability"다. preview는 같은 조상 위에 #104(120Hz 커서·정지 범위)와 #136(커서 조작감·클릭/드래그 가드·온보딩)이 더 있다. 그래서 testing-mlp 폴더에 없는 preview 코드는 지워진 것이 아니라 preview가 나중에 더한 것이다.
- 비교는 d1713f2의 파일별 변경분만 보고 했다(저장소 전체를 받지 않음).
- 이 폴더의 git은 로컬 기록용이다. 원격과 연결되어 있지 않다. 첫 커밋 fdf5ca6이 preview 그대로다.

## 가져온 것

| 무엇 | 어디 | 기본값 | 사용자에게 보이는 곳 |
|---|---|---|---|
| 움직이면 바로 드래그, 드래그 중 중지 우선, 느슨한 놓기 | `features/pinch/engine.py`, `pinch.drag_on_move`, `pinch.drag_move_distance`, `pinch.drag_move_min_time` | **꺼짐**(preview #136 동작 그대로) | 설정 › 클릭 · 드래그 › "드래그 시작 방식" |
| 클릭 직후 드래그를 더블클릭과 구분 | `output/windows/sink.py`, `cursor.drag_after_click_guard` | **0(꺼짐)**, d1713f2는 0.52 | 설정 › 클릭 · 드래그 › "클릭 직후 드래그 보호" |
| 규칙과 MLP를 합친 판정 | `data/pose_studio.py` `hybrid_reading` | 표시만 | Pose Studio의 AI 판정 줄("규칙과 함께 …") |
| 실험 보조 차단 상태 줄 | `desktop._mlp_badge`, `ViewFrame.mlp_badge`, 두 대시보드 | 차단이 켜졌을 때만 보임 | 메인 화면 상태 아래 |

- `drag_on_move`를 켜면 d1713f2와 같은 동작이 된다. 다만 d1713f2의 나머지 값(길게 누르기 0.55초, 드래그 배율 1.0, 클릭 끊김 보정 0.18)은 기존 설정 그대로이므로 같은 손맛을 원하면 그 값들도 바꾼다. 셋 다 같은 "클릭 · 드래그" 탭에 있다.
- 시험: `test_pinch.py`(3), `test_windows_sink.py`(3), `test_sensitivity.py`(2), `test_studio_layout.py`(1), `test_mlp_audit.py`(2). 전체 930 통과, 11 건너뜀(기준 919 통과, 11 건너뜀).

## 설정 화면 정리 (Studio 설정 창)
기능마다 탭 하나: **스크롤 · 창 전환**(엄지·검지, 엄지·새끼, 핀치 유지) / **커서**(이동 감도, 주먹) / **클릭 · 드래그**(좌·우클릭 감도와 유지, 길게 누르기 시간, 드래그 배율, 드래그 시작 방식, 클릭 직후 보호) / **표시 · 데이터**. 예전에는 클릭 설정이 "동작 민감도"에, 드래그 배율이 "커서 민감도"에 흩어져 있었다. 커서 탭의 위치(두 번째)는 그대로라 기존 시험과 습관이 유지된다. 고급 설정은 원래대로 모든 값을 보여 준다.

## 가져오지 않은 것과 이유

| d1713f2의 내용 | 이유 |
|---|---|
| MLP 보강 클릭(규칙이 놓친 클릭을 MLP가 냄), 드래그 유지(`end`→`hold`, `move`→`drag`) | [계약 §6](contracts.md#6-의도-필터-intentfilter-예-tcn-확인기): 필터는 통과·보류·버림만 하고 새 동작을 만들지 않는다. 사용자 결정(2026-11-10)으로 이번에는 뺐다. 넣으려면 계약 변경 제안이 먼저다. |
| 모델이 있으면 차단을 기본으로 켬 | D-010 "기본 꺼짐 거부권" |
| 앱 폴더(`models/spatial_mlp`)의 모델을 불러오기, 포즈 표본 16개·모델 3개를 저장소에 커밋 | AGENTS.md: 개인 녹화·모델은 저장소 밖. 공유는 `tools/hub.py` |
| 포즈 학습 직후 실시간 제어에 자동 적용("실시간 제어에 적용되었습니다") | D-010: 미리보기 모델 선택, 기본 꺼짐 |
| `output/windows/interp.py`(144Hz 보간) | **중복**: preview #104의 120Hz 글라이드가 같은 일을 하며 클릭 되돌리기·클릭 중 커서 고정과 묶여 있다. interp로 바꾸면 그 둘이 사라진다 |
| `tools/train_spatial_mlp.py` | **중복**: `tools/studio_worker.py`의 포즈 학습과 같은 일 |
| TCN 학습 목록에서 클릭·창 제어 숨김 | 제품 방향 결정이라 별도로 정할 일 |
| Pose Studio Space 단축키(QML `Shortcut` + 브리지 키 처리 둘 다) | 같은 키를 두 곳에서 받아 한 번 눌러 두 장이 찍힐 수 있다. 확인 전에는 넣지 않음 |
| `long_press_drag_multiplier` 범위 0.1~5 | preview 기본값 15가 범위 밖이 되어 기존 사용자 설정이 거부된다. 범위는 1~30 그대로(1.0 선택 가능) |
| 주먹 배율 하한 0.1→0.05, 손 모양 `fist` 표시 | 드래그와 무관한 조정. 측정 근거 없음 |
| `cursor.py` 세로 이동을 화면 폭 기준으로 | preview #104가 바꾼 다중 모니터 세로 배율을 되돌린다 |

## 병합 중 찾은 문제
1. **(d1713f2, 고쳐서 가져옴)** 혼합 판정을 `effective_predicted_action`에 넣어, Pose Studio가 저장하는 표본의 "예측" 값 의미가 바뀌었다(규칙 접촉이 MLP 판정을 덮음). 이 병합에서는 화면 표시에만 쓴다. 시험 `test_hybrid_reading_is_display_only_and_keeps_the_rule_contact`.
2. **(d1713f2)** 위 표의 계약·결정 위반 3건(새 동작 생성, 기본 켜짐, 학습 후 자동 적용).
3. **(d1713f2)** Pose Studio Space 단축키 중복 처리, 드래그 배율 범위가 기본값을 벗어나는 문제(위 표).
4. **(preview, 설정으로 대응)** 좌클릭 직후 같은 자리에서 드래그를 시작하면 Windows가 두 번째 누름을 더블클릭으로 읽을 수 있다. 0.52초 보호는 시작점을 최대 8px 옮기는 대가가 있어 기본은 껐다. 실제 Windows에서 확인하지 못했다.

## 확인하지 못한 것
- 실제 웹캠·실제 Windows 입력으로 `drag_on_move`와 클릭 직후 보호를 써 보지 않았다. 시험은 합성 손과 가짜 백엔드다.
- 메인 화면 상태 줄은 단위 시험이 없다(QML이 오류 없이 뜨는 것은 기존 화면 시험으로 확인).

---

# virtual-hand-20261110 병합 (3단계, 2026-11-10)

출처는 `virtual-hand-20261110` 폴더(hand-mouse v0.3 구조, git 없음, 1단계에서 hand-mouse-1109를 흡수한 상태)다. 구조가 달라 파일째 합치지 않고 기능 단위로 MANUX 계층에 맞춰 다시 썼다.

## 옮긴 것

| 기능 | 원본 | 여기 | 기본값 | 시험 |
|---|---|---|---|---|
| 먼 손 좌우 판정이 뒤집혀도 같은 손 유지 | `src/hand_selection.py` `HandFollower` | `tracking/selection.py` `HandFollower`, `tracking/tracker.py`, `TrackResult.followed` | 켜짐(`tracking.hand_follow`, 원본과 같음) | `tests/unit/tracking/test_tracking.py` 4개 |
| Pause 키 긴급 정지 | `src/hotkeys.py` `VK_PAUSE`, `qt_dashboard.emergency_stop` | `platform/hotkeys.py`(Pause만 단독 키 허용), `ui/bridge.py` `emergency_stop`, 단축키 목록 "긴급 정지" | Pause | `tests/unit/ui/test_bridge.py` 2개 |
| 가상 손 모드(판정) | `src/virtual_hand.py`, `qt_runtime.py` 가상 손 부분 | `features/virtual_hand/`(새 모드 `virtual_hand`), 액션 `mouse.place`, 설정 › 이동 방식 › "가상 손 (시험)", 고급 설정 › "가상 손" | 꺼짐(이동 방식에서 고름) | `tests/unit/features/test_virtual_hand.py` 14개, 브리지 1개 |

- HandFollower 위험(원본 문서 그대로): 다른 손이 같은 자리에 들어오면 최대 3초 이어받을 수 있다. 원본도 단위 시험만 했다.
- 긴급 정지는 켜는 일이 없다(두 번 눌러도 안전). 실행 중인 학습 worker를 멈춘다. 실제 키 입력으로는 확인하지 못했다.
- 가상 손: 박스 = 모니터, 엄지+검지 짧게 = 좌클릭, 0.7초 안에 다시 = 더블클릭(같은 점), 0.45초 이상 = 끌기, 엄지+검지+중지 = 우클릭, 주먹 좌우 = 스크롤(0.5배), 엄지 접고 네 손가락 위로 0.5초 = 창 전환.
  - 원본과 다른 점: (1) 클릭이 손바닥 커서 자리에서 난다. 원본은 화면에 그린 손의 엄지·검지 사이에서 눌렀는데, 그 위치를 출력에 넘길 자리가 의도 계약에 없다(사용자 결정: 판정부터, 손 그림·클릭 위치 오프셋은 다음 단계). (2) 주먹 판정을 규칙 엔진에서 받던 것을 손 모양(`shapes.is_fist`)으로 직접 본다(기능끼리 import 금지). (3) 클릭 기록·F 표시·TCN 클릭 확인기는 옮기지 않았다.
  - 계약 변경: `docs/contracts.md` §7에 `mouse.place`(hold, `point` = 현재 모니터의 0..1) 추가.
  - 박스는 고급 설정 숫자로만 바꾼다. 카메라 화면에 직접 그리는 편집기는 아직 없다.

## 온라인 학습: MANUX와 겹치는 부분 (사용자 결정: 겹치는 것은 MANUX 쪽으로)

| 원본 `src/online/` | 하는 일 | MANUX에 이미 있는 것 | 처리 |
|---|---|---|---|
| `versions.py` | 후보·실사용·직전 모델, 검사 후 교체, 되돌리기 | `ml/store.py`(불변 버전 + active 포인터), `tools/promote_tcn.py`(별도 평가 후 설치) | MANUX 것 사용. **되돌리기(직전 active로)만 추가 필요** |
| `app_job.py` | 학습 프로세스 시작·진행 읽기 | `data/worker_job.py`, `tools/app_worker.py` | MANUX worker에 작업 종류 추가 |
| `safety.py` `OnlineGate` | 모델이 k프레임 확인한 클릭만 통과 | `features/tcn_gate`(의도 필터) | MANUX 것 사용 |
| `splits.py` | 세션 단위 분할 | 학습 도구의 시도 단위 분할(AGENTS 규칙) | MANUX 것 사용 |
| `import_guided.py`, `samples.py` | 녹화 → 표본, 표본 저장소(npz) | `data/recording.py`, `data/recorder.py`(jsonl.gz) | 새 저장 형식을 만들지 않고 MANUX 녹화 형식에 라벨을 붙여 저장 |
| `commands.py` | 등록 동작 → 명령, 안전장치 | 바인딩·라우터(D-004), 직접 TCN의 중립 재무장 | MANUX 것 사용 |
| `pose_memory.py`, `registration.py` | **몇 번 보여 주면 바로 새 동작 등록**(torch 없음) | Pose Studio(포즈 표본 + MLP 학습, 기본 꺼짐) | 새로 옮김: Pose Studio 수집 흐름 위에 "즉시 등록"으로 |
| `segmenter.py`, `collector.py` | 평소 사용 중 동작 후보 자르기·저장 | 없음 | 새로 옮김 |
| `models.py`, `trainer.py`, `replay.py`, `memory.py`, `live.py`, `baseline.py`, `dataset.py`, `update_job.py` | torch 임베딩·재생 메모리·사용 중 재학습 | `tools/train_tcn.py`(일괄 학습) | 새로 옮김: worker 안에서만(torch는 앱 프로세스 금지) |

원본 상태(그 폴더 문서): "검증 성공 시 교체"는 실데이터로 통과한 적이 없다. 미등록 동작 거부 FRR 0.44 / FAR 0.053(배수 1.5). 한 사람·한 카메라.

## 즉시 동작 등록 (3단계 1번, 완료)
- 원본 `online/pose_memory.py`·`registration.py` → `perception/pose_memory.py`·`perception/pose_registration.py`(`ml` 계층은 `core`만 import할 수 있어 `perception`에 둠, numpy만), 기능 `features/custom_pose`(칸 8개, 기본 바인딩 없음), 저장·엔진 연결 `desktop.CustomPoses`(`<data>/custom_poses/memory.json`, `bindings.json`, `demos/`), 화면은 학습 센터 › Pose Studio 맨 위 "내 동작 바로 등록".
- 흐름: 이름 → 등록 시작(제어 꺼짐, 시연 중 OS 입력 없음) → 준비 1.5초 · 자세 2초 · 쉬기 1초 × 5(손이 안 보이면 시간 멈춤) → 결과(다른 시연만으로 몇 번 알아봤는지, 쉬는 자세에서 잡히는지, 헷갈리는 자세) → 저장/버리기 → 명령 고르기(고르기 전에는 아무 일도 안 함).
- 새 동작은 Pose Studio에 저장된 표본의 자세들(알려진 자세)과 경쟁한다. 원본은 안내 녹화의 자세를 썼다. Pose Studio 표본이 없으면 등록 동작끼리만 경쟁하므로 다른 손 모양을 잘못 잡을 수 있다.
- 원본과 다른 점: 등록 동작이 잡히는 동안 커서를 멈추지 않는다(기능끼리 서로 멈출 수 없음). 원본의 신경망 임베딩 쪽(`memory.py` PrototypeMemory)은 옮기지 않았다(원본 문서: 새 동작 인식이 약해 자세 공간으로 바꿈).
- 고친 것: 등록 실패(시연이 짧거나 손이 안 보임) 때 입력이 꺼진 채 남지 않게 `CustomPoses.step`이 세션을 닫고 이유를 남긴다.
- 시험: `tests/unit/features/test_custom_pose.py` 9개(등록·승인·바인딩·재시작 후 유지·실제 엔진에서 `nav.back` 실행·실패 처리), `tests/unit/ui/test_unified_center.py` 1개(화면에서 등록 시작·취소, QML 오류 없음). 합성 손이며 실제 카메라로 등록해 보지 않았다.

## 아직 안 한 것 (3단계 남은 일)
2. `ml/store.py` 되돌리기.
3. 평소 사용 후보 수집(`segmenter`, `collector`) → MANUX 녹화 형식.
4. 사용 중 재학습(torch 부분) → worker 작업 종류.
5. 가상 손의 화면 손 그림과 손가락 사이 클릭(계약 변경 제안 필요).
6. 녹화 파일(`recordings/`)은 저장소 밖 + `tools/hub.py`로 공유(AGENTS 규칙), virtual-hand의 `config/gestures.json` 값은 PC별 조정값이라 옮기지 않음.
