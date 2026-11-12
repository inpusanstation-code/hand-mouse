"""Training center (2026-11-11 request): its options are kept per profile, and the "동작 연결" list shows what each hand
signal runs in the hand mode in use (it used to list palm mode's recording catalogue whatever the mode was)."""
import os

import pytest


_ALIVE = []


def _board():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication
    from src.qt_dashboard import QtDashboard
    QApplication.instance() or QApplication([])
    QQuickStyle.setStyle("Basic")
    board = QtDashboard(dry_run=True)
    _ALIVE.append(board)       # kept to the end: a dashboard garbage-collected while a later test's QML runs crashes Qt on Windows
    return board


def _rows(board, **mode):
    for name, value in mode.items():
        setattr(board, name, value)
    board.stateChanged.emit()
    return {r["key"]: r for r in board.bindingRows}


def test_the_hand_on_the_screen_has_its_own_bindings():
    """Thumb + little finger -> Ctrl+W (a palm-mode pinch) closed a tab from the virtual hand's switcher shape, because
    the virtual hand borrowed palm mode's binding keys."""
    from src.action_bindings import PALM_ACTION_KEYS, VIRTUAL_ACTION_KEYS, get_action_registry
    reg = get_action_registry()
    reg.set_binding("thumb_pinky", "hotkey", "ctrl+w")
    assert VIRTUAL_ACTION_KEYS["task_switcher"] != PALM_ACTION_KEYS["task_switcher"]
    resolved = reg.resolve_effective_action(VIRTUAL_ACTION_KEYS["task_switcher"], {})
    assert (resolved["action_type"], resolved["action_value"]) == ("mouse_action", "task_switcher")
    for action, key in VIRTUAL_ACTION_KEYS.items():
        assert reg.get_binding(key)["action_value"] == action


def test_the_list_follows_the_hand_mode_in_use():
    board = _board()
    virtual = _rows(board, use_index_pointer=False, virtual_hand_on=True)
    assert board.handModeName == "가상 손 모드"
    assert virtual["vh_pinch"]["active"] and virtual["vh_pinch"]["editable"]
    assert not virtual["thumb_middle"]["active"] and "손바닥 모드" in virtual["thumb_middle"]["why"]
    # 2026-11-11 ("기본적으로 설정한 움직임도 커스텀 가능하게"): the fist scroll takes another command now, tagged as a default
    assert virtual["vh_fist"]["editable"] and virtual["vh_fist"]["builtin"] and virtual["vh_fist"]["default_badge"] == "잡기 스크롤"
    assert not virtual["fixed:vh_move"]["editable"] and virtual["fixed:vh_move"]["builtin"]     # moving the cursor stays
    assert "thumb_index" not in virtual                             # palm mode's grab scroll is not offered here
    palm = _rows(board, use_index_pointer=False, virtual_hand_on=False)
    assert palm["thumb_middle"]["active"] and not palm["vh_pinch"]["active"]
    assert palm["thumb_index"]["editable"] and palm["thumb_index_middle"]["editable"] and palm["thumb_middle_drag"]["editable"]
    index = _rows(board, use_index_pointer=True)
    assert not index["v_sign"]["active"] and index["thumbs_up"]["active"]      # motion mode works with the index pointer
    sections = [r["section"] for r in board.bindingRows]
    unused = [i for i, s in enumerate(sections) if s == "지금 방식에서는 쓰이지 않음"]
    assert unused and unused == list(range(unused[0], len(sections)))           # one block, at the end


def test_a_changed_binding_shows_in_the_list_at_once():
    board = _board()
    _rows(board, use_index_pointer=False, virtual_hand_on=True)
    seen = []
    board.bindingRowsChanged.connect(lambda: seen.append(1))
    from src.action_bindings import get_action_registry
    reg = get_action_registry()                  # (saveGestureBinding also re-reads the recordings in a thread)
    reg.set_binding("vh_switch", "hotkey", "win+tab")
    board.stateChanged.emit()
    row = {r["key"]: r for r in board.bindingRows}["vh_switch"]
    assert seen and row["changed"] and row["action_value"] == "win+tab"
    assert row["same_action_elsewhere"] == []
    reg.set_binding("vh_switch", "hotkey", "win+tab", enabled=False)
    board.stateChanged.emit()
    assert {r["key"]: r for r in board.bindingRows}["vh_switch"]["shortcut_badge"] == "꺼짐"
    # the same click in the other hand mode is not "the same command on another gesture"
    assert reg.others_with_action("vh_pinch", "mouse_action", "left_click") == []


