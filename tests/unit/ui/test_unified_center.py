import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import pytest
pytest.importorskip("PySide6")
from PySide6.QtCore import QObject, QMetaObject, QPointF
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from manux.app import schema, training_specs
from manux.settings.store import Settings
from manux.data.training_center import TrainingCenterService
from manux.ui.bridge import Bridge
from test_bridge import FakeRuntime


@pytest.mark.parametrize("layout",["standard","studio"])
def test_common_tabs_keep_header_and_named_model_actions(tmp_path,monkeypatch,layout):
    settings=Settings(schema())
    runtime=FakeRuntime(settings)
    if layout=="studio":
        from manux.desktop import build
        from types import SimpleNamespace
        runtime=build(settings,SimpleNamespace(close=lambda:None),windows=False)
    service=TrainingCenterService(tmp_path/'config',tmp_path/'data',tmp_path/'recordings',specs=training_specs())
    service.configure("synthetic")
    b=Bridge(runtime,settings,tmp_path/'config',services={"training_center":service},layout=layout)
    try:
        b.control_hand="Right";b.finishSplash()
        popup=b.window.findChild(QObject,"studioDataManagement" if layout=="studio" else "trainingCenter")
        if layout=="studio":
            button=b.window.findChild(QObject,"openLearningCenter")
            assert QMetaObject.invokeMethod(button,"click")
            assert not b.window.findChild(QObject,"trainingCenter").property("visible")
        else: QMetaObject.invokeMethod(popup,"open")
        for _ in range(80):
            QTest.qWait(30)
            if not b.studio.busy and not b.training_busy:break
        for width,height in ((780,560),(1140,720)):
            b.window.setWidth(width);b.window.setHeight(height)
            for index in range(6):
                popup.setProperty("pageIndex",index);QTest.qWait(30)
                alias=b.window.findChild(QQuickItem,"trainingAlias")
                point=alias.mapToScene(QPointF(0,0))
                assert alias.isVisible() and 0<=point.y()<180
                assert b.paused
        assert b._pose_studio_visible
        popup.setProperty("pageIndex",3);QTest.qWait(30)
        assert not b._pose_studio_visible
        calls=[]
        monkeypatch.setattr(b.studio,"_run",lambda action,**values:calls.append((action,values)))
        b.studio.modelAction("preview","a"*64,"")
        assert calls==[("model_preview",{"identifier":"a"*64,"name":""})]
    finally:
        b.close()
        if layout=="studio":runtime.stop()


def test_register_a_gesture_from_the_pose_page_without_qml_errors(tmp_path):
    from PySide6.QtCore import qInstallMessageHandler
    from manux.desktop import build, CustomPoses
    from types import SimpleNamespace
    messages = []
    qInstallMessageHandler(lambda mode, ctx, text: messages.append(text))
    settings = Settings(schema())
    runtime = build(settings, SimpleNamespace(close=lambda: None), windows=False)
    runtime.custom_poses = CustomPoses(tmp_path / "custom_poses")
    service = TrainingCenterService(tmp_path/'config', tmp_path/'data', tmp_path/'recordings', specs=training_specs())
    service.configure("synthetic")
    b = Bridge(runtime, settings, tmp_path/'config', services={"training_center": service}, layout="studio")
    try:
        b.control_hand = "Right"; b.finishSplash()
        if b.stage != "main":
            b._set_stage("main")
        QTest.qWait(40)
        section = b.window.findChild(QQuickItem, "mainCustomPoses")         # on the first page (2026-11-10 request)
        assert section is not None and section.isVisible()
        start = b.window.findChild(QQuickItem, "customPoseStart")
        assert start is not None and start.isVisible()
        assert not start.property("enabled")                         # no name yet
        b.window.findChild(QQuickItem, "customPoseName").setProperty("text", "락 사인")
        QTest.qWait(10)
        assert start.property("enabled")
        assert QMetaObject.invokeMethod(start, "click")
        runtime._drain_runtime_requests(); b.poll(); QTest.qWait(20)
        assert b.customPoseSession["state"] == "prep" and b.paused
        assert b.window.findChild(QQuickItem, "customPoseProgress").isVisible()
        b.cancelCustomPose(); runtime._drain_runtime_requests(); b.poll(); QTest.qWait(20)
        assert b.customPoseSession == {} and start.isVisible()
        presets = b.customPosePresets
        assert presets[0]["label"].startswith("명령 없음") and presets[-1]["keys"] == "*" and len(presets) > 60
        from manux.actions.keys import parse_combo
        for p in presets[1:-1]:
            if p["action"] == "keys.press":
                parse_combo(p["keys"])                                      # every preset is a valid, allowed combination
        assert any(p["keys"].startswith("win") for p in presets)
        assert not [m for m in messages if any(s in m for s in ("ReferenceError", "TypeError", "Cannot assign", "Binding loop"))], messages
    finally:
        qInstallMessageHandler(None)
        b.close()
        runtime.stop()


