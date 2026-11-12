"""A hand about to be registered that another gesture answers to as well is said and asked about, never refused
(2026-11-12: "겹치는 동작을 등록하려고 하면 겹친다고 알려주는 기능" · "의사를 물어보게 해서 겹치는걸 원하면 겹치게"),
and a connected command's editor can show its hand shape once more for the taught model ("수정 메뉴에 mlp 추가 학습")."""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from src import gesture_overlap


class Registry:
    def __init__(self, off=(), composites=None):
        self.off = set(off)
        self.composite_gestures = composites or {}

    def get_binding(self, key):
        return {"enabled": key not in self.off}


COMPS = {"comp_open_hand_hold": {"name": "손 펴기 유지", "base_posture": "open_hand", "enabled": True},
         "comp_index_point_hold": {"name": "검지만 펴기 유지", "base_posture": "index_point", "enabled": True}}


def test_a_look_read_as_the_rock_sign_overlaps_the_close_window_sign():
    # the morning's example: saved as "index only", read as the rock sign in 43 of its 54 frames
    found = gesture_overlap.find({"rock_sign": .8, "thumb_middle": .2}, "index_point", Registry(composites=COMPS))
    assert [(f["posture"], f["does"], f["same"]) for f in found] == [("rock_sign", "창 닫기", False)]
    text = gesture_overlap.words(found, "검지만 펴기")
    assert "창 닫기" in text and "80%" in text and "함께 실행" in text
    assert gesture_overlap.find({"rock_sign": .8}, "index_point", Registry(off=["rock_sign"])) == []     # the sign is off
    assert gesture_overlap.find({"rock_sign": .1, "index_point": .9}, "index_point", Registry()) == []   # a few frames only
    assert gesture_overlap.words([]) == ""


def test_a_gesture_of_another_shape_and_a_sign_of_the_same_shape_are_listed():
    found = gesture_overlap.find({"open_hand": .4, "index_point": .6}, "custom_9", Registry(composites=COMPS))
    assert {f["name"] for f in found} == {"손 펴기 유지", "검지만 펴기 유지"}
    # the shape's own gestures are not an overlap (they differ by their movement), its own sign is
    assert gesture_overlap.find({"index_point": 1.0}, "index_point", Registry(composites=COMPS)) == []
    same = gesture_overlap.find({}, "rock_sign", Registry())
    assert same and same[0]["same"] and "같은 손 모양" in gesture_overlap.words(same, "락 사인")


def test_an_overlapping_new_gesture_of_the_ai_is_left_unticked_with_the_reason():
    rows = [{"ok": True, "checked": True, "risky": False, "warning": "", "new_posture": "rock_sign", "new_trigger": "hold"},
            {"ok": True, "checked": True, "risky": False, "warning": "", "new_posture": "rock_sign", "new_trigger": "motion_left"},
            {"ok": True, "checked": True, "risky": False, "warning": "", "new_posture": "", "new_trigger": ""}]
    gesture_overlap.mark_proposals(rows, None, Registry())
    assert rows[0]["checked"] is False and rows[0]["risky"] and "창 닫기" in rows[0]["warning"] and "체크" in rows[0]["warning"]
    assert rows[1]["checked"] and rows[2]["checked"]                      # motion mode only / an existing gesture: untouched


@pytest.fixture
def board():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication
    from src.qt_dashboard import QtDashboard
    app = QApplication.instance() or QApplication([])
    QQuickStyle.setStyle("Basic")
    ui = QtDashboard(dry_run=True)
    assert ui.engine.rootObjects(), "dashboard.qml did not load"
    yield ui
    app.processEvents()


def test_saving_an_overlapping_look_asks_first_and_saves_when_the_person_wants_it(board):
    asked = []
    board.overlapAsk.connect(lambda kind, what, words: asked.append((kind, what, words)))
    board.pose_probe_view = {"state": "done", "posture": "rock_sign", "name": "락 사인", "share": .8,
                             "seen": {"rock_sign": .8, "thumb_middle": .2}}
    board.online_commands.clear()
    board.poseTeachSave("index_point")
    assert not board.online_commands and len(asked) == 1                  # nothing saved: asked
    assert asked[0][:2] == ("save", "index_point") and "창 닫기" in asked[0][2] and "그래도 저장" in asked[0][2]
    assert "창 닫기" in board.llmContext["overlap"]                        # ... and said under the look
    board.overlapConfirmed("save", "index_point")                         # [그래도 저장]
    assert list(board.online_commands) == [("pose_teach_save", "index_point")]
    # a look that nothing else answers to is saved without a question
    board.online_commands.clear()
    board.pose_probe_view = {"state": "done", "posture": "index_point", "name": "검지만 펴기", "share": 1.0,
                             "seen": {"index_point": 1.0}}
    board.poseTeachSave("index_point")
    assert list(board.online_commands) == [("pose_teach_save", "index_point")] and len(asked) == 1
    assert board.llmContext["overlap"] == ""