def test_training_center_options_are_kept_per_profile():
    board = _board()
    board.profile = None
    board.setCenterPref("centerTab", "bindings")
    board.setCenterPref("sim.playSpeed", 2.0)
    board.setCenterPref("sim.showArmPose", False)
    board.setTrainingMode("thorough")
    board.profile = "민수"
    assert board.centerPref("centerTab", "gestures") == "bindings"           # a profile that did not touch it: the default state
    assert board.centerPref("sim.showArmPose", True) is False
    board.setCenterPref("centerTab", "recordings")
    board.setTrainingMode("fast")
    board.profile = None
    assert board.centerPref("centerTab", "gestures") == "bindings"
    assert board.centerPref("sim.playSpeed", 1.0) == 2.0
    assert board.centerPref("sim.showArmPose", True) is False
    assert board.centerPref("sim.playSpeed", "x") == "x"                     # a value of another kind: the default
    told = []
    board.centerPrefsChanged.connect(lambda: told.append(1))
    board._apply_center_prefs()                                              # what picking the profile does
    assert board.training_mode == "thorough" and told
    board.profile = "민수"
    board._apply_center_prefs()
    assert board.training_mode == "fast"


def test_the_center_opens_on_the_tab_left_open():
    from PySide6.QtCore import QObject
    board = _board()
    board.profile = None
    board.setCenterPref("centerTab", "bindings")
    board.setCenterPref("bindingsSubTab", "composites")
    board.centerPrefsChanged.emit()
    popup = board.window.findChild(QObject, "trainingCenterPopup")
    assert popup.property("centerTab") == "bindings" and popup.property("bindingsSubTab") == "composites"
    popup.setProperty("centerTab", "recordings")                             # the person picks another tab: saved
    assert board.centerPref("centerTab", "") == "recordings"


def test_each_profile_has_its_own_bindings():
    """2026-11-11, the person's choice ("프로필별로"): the gesture -> command bindings go with the profile."""
    import src.action_bindings as ab
    common = ab.get_action_registry()
    common.set_binding("thumb_pinky", "hotkey", "ctrl+w")
    mine = ab.use_binding_profile("민수")
    assert mine.path != common.path and mine.path.parent.name == "bindings"
    assert mine.get_binding("thumb_pinky")["action_value"] == "ctrl+w"        # untouched: the default state
    assert not mine.path.exists()                                              # ... and nothing is written for it
    mine.set_binding("thumb_pinky", "hotkey", "alt+f4")
    mine.register_composite_gesture("", "내 동작", "fist", "hold", "hotkey", "f5")
    import json
    saved = json.loads(mine.path.read_text(encoding="utf-8"))                  # only what the profile changed
    assert set(saved["bindings"]) == {"thumb_pinky", "comp_fist_hold"} and list(saved["composite_gestures"]) == ["comp_fist_hold"]
    # the default state changes later (in code or the shared file): the profile follows where it did not touch
    ab.use_binding_profile(None).set_binding("thumb_ring", "hotkey", "ctrl+c")
    mine = ab.use_binding_profile("민수")
    assert mine.get_binding("thumb_ring")["action_value"] == "ctrl+c"
    assert mine.get_binding("thumb_pinky")["action_value"] == "alt+f4"
    assert mine.reset_binding("thumb_pinky")["action_value"] == "ctrl+w"       # back to the default state
    mine.set_binding("thumb_pinky", "hotkey", "alt+f4")
    assert ab.use_binding_profile("민수") is mine                              # asked again: nothing changes
    back = ab.use_binding_profile(None)
    assert back.get_binding("thumb_pinky")["action_value"] == "ctrl+w" and not back.composite_gestures
    again = ab.use_binding_profile("민수")
    assert again.get_binding("thumb_pinky")["action_value"] == "alt+f4" and len(again.composite_gestures) == 1
    assert ab.use_binding_profile("../x") is again                             # not a profile name: stays where it is


def test_picking_a_profile_on_the_dashboard_switches_the_list():
    import src.action_bindings as ab
    board = _board()
    board.profile = None
    board._use_profile_bindings()
    ab.get_action_registry().set_binding("vh_switch", "hotkey", "win+tab")
    board.profile = "민수"
    board._use_profile_bindings()
    ab.get_action_registry().set_binding("vh_switch", "hotkey", "ctrl+w")
    rows = _rows(board, use_index_pointer=False, virtual_hand_on=True)
    assert rows["vh_switch"]["action_value"] == "ctrl+w" and "민수" in board.bindingProfileNote
    board.profile = None
    board._use_profile_bindings()
    assert _rows(board)["vh_switch"]["action_value"] == "win+tab"


