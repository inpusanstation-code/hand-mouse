"""Mouse control off = simulation (2026-11-11): motion mode can be entered and its swipes are shown as what they would do, nothing
is sent; the dashboard says "시뮬레이션 중" in the top-right corner."""
import dataclasses
import os

import pytest

from src.motion_mode import MotionEvent


def _runtime(tmp_path, paused):
    from tests.test_qt_runtime import runtime
    rt = runtime(tmp_path)
    rt.ui = dataclasses.replace(rt.ui, use_index_pointer=False)
    rt.paused = paused
    rt._intent = lambda key, t0: True
    return rt


def _swipe(rt, action="back"):
    sent = []
    rt.mouse.send_motion_action = lambda a: sent.append(a) or True
    real = rt.motion.update

    def once(t0, lm, request="", blocked=False):
        rt.motion.update = real
        real(t0, lm, request=request, blocked=blocked)
        return MotionEvent("swipe", {}, action)
    rt.motion.update = once
    return sent


def test_with_the_control_off_motion_mode_runs_as_a_simulation(tmp_path):
    rt = _runtime(tmp_path, paused=True)
    rt.ui = dataclasses.replace(rt.ui, motion_request=1)          # the motion-mode button (or the thumbs-up)
    assert rt._motion(1.0, rt.ui, []) and rt.motion.active        # it used to be refused while paused
    assert "시뮬레이션" in rt._status
    sent = _swipe(rt)
    assert rt._motion(1.1, rt.ui, []) and sent == []              # nothing sent ...
    assert rt._motion_last == "시뮬레이션: 검지만 펴고 왼쪽 쓸기 → 단축키: Alt + ←"     # 2026-11-12: "back" = the index to the left     # ... but shown: the gesture and its command
    assert "실행 안 함" in rt._status


def test_with_the_control_on_the_swipe_is_sent(tmp_path):
    rt = _runtime(tmp_path, paused=False)
    rt.ui = dataclasses.replace(rt.ui, motion_request=1)
    assert rt._motion(1.0, rt.ui, [])
    sent = _swipe(rt)
    rt._motion(1.1, rt.ui, [])
    assert sent == ["back"] and not rt._motion_last.startswith("시뮬레이션")


def test_the_dashboard_shows_the_simulation_badge_only_while_the_control_is_off():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import numpy as np
    from PySide6.QtCore import QObject
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication
    from src.qt_dashboard import QtDashboard
    app = QApplication.instance() or QApplication([])
    QQuickStyle.setStyle("Basic")
    ui = QtDashboard(dry_run=True)
    root = ui.engine.rootObjects()[0]
    badge = root.findChild(QObject, "simBadge")
    frame = np.zeros((72, 128, 3), np.uint8)
    ui.stage_name = "main"
    ui.show(frame, True, True, "none", 30.0, 9.0)
    app.processEvents()
    assert ui.simulating and badge.property("visible")
    ui.show(frame, True, False, "none", 30.0, 9.0)
    app.processEvents()
    assert not ui.simulating and not badge.property("visible")