def test_everyday_section_on_the_recording_page_switches_and_lists(tmp_path):
    from PySide6.QtCore import qInstallMessageHandler
    from manux.desktop import build, everyday_service
    from types import SimpleNamespace
    messages = []
    qInstallMessageHandler(lambda mode, ctx, text: messages.append(text))
    settings = Settings(schema())
    runtime = build(settings, SimpleNamespace(close=lambda: None), windows=False)
    service = TrainingCenterService(tmp_path/'config', tmp_path/'data', tmp_path/'recordings', specs=training_specs())
    service.configure("synthetic")
    every = everyday_service(tmp_path / "recordings" / "everyday", lambda: "pinch")
    b = Bridge(runtime, settings, tmp_path/'config', services={"training_center": service, "everyday": every}, layout="studio")
    try:
        b.control_hand = "Right"; b.finishSplash()
        assert QMetaObject.invokeMethod(b.window.findChild(QObject, "openLearningCenter"), "click")
        popup = b.window.findChild(QObject, "studioDataManagement")
        popup.setProperty("pageIndex", 1); QTest.qWait(40)
        check = b.window.findChild(QQuickItem, "everydayCollect")
        assert check is not None and check.isVisible() and not check.property("checked")
        for width in (780, 1140):                       # the label must fit its column (2026-11-10 report: it spilled out)
            b.window.setWidth(width); QTest.qWait(30)
            label = b.window.findChild(QQuickItem, "everydayCollectLabel")
            box = check.parentItem().parentItem().parentItem()
            right = label.mapToItem(box, label.property("width"), 0).x()
            assert label.isVisible() and right <= box.property("width") + 1, (width, right, box.property("width"))
            assert label.property("lineCount") >= 1 and label.property("contentWidth") <= label.property("width") + 1
        b.setEverydayCollect(True); QTest.qWait(20)
        assert settings.get("data.collect_everyday") is True and check.property("checked")
        b.refreshEveryday()
        assert b.everydayCandidates == [] and b.everydayChoiceLabels[0] == "아무 동작도 아니었음"
        assert not [m for m in messages if any(s in m for s in ("ReferenceError", "TypeError", "Cannot assign", "Binding loop"))], messages
    finally:
        qInstallMessageHandler(None)
        b.close()
        runtime.stop()


