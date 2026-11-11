"""A finished learning round in words (2026-11-11).

The person, on a left panel filled with one paragraph per gesture and keys like 'left_click:thumb_index':
"이렇게 나오는 이유가 뭐임. 유저가 꼭 알아야 하는 메세지면 저렇게 인터페이스에 나오게 하지말고 알림 형식으로 나오게 처리해".
Now: one short line (for a few minutes), and a notice only for what changes something."""
import os
import time
from types import SimpleNamespace

import pytest

from src.qt_dashboard import QtDashboard

WAIT = {"status": "waiting", "reason": "one_day", "uses": 54}
THE_ROUND = {"status": "rejected", "problems": [], "verifiers": {
    "comp_open_hand_hold": WAIT, "left_click:thumb_index": {**WAIT, "uses": 220},
    "right_click:thumb_index_middle": {**WAIT, "uses": 91}, "comp_custom_2_hold": {**WAIT, "uses": 21}}}


def _summary(state, auto=True):
    board = SimpleNamespace(learn_auto=auto, _gesture_name=QtDashboard._gesture_name)
    return QtDashboard._learn_summary(board, state)


def test_the_round_of_the_report_is_one_line_and_no_notice():
    line, notice = _summary(THE_ROUND)
    assert notice == ""                                              # nothing changed for the person: no notice
    assert "4개" in line and "다른 날" in line and len(line) < 90     # (it was ~520 characters)
    assert "left_click" not in line and "thumb_index" not in line and "하루치" not in line


def test_what_changes_something_is_a_notice_with_the_gestures_own_names():
    # a click says which click it is: the mode, the fingers and the kind (2026-11-11: "어떤 모드의, 어떤 식의 좌클릭인지")
    assert QtDashboard._gesture_name("left_click:thumb_index") == "좌클릭 · 가상 손 (엄지+검지)"
    assert QtDashboard._gesture_name("left_click:thumb_index:double") == "좌클릭 · 가상 손 (엄지+검지) · 더블클릭의 두 번째"
    assert QtDashboard._gesture_name("left_click:thumb_middle") == "좌클릭 · 손바닥 모드 (엄지+중지)"
    assert QtDashboard._gesture_name("right_click:thumb_index_middle") == "우클릭 · 가상 손 (엄지+검지+중지)"
    line, notice = _summary({"status": "nothing", "verifiers": {
        "left_click:thumb_index": {"status": "saved", "recall": 1.0, "held": 6},
        "right_click:thumb_index_middle": {"status": "rejected", "reason": "misses_uses"}, "comp_x": WAIT}})
    assert "'좌클릭 · 가상 손 (엄지+검지)' 확인 모델을 만들었어요" in notice
    assert "'우클릭 · 가상 손 (엄지+검지+중지)' 확인 모델은" in notice and "통과하지 못해" in notice
    assert "다른 날" not in notice and "1개는 다른 날" in line          # the waiting one is counted in the line only
    assert _summary({"status": "promoted"})[1] == "자동 학습으로 만든 새 모델을 반영했어요."
    assert _summary({"status": "promoted"}, auto=False)[1] == "새 모델을 반영했어요."
    assert _summary({"status": "rolled_back", "message": "이전 모델로 되돌렸어요."})[1] == "이전 모델로 되돌렸어요."
    line, notice = _summary({"status": "nothing"})
    assert notice == "" and "정정·확인 데이터가 없어요" in line


def test_the_panel_line_goes_back_to_the_count_after_a_while_and_the_notice_pops_up():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QObject
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    QQuickStyle.setStyle("Basic")
    board = QtDashboard(dry_run=True)
    root = board.engine.rootObjects()[0]
    board.learn_summary = {"samples": 3, "last": None}
    board.learn_message, board.learn_banner_until = "새 모델을 반영했어요.", time.time() + 300
    assert board.learnText == "새 모델을 반영했어요."
    board.learn_banner_until = time.time() - 1                        # a few minutes later
    assert board.learnText.startswith("정정·확인한 데이터 3개")
    toast = root.findChild(QObject, "toast")
    assert toast is not None and not toast.property("visible")
    board.notify("'좌클릭' 확인 모델을 만들었어요.")
    QTest.qWait(80)
    assert toast.property("visible") and "좌클릭" in root.findChild(QObject, "toastText").property("text")
    toast.close()
    app.processEvents()
