"""The drawn virtual hand glides toward each new camera frame at the screen's rate, as in the hand-mouse virtual-hand
branch (2026-11-10 '움직임이 너무 끊긴다', '가상손 모드의 좋은 부분들을 너무 많이 잃었다')."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
pytest.importorskip("PySide6")
from pathlib import Path
from PySide6.QtCore import Property, QObject, QUrl, Signal, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtTest import QTest

QML = Path(__file__).resolve().parents[3] / "src" / "manux" / "ui" / "qml" / "VirtualHandOverlay.qml"


class Controller(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self._hand = {}

    @Property("QVariantMap", notify=changed)
    def virtualHand(self):
        return self._hand

    def show(self, palm, finger=0.0, lost=False):
        pts = [0.0] * 42
        pts[17] = finger                                   # joint 8 (index tip) y
        self._hand = {"pts": pts, "anchor": [0, 0], "aim": True, "grip": False, "lost": lost,
                      "palm": list(palm), "scale": 1.0}
        self.changed.emit()


def test_drawn_hand_and_window_glide_continuously_to_the_newest_frame():
    app = QGuiApplication.instance() or QGuiApplication([])
    messages = []
    qInstallMessageHandler(lambda mode, ctx, text: messages.append(text))
    controller = Controller()
    engine = QQmlEngine()
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(QML)))
    overlay = component.createWithInitialProperties({"controller": controller})
    try:
        assert overlay is not None, component.errorString()
        controller.show((500, 500)); QTest.qWait(30)
        start = overlay.property("x")
        assert start == 500 - 170                            # the first frame is placed at once
        controller.show((600, 500), finger=-40.0)
        seen = []
        for _ in range(30):
            QTest.qWait(10)
            seen.append(overlay.property("x"))
        assert any(start < x < start + 100 for x in seen), seen          # on its way, not one jump
        assert abs(seen[-1] - (start + 100)) <= 1                         # and there
        assert abs(overlay.property("shown").toVariant()[17] + 40.0) < 1.0  # the joints glide too
        assert not [m for m in messages if "VirtualHandOverlay" in m], messages
    finally:
        qInstallMessageHandler(None)
        if overlay is not None:
            overlay.deleteLater()
        del app