def test_checking_a_task_keeps_the_list_where_it_was(tmp_path):
    """2026-11-10 report: checking a task scrolled the list to the top, so another row's check sat under the pointer."""
    from manux.desktop import build
    from types import SimpleNamespace
    settings = Settings(schema())
    runtime = build(settings, SimpleNamespace(close=lambda: None), windows=False)
    service = TrainingCenterService(tmp_path/'config', tmp_path/'data', tmp_path/'recordings', specs=training_specs())
    service.configure("synthetic")
    b = Bridge(runtime, settings, tmp_path/'config', services={"training_center": service}, layout="studio")
    try:
        b.control_hand = "Right"; b.finishSplash()
        assert QMetaObject.invokeMethod(b.window.findChild(QObject, "openLearningCenter"), "click")
        for _ in range(80):
            QTest.qWait(30)
            if not b.studio.busy and not b.training_busy:
                break
        popup = b.window.findChild(QObject, "studioDataManagement")
        b.window.setWidth(1140); b.window.setHeight(720)
        popup.setProperty("pageIndex", 0); QTest.qWait(60)
        tasks = b.window.findChild(QQuickItem, "trainingTasks")
        assert tasks.property("contentHeight") > tasks.property("height") + 200, "needs a list longer than the view"
        tasks.setProperty("contentY", 200.0); QTest.qWait(40)
        before = tasks.property("contentY")
        def items(item):
            for child in item.childItems():
                yield child
                yield from items(child)
        visible_checks = [c for c in items(tasks) if c.objectName().startswith("taskCheck_")
                          and c.isVisible() and 0 <= c.mapToItem(tasks, 0, 0).y() < tasks.property("height") - 40]
        check = visible_checks[len(visible_checks) // 2]
        key = check.objectName().removeprefix("taskCheck_")
        was = key in b.training_selected
        assert QMetaObject.invokeMethod(check, "click")
        QTest.qWait(80)
        assert (key in b.training_selected) != was
        assert abs(tasks.property("contentY") - before) < 5, (before, tasks.property("contentY"))
    finally:
        b.close()
        runtime.stop()



def test_a_registered_gesture_gets_a_preset_or_a_typed_win_combination_on_screen(tmp_path):
    from PySide6.QtCore import qInstallMessageHandler
    from manux.desktop import build, CustomPoses
    from types import SimpleNamespace
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "features"))
    from test_custom_pose import ASPECT, ROCK, demonstrate
    messages = []
    qInstallMessageHandler(lambda mode, ctx, text: messages.append(text))
    settings = Settings(schema())
    runtime = build(settings, SimpleNamespace(close=lambda: None), windows=False)
    runtime.custom_poses = CustomPoses(tmp_path / "cp")
    runtime.custom_poses.start("락", ASPECT)
    demonstrate(runtime.custom_poses.session, ROCK)
    runtime.custom_poses.approve()
    service = TrainingCenterService(tmp_path/'config', tmp_path/'data', tmp_path/'recordings', specs=training_specs())
    service.configure("synthetic")
    b = Bridge(runtime, settings, tmp_path/'config', services={"training_center": service}, layout="studio")
    try:
        b.control_hand = "Right"; b.finishSplash()
        if b.stage != "main":
            b._set_stage("main")
        b.poll(); QTest.qWait(60)
        def find(name):
            def walk(item):
                for child in item.childItems():
                    if child.objectName() == name:
                        return child
                    hit = walk(child)
                    if hit is not None:
                        return hit
            return walk(b.window.contentItem()) or next((w for w in [b.window.findChild(QQuickItem, name)] if w), None)
        select = find("customPoseAction-slot1")
        assert select is not None and select.property("currentIndex") == 0
        copy = next(i for i, p in enumerate(b.customPosePresets) if p["keys"] == "ctrl+c")
        b.setCustomPoseAction("slot1", "keys.press", "ctrl+c")
        runtime._drain_runtime_requests(); b.poll(); QTest.qWait(30)
        assert b.customPoses[0]["keys"] == "ctrl+c" and find("customPoseAction-slot1").property("currentIndex") == copy
        b.setCustomPoseAction("slot1", "keys.press", "win + e")                 # typed, but it is a preset
        runtime._drain_runtime_requests(); b.poll(); QTest.qWait(30)
        explorer = next(i for i, p in enumerate(b.customPosePresets) if p["keys"] == "win+e")
        assert b.customPoses[0]["keys_label"] == "Win + E" and find("customPoseAction-slot1").property("currentIndex") == explorer
        b.setCustomPoseAction("slot1", "keys.press", "Shift+Win+N")             # not in the list
        runtime._drain_runtime_requests(); b.poll(); QTest.qWait(30)
        assert b.customPoses[0]["keys"] == "shift+win+n"
        assert find("customPoseAction-slot1").property("currentIndex") == len(b.customPosePresets) - 1   # "직접 입력"
        assert find("customPoseKeys-slot1").isVisible()
        b.setCustomPoseAction("slot1", "keys.press", "alt+f4")
        runtime._drain_runtime_requests(); b.poll(); QTest.qWait(30)
        assert b.customPoses[0]["keys"] == "shift+win+n" and "위험" in b.customPoseMessage
        assert not [m for m in messages if any(s in m for s in ("ReferenceError", "TypeError", "Cannot assign", "Binding loop"))], messages
    finally:
        qInstallMessageHandler(None)
        b.close()
        runtime.stop()



