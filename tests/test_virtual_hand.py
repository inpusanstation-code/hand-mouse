"""The hand drawn at the cursor: thumb tip at the cursor, fixed size, pinch lines, click label (no camera)."""
import math
import os
from types import SimpleNamespace

import pytest

from src.virtual_hand import SIZE_PX, view
from tests.test_online_data import hand_world


def landmarks(scale=1.0, shift=0.0):
    w = hand_world()
    return [SimpleNamespace(x=.5 + shift + p[0] * scale, y=.5 + p[1] * scale, z=p[2]) for p in w]


def test_the_thumb_tip_is_the_origin_and_the_size_is_fixed_whatever_the_distance():
    near, far = view(landmarks(1.0), 1280, 720), view(landmarks(.3, .2), 1280, 720)
    for v in (near, far):
        assert v["pts"][8:10] == [0.0, 0.0]
        wrist, knuckle = v["pts"][0:2], v["pts"][18:20]
        assert math.dist(wrist, knuckle) == pytest.approx(SIZE_PX, abs=.5)
    assert near["pts"] == pytest.approx(far["pts"], abs=1.0)


def test_pinch_lines_and_the_click_name_come_along():
    v = view(landmarks(), 1280, 720, guides=[("middle", "action")], action="left_click")
    assert v["guides"] == [["middle", "action"]] and v["action"] == "좌클릭"
    assert view(landmarks(), 1280, 720, action="move_cursor")["action"] == ""
    assert view(landmarks()[:20], 1280, 720) is None
    flat = [SimpleNamespace(x=.5, y=.5, z=0)] * 21
    assert view(flat, 1280, 720) is None


def test_the_runtime_sends_the_hand_only_while_one_is_seen(tmp_path):
    import dataclasses
    from tests.test_qt_runtime import runtime
    rt = runtime(tmp_path)
    rt.ui = dataclasses.replace(rt.ui, use_index_pointer=False)
    rt._step()
    assert rt._snap.virtual_hand and len(rt._snap.virtual_hand["pts"]) == 42
    rt.tracker.present = False
    rt._step()
    assert rt._snap.virtual_hand is None


def test_the_window_follows_the_cursor_and_hides_without_a_hand():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QObject
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication
    from src.qt_dashboard import QtDashboard
    app = QApplication.instance() or QApplication([])
    QQuickStyle.setStyle("Basic")
    board = QtDashboard(dry_run=True)
    win = board.engine.rootObjects()[0].findChild(QObject, "virtualHandWindow")
    board.set_virtual_hand(view(landmarks(), 1280, 720))
    app.processEvents()
    hand = board.virtualHand
    assert win.property("visible") and win.property("x") == hand["x"] - 320 and win.property("y") == hand["y"] - 320
    board.setVirtualHand(False)
    app.processEvents()
    assert not win.property("visible")
    board.setVirtualHand(True)
    board.set_virtual_hand(None)
    app.processEvents()
    assert not win.property("visible") and board.virtualHand == {}