def test_the_editor_of_a_connected_command_starts_one_more_look_at_its_hand_shape(board):
    board.online_commands.clear()
    board.poseTeachMore("no_such_shape")
    assert not board.online_commands
    board.poseTeachMore("index_point")
    assert board.teach_focus == "index_point" and board.teach_adding
    assert list(board.online_commands) == [("pose_probe",)]
    assert board.llmContext["teach"]["focus"] == "index_point" and "counts" in board.llmContext["teach"]
    board.clearPoseProbe()


def test_the_rows_of_the_list_carry_the_hand_shape_to_teach(tmp_path):
    import json
    from src.llm_binding import History
    path = tmp_path / "ai.json"
    path.write_text(json.dumps([{"gesture_key": "comp_index_point_hold", "gesture_name": "검지만 펴기 유지",
                                 "action_type": "hotkey", "action_value": "f5", "enabled": True},
                                {"gesture_key": "thumb_pinky", "gesture_name": "엄지+새끼", "action_type": "hotkey",
                                 "action_value": "f5", "enabled": True}]), encoding="utf-8")
    registry = SimpleNamespace(composite_gestures={"comp_index_point_hold": {"base_posture": "index_point", "trigger_type": "hold",
                                                                              "hold_seconds": .4}}, custom_motions={})
    import src.llm_binding as lb
    old = lb.still_in_force
    lb.still_in_force = lambda *a, **k: True
    try:
        rows = {r["gesture_key"]: r for r in History(path).rows(registry)}
    finally:
        lb.still_in_force = old
    assert rows["comp_index_point_hold"]["teach_posture"] == "index_point" and rows["thumb_pinky"]["teach_posture"] == ""


def test_the_back_of_the_hand_and_the_palm_down_hand_are_said_to_mix():
    """2026-11-12: the two differ only by a tilt (pose_probe.faced); with a gesture on each they are read as each
    other now and then, also when this one look happened to read as one of them only."""
    comps = {"comp_back": {"name": "손등 유지", "base_posture": "open_hand_back", "enabled": True}}
    found = gesture_overlap.find({"open_hand_down": 1.0}, "open_hand_down", Registry(composites=comps))
    assert [(f["name"], f.get("twin")) for f in found] == [("손등 유지", True)]
    assert "기울기만 달라" in gesture_overlap.words(found, "손바닥을 바닥으로 손 펴기")
    assert gesture_overlap.find({"open_hand_down": 1.0}, "open_hand_down", Registry(composites=COMPS)) == []     # no gesture on the back
    assert gesture_overlap.find({"open_hand_up": 1.0}, "open_hand_up", Registry(composites=comps)) == []


def test_the_open_hand_in_any_facing_offers_no_more_teaching(tmp_path):
    import json
    import src.llm_binding as lb
    path = tmp_path / "ai.json"
    path.write_text(json.dumps([{"gesture_key": "comp_down", "gesture_name": "바닥 유지", "action_type": "hotkey",
                                 "action_value": "f5", "enabled": True},
                                {"gesture_key": "comp_point", "gesture_name": "검지 유지", "action_type": "hotkey",
                                 "action_value": "f5", "enabled": True}]), encoding="utf-8")
    registry = SimpleNamespace(composite_gestures={"comp_down": {"base_posture": "open_hand_down", "trigger_type": "hold"},
                                                   "comp_point": {"base_posture": "index_point", "trigger_type": "hold"}},
                               custom_motions={})
    old = lb.still_in_force
    lb.still_in_force = lambda *a, **k: True
    try:
        rows = {r["gesture_key"]: r for r in lb.History(path).rows(registry)}
    finally:
        lb.still_in_force = old
    assert rows["comp_down"]["teach_posture"] == "" and rows["comp_point"]["teach_posture"] == "index_point"
