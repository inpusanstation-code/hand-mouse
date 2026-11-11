"""The words beside the hand drawn on the screen (2026-11-11).

"마우스 제어상태가 아닌 상태에서 가상손에서 보면서 검수할 수 있게 명령신호 정보들이 다 나오도록 해줘. 그리고 이렇게
글자로 신호 정보 나오는 것도 설정에서 켜고 끌 수 있게 만들어줘": with the control off the hand's signals are named and
nothing is run; the words can be switched off."""
import dataclasses
import os

import pytest

from tests.test_virtual_hand import box_runtime, pinch_hand


def _run(rt, seconds):
    """The runtime's clock is the real one: step until that much time has passed."""
    import time
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        rt._step()


def _click(rt):
    """A short thumb + index pinch. Returns every note / action shown on the way."""
    seen = []
    opened = pinch_hand(rt)
    for hand in (None, None, opened, None):
        if hand is not None:
            rt.tracker.hand[:] = hand
        rt._step()
        vh = rt._virtual_hand or {}
        seen.append((vh.get("action", ""), vh.get("note", ""), vh.get("text")))
    return seen


def test_with_the_control_off_a_click_is_named_on_the_drawn_hand_and_not_made(tmp_path):
    rt = box_runtime(tmp_path)
    rt._step()
    rt.paused = True
    rt._step()
    seen = _click(rt)
    assert "left_click" not in rt.mouse.event_log                    # nothing happened ...
    notes = [n for _, n, _ in seen]
    assert any("클릭" in n for n in notes), notes                     # ... but the signal was named
    for _ in range(3):                                               # and it stays readable for a moment
        rt._step()
    assert "클릭" in rt._virtual_hand["note"]
    _run(rt, rt.INSPECT_HOLD + .2)                                   # later: the hand shape the app sees (or nothing)
    assert "클릭" not in rt._virtual_hand.get("note", "")
    # a gesture the person connected: its name and the command it would run, without running it
    from src.action_bindings import get_action_registry
    from src.pose_probe import hand_posture
    shape = hand_posture(rt.tracker.hand, rt.mouse.frame_aspect)
    if shape:
        get_action_registry().register_composite_gesture("", "검수용 유지", shape, "hold", "hotkey", "f5", hold_seconds=.3)
        before = list(rt.mouse.event_log)
        _run(rt, .8)
        assert "검수용 유지" in rt._virtual_hand["note"] and "F5" in rt._virtual_hand["note"].upper()
        assert rt.mouse.event_log == before
    # the control on again: no notes, the click is made
    rt.paused = False
    _run(rt, .2)
    assert "note" not in rt._virtual_hand
    _click(rt)
    assert "left_click" in rt.mouse.event_log


def test_the_words_can_be_switched_off(tmp_path):
    rt = box_runtime(tmp_path)
    rt._step()
    assert rt._virtual_hand["text"] is True
    rt.ui = dataclasses.replace(rt.ui, signal_text=False)
    rt._step()
    assert rt._virtual_hand["text"] is False                         # the window draws no words (the hand itself stays)


def test_the_setting_is_a_button_in_the_settings_window_and_is_remembered():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QObject
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication
    from src.qt_dashboard import QtDashboard
    app = QApplication.instance() or QApplication([])
    QQuickStyle.setStyle("Basic")
    board = QtDashboard(dry_run=True)
    root = board.engine.rootObjects()[0]
    was = board.signalTextOn
    try:
        button = root.findChild(QObject, "signalTextButton")
        assert button is not None
        board.setSignalText(False)
        assert board.signalTextOn is False and board.preferences.value("signalText", True, type=bool) is False
        assert "꺼짐" in button.property("text")
        board.setSignalText(True)
        assert "켜짐" in button.property("text")
    finally:
        board.setSignalText(was)
    app.processEvents()
