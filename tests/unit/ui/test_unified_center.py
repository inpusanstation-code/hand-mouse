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
        assert QMetaObject.invokeMethod(b.window.findChild(QObject, "openLearningCenter"), "click")
        popup = b.window.findChild(QObject, "studioDataManagement")
        for _ in range(80):
            QTest.qWait(30)
            if not b.studio.busy and not b.training_busy:
                break
        start = None
        for index in range(6):
            popup.setProperty("pageIndex", index); QTest.qWait(30)
            start = b.window.findChild(QQuickItem, "customPoseStart")
            if start is not None and start.isVisible():
                break
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
        assert b.customPoseCommandLabels[0].startswith("명령 없음") and len(b.customPoseCommandIds) == len(b.customPoseCommandLabels)
        assert not [m for m in messages if any(s in m for s in ("ReferenceError", "TypeError", "Cannot assign", "Binding loop"))], messages
    finally:
        qInstallMessageHandler(None)
        b.close()
        runtime.stop()
