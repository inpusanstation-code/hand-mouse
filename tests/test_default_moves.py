"""The app's own moves can take another command (2026-11-11, "기본적으로 설정한 움직임도 커스텀 가능하게 … 학습센터 5 동작
연결 안에서 … 기본 동작 명령이라는 걸 알 수 있게 태그"): src/default_moves.py."""
import os

import pytest

from src import default_moves as dm


def test_a_held_move_left_at_its_default_does_what_it_always_did():
    h = dm.HoldRemap()
    scroll = {"action_type": "mouse_action", "action_value": "scroll_grab"}
    for i in range(10):
        assert h.step("vh_fist", True, scroll, i / 30, 5) == ("native", False)


def test_a_held_move_connected_to_a_command_runs_it_once_per_hold():
    h, t = dm.HoldRemap(), 0.0
    f5 = {"action_type": "hotkey", "action_value": "f5"}
    fired = []
    for _ in range(20):                                   # the fist held 20 frames: fires once, on the 5th
        mode, fire = h.step("vh_fist", True, f5, t, 5)
        assert mode == "command"
        fired.append(fire)
        t += 1 / 30
    assert fired.index(True) == 4 and fired.count(True) == 1
    for _ in range(3):                                    # the fist flickers away for 0.1 s: still the same hold
        h.step("vh_fist", False, None, t, 5)
        t += 1 / 30
    assert not any(h.step("vh_fist", True, f5, t + i / 30, 5)[1] for i in range(10))
    t += 1.0
    h.step("vh_fist", False, None, t, 5)                  # gone for longer than REARM: a new hold fires again
    assert [h.step("vh_fist", True, f5, t + .5 + i / 30, 5)[1] for i in range(5)][-1]


def test_a_held_move_switched_off_does_nothing():
    h = dm.HoldRemap()
    off = {"action_type": "none", "action_value": "none"}
    assert h.step("thumb_index", True, off, 0.0) == ("off", False)


def test_held_moves_only_take_their_own_continuous_action():
    from src.action_bindings import get_action_registry
    reg = get_action_registry()
    with pytest.raises(ValueError):
        reg.set_binding("vh_fist", "mouse_action", "drag_hold")
    with pytest.raises(ValueError):
        reg.set_binding("point_double", "mouse_action", "scroll_grab")
    assert reg.set_binding("vh_fist", "hotkey", "ctrl+w")["action_value"] == "ctrl+w"
    assert dm.plan("vh_fist", reg.resolve_effective_action("vh_fist", {})) == "command"
    assert reg.reset_binding("vh_fist")["action_value"] == "scroll_grab"
    assert dm.plan("point_right", reg.resolve_effective_action("point_right", {})) == "native"
    assert reg.get_binding("vh_fist")["track"] == "virtual"


def _board():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication
    from src.qt_dashboard import QtDashboard
    QApplication.instance() or QApplication([])
    QQuickStyle.setStyle("Basic")
    return QtDashboard(dry_run=True)


def test_the_list_tags_the_default_moves():
    from src.action_bindings import get_action_registry
    board = _board()
    board.use_index_pointer, board.virtual_hand_on, board.point_mode_on = False, True, True
    board.stateChanged.emit()
    rows = {r["key"]: r for r in board.bindingRows}
    assert rows["point_double"]["editable"] and rows["point_double"]["builtin"]
    assert rows["v_sign"]["builtin"] and not rows["v_sign"]["changed"]
    custom = [r for r in board.bindingRows if r["key"].startswith(("comp_", "user:", "seq_", "path_"))]
    assert all(not r["builtin"] for r in custom)
    get_action_registry().set_binding("vh_fist", "hotkey", "ctrl+w")
    board.stateChanged.emit()
    fist = {r["key"]: r for r in board.bindingRows}["vh_fist"]
    assert fist["changed"] and fist["default_badge"] == "잡기 스크롤" and "한 번 실행" in fist["how"]


def test_a_fist_connected_to_a_shortcut_sends_it_once_and_does_not_scroll(tmp_path):
    import time
    from src.action_bindings import get_action_registry
    from tests.test_virtual_hand import box_runtime, forcing
    get_action_registry().set_binding("vh_fist", "hotkey", "ctrl+w")
    rt = box_runtime(tmp_path)
    rt._step()
    forcing(rt, active_gesture="fist")
    sent = []
    rt.mouse._send_scroll = lambda v, h: sent.append(v)
    for _ in range(20):
        rt.tracker.dx += .02
        time.sleep(1 / 60)
        rt._step()
    assert rt.grip.kind is None and not sent                              # no page held, nothing scrolled
    assert sum("ctrl+w" in str(e).lower() for e in rt.mouse.event_log) == 1, rt.mouse.event_log