@pytest.mark.parametrize("layout", ["standard", "studio"])
def test_new_gesture_registration_is_on_the_first_page_in_both_layouts(tmp_path, layout):
    from manux.desktop import build, CustomPoses
    from types import SimpleNamespace
    settings = Settings(schema())
    runtime = build(settings, SimpleNamespace(close=lambda: None), windows=False)
    runtime.custom_poses = CustomPoses(tmp_path / "cp")
    b = Bridge(runtime, settings, tmp_path/'config', layout=layout)
    try:
        b.control_hand = "Right"; b.finishSplash()
        if b.stage != "main":
            b._set_stage("main")
        b.window.setWidth(1140); b.window.setHeight(760); QTest.qWait(60)
        section = b.window.findChild(QQuickItem, "mainCustomPoses")
        assert section is not None and section.isVisible() and section.property("width") > 150
        assert b.window.findChild(QQuickItem, "customPoseStart").isVisible()
    finally:
        b.close()
        runtime.stop()


@pytest.mark.parametrize("layout", ["standard", "studio"])
def test_fist_style_choice_on_the_first_page_switches_both_speeds(tmp_path, layout):
    from PySide6.QtCore import qInstallMessageHandler
    from manux.desktop import build
    from types import SimpleNamespace
    messages = []
    qInstallMessageHandler(lambda mode, ctx, text: messages.append(text))
    settings = Settings(schema())
    runtime = build(settings, SimpleNamespace(close=lambda: None), windows=False)
    b = Bridge(runtime, settings, tmp_path/'config', layout=layout)
    try:
        b.control_hand = "Right"; b.finishSplash()
        if b.stage != "main":
            b._set_stage("main")
        b.window.setWidth(1140); b.window.setHeight(760); QTest.qWait(60)
        def find(name, item=None):                      # the visible one (the tutorial page has its own copy)
            for child in (item or b.window.contentItem()).childItems():
                if child.objectName() == name and child.isVisible():
                    return child
                hit = find(name, child)
                if hit is not None:
                    return hit
        fast, precise = find("fistStyle_fast"), find("fistStyle_precise")
        assert fast is not None and fast.isVisible() and precise.property("checked") and not fast.property("checked")
        assert QMetaObject.invokeMethod(fast, "click")
        runtime._drain_runtime_requests(); b.poll(); QTest.qWait(40)
        assert settings.get("pinch.fist_dpi_multiplier") == 30.0 and settings.get("pinch.shape_dpi_min") == 1.0
        assert fast.property("checked") and not precise.property("checked")
        assert runtime.settings_for("pinch")["fist_dpi_multiplier"] == 30.0
        assert QMetaObject.invokeMethod(precise, "click")
        runtime._drain_runtime_requests(); b.poll(); QTest.qWait(40)
        assert settings.get("pinch.fist_dpi_multiplier") == .35 and precise.property("checked")
        assert not [m for m in messages if "QuickSpeedControls" in m], messages
    finally:
        qInstallMessageHandler(None)
        b.close()
        runtime.stop()
