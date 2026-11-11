"""The [손 모양·움직임 보여주기] row on the screen (2026-11-11): the look replayed like a GIF, "not in the list" said so,
and a name box that makes a new hand shape."""
import os

import numpy as np
import pytest


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


def _wait(ms):
    from PySide6.QtTest import QTest
    QTest.qWait(ms)


def test_the_look_is_replayed_and_an_unlisted_shape_gets_a_name(board):
    from PySide6.QtCore import QObject
    from src import custom_postures
    from src.action_bindings import POSTURE_NAMES_KO
    root = board.engine.rootObjects()[0]
    frames = [np.full((160, 160, 3), 10 * i, np.uint8) for i in range(12)]
    board.pose_probe_view = {"state": "done", "posture": "", "name": "목록에 없는 손 모양", "unknown": True, "share": 0.0,
                             "approx": False, "everyday": False, "gesture_key": ""}
    board._set_probe_shot((1, frames[6], frames))
    ctx = board.llmContext
    assert ctx["shot"] == "image://probeshot/1" and ctx["shotFrames"] == 12
    # the provider serves each picture of the look, and the still one for a bare id
    assert board.probe_shot.requestImage("1/3", None, None).pixelColor(0, 0).red() == 30
    assert board.probe_shot.requestImage("1", None, None).pixelColor(0, 0).red() == 60
    assert board.probe_shot.requestImage("1/99", None, None).pixelColor(0, 0).red() == 60

    root.findChild(QObject, "llmDialog").setProperty("visible", True)
    _wait(50)
    shot = root.findChild(QObject, "poseProbeShot")
    assert shot is not None and shot.property("visible") and shot.property("frames") == 12
    seen = set()
    for _ in range(8):
        _wait(70)
        seen.add(shot.property("frame"))
    assert len(seen) >= 3, seen                                    # it plays

    # no listed shape: no choice is preselected, the name box makes a new shape and saves the look as its example
    assert root.findChild(QObject, "poseTeachChoice").property("currentIndex") == -1
    assert root.findChild(QObject, "poseTeachNewName") is not None
    board.online_commands.clear()
    try:
        board.poseTeachSaveNew("주먹 쥐기")                          # a listed name: refused, nothing saved
        assert board.teach_view["state"] == "error" and not board.online_commands
        board.poseTeachSaveNew("여우 손")
        key = next(k for k, v in custom_postures.load().items() if v == "여우 손")
        assert ("pose_teach_save", key) in list(board.online_commands)
        assert POSTURE_NAMES_KO[key] == "여우 손" and {"key": key, "name": "여우 손"} in board.postureChoices
        # from now on the screen is about this shape: its steps, a one-press "add this look", "show once more"
        teach = board.llmContext["teach"]
        assert teach["focus"] == key and "여우 손" in teach["text"] and "③ 견본" in teach["steps"]
        _wait(50)
        assert "여우 손" in root.findChild(QObject, "poseTeachGuide").property("text")
        assert root.findChild(QObject, "poseTeachAgain").property("visible")
        add = root.findChild(QObject, "poseTeachAddFocus")
        assert add.property("visible") and "여우 손" in add.property("text")
        assert root.findChild(QObject, "poseTeachTrain").property("text") == "🧠 '여우 손' 학습"
        # the runtime saved the example (the result says "taught"): with two examples the training starts by itself
        import src.posture_teach as pt
        started = []
        board.poseTeachTrain = lambda: started.append(1)
        pt.save_example(key, [[[0.0, 0.0, 0.0]] * 21])
        board._after_example_saved(key)
        assert not started                                             # one example: show it once more first
        pt.save_example(key, [[[0.0, 0.0, 0.0]] * 21])
        board._after_example_saved(key)
        assert started == [1]
    finally:
        custom_postures.PATH.unlink(missing_ok=True)
        custom_postures.register()

    # a training of the shape being taught that passes the check is put to use by itself (no [적용] to forget)
    import src.posture_teach as pt
    board.teach_focus = "v_sign_down"
    pt.CANDIDATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = {"examples": {"v_sign_down": 3}, "recognition": {"v_sign_down": 1.0}, "false_rate": 0.0, "can_apply": True}
    pt.CANDIDATE_PATH.write_text('{"report": ' + __import__("json").dumps(report) + '}', encoding="utf-8")
    board._finish_pose_teach(report, "")
    assert pt.MODEL_PATH.is_file() and not pt.CANDIDATE_PATH.is_file() and board.teach_view["state"] == "applied"
    assert "적용됨" in board.llmContext["teach"]["text"] and "⑤ 적용 ✓" in board.llmContext["teach"]["steps"]
    # ... one that fails the check is not
    pt.MODEL_PATH.unlink()
    pt.CANDIDATE_PATH.write_text("{}", encoding="utf-8")
    board._finish_pose_teach({**report, "false_rate": .05, "can_apply": False}, "")
    assert not pt.MODEL_PATH.is_file() and board.teach_view["state"] == "ready"
    assert "실행되지 않아요" in board.llmContext["teach"]["text"]
    pt.CANDIDATE_PATH.unlink()
    board.teach_view = {"state": "", "text": ""}

    # [한 번 더 보여주기]: the look is one more example of the shape being taught - no "new hand shape" form
    board.teach_focus = "v_sign_down"
    board.online_commands.clear()
    board.poseTeachAgain()
    assert board.llmContext["teach"]["adding"] and ("pose_probe",) in list(board.online_commands)
    unknown = {"state": "done", "posture": "", "name": "목록에 없는 손 모양", "unknown": True, "gesture_key": ""}

    snap = board._set_pose_probe         # what apply_snapshot hands the runtime's view to

    # the runtime has not picked the button press up yet: its snapshots still carry the previous look, which was saved
    # as an example. That is not this look's result (it used to switch the adding off and train again)
    started = []
    board.poseTeachTrain = lambda: started.append(1)
    snap({"state": "done", "posture": "v_sign_down", "name": "거꾸로 V", "taught": "v_sign_down", "gesture_key": ""})
    assert board.teach_adding and not started and board.pose_probe_view["state"] == "countdown"
    assert ("pose_teach_save", "v_sign_down") not in list(board.online_commands)
    snap({"state": "countdown", "seconds": 2})
    snap({"state": "holding", "progress": .5})
    snap(unknown)
    assert ("pose_teach_save", "v_sign_down") in list(board.online_commands)       # saved by itself
    _wait(50)
    assert not root.findChild(QObject, "poseTeachNewName").property("visible")     # no form for a new shape
    assert not root.findChild(QObject, "poseTeachAddFocus").property("visible")
    snap({**unknown, "posture": "v_sign_down", "name": "거꾸로 V", "unknown": False, "taught": "v_sign_down"})
    _wait(50)
    assert not board.teach_adding and not root.findChild(QObject, "poseTeachNewName").property("visible")
    # a look that failed or moved adds nothing and says so
    board.online_commands.clear()
    board.poseTeachAgain()
    snap({"state": "holding", "progress": .5})
    snap({"state": "failed", "message": "손이 잘 보이지 않았어요."})
    assert not board.teach_adding and ("pose_teach_save", "v_sign_down") not in list(board.online_commands)
    assert "추가되지 않았어요" in board.llmContext["teach"]["text"]
    board.teach_focus = ""
    board.startPoseProbe()
    snap({"state": "holding", "progress": .9})
    snap({"state": "done", "posture": "fist", "name": "주먹 쥐기", "gesture_key": ""})

    # [새 동작 등록]: the shape taught so far is done with, a fresh look starts, and its end asks for a name
    board.teach_focus = "v_sign_down"
    board.teach_view = {"state": "", "text": ""}
    board.llmChanged.emit()
    _wait(50)
    assert root.findChild(QObject, "poseTeachNew").property("visible")
    board.online_commands.clear()
    board.poseTeachNew()
    teach = board.llmContext["teach"]
    assert teach["focus"] == "" and teach["naming"] and not teach["adding"] and "새 손 모양을 보여 주세요" in teach["text"]
    assert ("pose_probe",) in list(board.online_commands) and board.pose_probe_view["state"] == "countdown"
    snap({"state": "holding", "progress": .5})
    snap({"state": "done", "posture": "fist", "name": "주먹 쥐기", "gesture_key": ""})
    _wait(50)
    assert ("pose_teach_save", "v_sign_down") not in list(board.online_commands)   # nothing is added to the old shape
    assert root.findChild(QObject, "poseTeachNewName").property("visible")
    assert not root.findChild(QObject, "poseTeachAddFocus").property("visible")
    try:
        board.poseTeachSaveNew("늑대")
        key = next(k for k, v in custom_postures.load().items() if v == "늑대")
        assert board.teach_focus == key and not board.llmContext["teach"]["naming"]
        assert ("pose_teach_save", key) in list(board.online_commands)
    finally:
        custom_postures.PATH.unlink(missing_ok=True)
        custom_postures.register()
    board.teach_focus = ""
    board.startPoseProbe()
    snap({"state": "holding", "progress": .9})
    snap({"state": "done", "posture": "fist", "name": "주먹 쥐기", "gesture_key": ""})

    # [새 동작 등록] is at the bottom of the window, in the row of Close - also with no shape being taught
    button = root.findChild(QObject, "poseTeachNew")
    box = button.parentItem()
    while box is not None and "DialogButtonBox" not in box.metaObject().className():
        box = box.parentItem()
    assert box is not None and button.property("visible") and button.property("enabled")
    close = root.findChild(QObject, "llmClose")                    # ... and Close is still there, beside it
    assert close.property("visible") and close.property("width") > 20 and button.property("width") > 20
    assert close.parentItem() is not None and abs(close.property("y") - button.property("y")) < 2
    assert abs(close.property("x") - button.property("x")) >= min(close.property("width"), button.property("width"))

    # the shapes the user named are listed with what hangs on them, and deleting one takes all of it along
    from src.action_bindings import get_action_registry
    try:
        key = custom_postures.add("오타 이름")
        pt.delete_examples(key)              # (the key was used by a shape made and dropped earlier in this test)
        get_action_registry().register_composite_gesture("", "오타 이름 유지", key, "hold", "hotkey", "f5")
        pt.save_example(key, [[[0.0, 0.0, 0.0]] * 21])
        board.teach_focus = key
        board.llmChanged.emit()
        _wait(50)
        rows = board.customPostures
        assert rows == [{"key": key, "name": "오타 이름", "examples": 1, "uses": 1, "usesText": "오타 이름 유지"}]
        board.removeCustomPosture(key)
        _wait(50)
        assert board.customPostures == [] and board.teach_focus == "" and key not in POSTURE_NAMES_KO
        assert not get_action_registry().composite_gestures and pt.example_counts().get(key) is None
        assert "오타 이름" in board.teach_view["text"]
    finally:
        custom_postures.PATH.unlink(missing_ok=True)
        custom_postures.register()
    board.teach_view = {"state": "", "text": ""}

    # a single picture: no replay
    board._set_probe_shot((2, frames[0], [frames[0]]))
    _wait(50)
    assert shot.property("frames") == 1
    root.findChild(QObject, "llmDialog").setProperty("visible", False)


def test_the_ai_connection_card_folds_to_one_line_once_it_is_set_up(board):
    """2026-11-11: the provider / model / key rows took the top of the window; they fold away once usable."""
    from PySide6.QtCore import QObject
    root = board.engine.rootObjects()[0]
    root.findChild(QObject, "llmDialog").setProperty("visible", True)
    _wait(50)
    card = root.findChild(QObject, "llmSetup")
    toggle = root.findChild(QObject, "llmSetupToggle")
    summary = root.findChild(QObject, "llmSetupSummary").property("text")
    assert summary.startswith("AI 연결")
    if card.property("ready"):
        assert not card.property("open") and toggle.property("visible")      # folded by default
        assert board.llmSettings["modelShown"] in summary
        card.setProperty("userOpen", True)
        assert card.property("open") and toggle.property("text") == "접기"
    else:
        card.setProperty("userOpen", False)
        assert card.property("open") and not toggle.property("visible")     # nothing usable yet: it stays open
    root.findChild(QObject, "llmDialog").setProperty("visible", False)