def test_profiles_are_made_renamed_reset_exported_imported_and_deleted_on_the_dashboard(tmp_path, monkeypatch):
    """2026-11-11 request: the person makes, changes and deletes profiles; what a profile changed can be exported and
    imported; no profile, or a profile nothing was changed in, is the app's default state."""
    import json
    import src.action_bindings as ab
    import src.gesture_engine as ge
    from src import profiles
    from src.gesture_engine import GestureEngine
    board = _board()
    board.stage_name = "main"
    board.profile = None
    board._reload_profile()
    cfg_dir = ge.DEFAULT_CONFIG_PATH.parent
    default_dwell = board.point_settings["dwell"]
    assert board.createProfile("민수") and board.profile == "민수" and profiles.get_active(cfg_dir) == "민수"
    assert not board.createProfile("민수") and not board.createProfile("../x")
    row = {r["name"]: r for r in board.profileRows}["민수"]
    assert row["active"] and row["changed"] == 0 and "기본 상태와 같음" in row["note"]
    assert board.point_settings["dwell"] == default_dwell                         # untouched = the default state
    # the person changes things with the profile on: a screen option, a binding, an engine setting
    board.setPointSetting("dwell", 2.0)
    ab.get_action_registry().set_binding("vh_switch", "hotkey", "win+tab")
    engine = GestureEngine()
    assert engine.profile_name == "민수"
    engine.config["smoothing"] = 0.11
    engine.save_config()
    assert {r["name"]: r for r in board.profileRows}["민수"]["changed"] == 3
    # ... none of it reaches the default state
    assert board.selectProfile("") and board.profile is None
    assert board.point_settings["dwell"] == default_dwell
    assert ab.get_action_registry().get_binding("vh_switch")["action_value"] == "task_switcher"
    assert GestureEngine().config["smoothing"] != 0.11
    assert board.selectProfile("민수") and board.point_settings["dwell"] == 2.0
    assert board.renameProfile("민수", "집 PC") and board.profile == "집 PC"
    assert board.point_settings["dwell"] == 2.0 and ab.get_action_registry().get_binding("vh_switch")["action_value"] == "win+tab"
    out = tmp_path / "out" / "p.json"
    assert board.exportProfileTo("집 PC", str(out))
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["profile"]["updates"] == {"smoothing": 0.11} and list(doc["bindings"]["bindings"]) == ["vh_switch"]
    assert "pointModeSettings" in doc["ui"]
    assert board.resetProfile("집 PC") and board.point_settings["dwell"] == default_dwell
    assert ab.get_action_registry().get_binding("vh_switch")["action_value"] == "task_switcher"
    assert {r["name"]: r for r in board.profileRows}["집 PC"]["changed"] == 0
    assert board.importProfileFrom(str(out))                                       # the name is taken: numbered
    assert "집 PC 2" in profiles.list_profiles(cfg_dir) and board.profile == "집 PC"
    assert board.selectProfile("집 PC 2") and board.point_settings["dwell"] == 2.0
    assert ab.get_action_registry().get_binding("vh_switch")["action_value"] == "win+tab"
    assert GestureEngine().config["smoothing"] == 0.11
    assert not board.importProfileFrom(str(tmp_path / "missing.json"))
    assert board.deleteProfile("집 PC 2") and board.profile is None                # the one in use: back to none first
    assert profiles.list_profiles(cfg_dir) == ["집 PC"] and board.point_settings["dwell"] == default_dwell
    assert board._profile_groups("집 PC 2") == {"ui": {}, "center": {}}


def test_the_profile_window_lists_the_profiles():
    from PySide6.QtCore import QObject
    board = _board()
    board.stage_name = "main"
    board.profile = None
    assert board.createProfile("민수")
    window = board.window.findChild(QObject, "profileManager")
    window.setProperty("visible", True)
    board.application.processEvents()
    assert window.property("visible") and [r["name"] for r in board.profileRows] == ["", "민수"]
    assert board.window.findChild(QObject, "profileButton") is not None
    window.setProperty("visible", False)
    assert board.deleteProfile("민수")


def test_a_command_a_signal_cannot_take_is_said_on_the_screen_and_a_valid_one_shows_in_the_list():
    """2026-11-12: the person picked the drag for the pointing click and pressed [저장]; it was refused (a pointing
    click takes one-shot commands only) and the screen said nothing - the list just kept "마우스 더블클릭"."""
    from PySide6.QtCore import QObject
    import src.action_bindings as ab
    board = _board()
    board.profile = None
    board._use_profile_bindings()
    assert "한 번 실행되는 명령" in board.bindingRefusal("point_double", "mouse_action", "scroll_grab")
    assert board.bindingRefusal("point_double", "mouse_action", "drag_hold") == ""      # 2026-11-12: pointing may drag
    assert board.bindingRefusal("point_double", "mouse_action", "right_click") == ""
    assert board.bindingRefusal("vh_pinch", "mouse_action", "drag_hold") == ""          # an ordinary signal takes anything
    tab = board.window.findChild(QObject, "bindingsTabRoot")
    popup = board.window.findChild(QObject, "trainingCenterPopup")
    _rows(board, use_index_pointer=False, virtual_hand_on=True, point_mode_on=True)
    popup.setProperty("selectedBindingKey", "point_double")
    board.application.processEvents()
    tab.setProperty("editActionType", "mouse_action")
    tab.setProperty("editActionValue", "scroll_grab")
    board.application.processEvents()
    assert "연결할 수 없어요" in tab.property("refusal") or "한 번 실행되는" in tab.property("refusal")
    note = board.window.findChild(QObject, "bindingSaveNote")
    assert "연결할 수 없어요" in note.property("text")
    tab.setProperty("editActionValue", "right_click")
    board.application.processEvents()
    assert tab.property("refusal") == "" and tab.property("unsaved") and "아직 저장되지 않았어요" in note.property("text")
    ab.get_action_registry().set_binding("point_double", "mouse_action", "right_click")   # what [저장] does
    board.stateChanged.emit()
    row = {r["key"]: r for r in board.bindingRows}["point_double"]
    assert "우클릭" in row["shortcut_badge"] and row["changed"]
