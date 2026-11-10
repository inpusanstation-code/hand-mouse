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
