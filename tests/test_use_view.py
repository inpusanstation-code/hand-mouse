"""The main screen's learning cards and their [사례 보기] viewer (2026-11-11): each card opens THAT gesture's collected uses
(src/use_view.py), not the training center's dataset simulator."""
import json
import os
import time

import pytest

from src.use_view import cases


def _log(folder, key="comp_custom_2_hold", n=3, marked=(1,)):
    folder.mkdir(parents=True, exist_ok=True)
    lines = []
    for i in range(1, n + 1):
        t0 = 100.0 + i * 10
        frames = [{"t": round(t0 - 3 + k / 30, 4), "lm": [[.5 + .001 * k, .5, 0.0]] * 21} for k in range(150)]
        lines.append({"type": "event", "id": i, "source": "binding", "key": key, "label": "", "t": t0,
                      "wall": f"2026-11-11 12:00:{i:02d}", "frames": frames})
        if i in marked:
            lines.append({"type": "mark", "id": i, "t": t0 + 1, "reason": "f_key"})
    lines.append({"type": "event", "id": 99, "source": "binding", "key": "comp_other_hold", "t": 1.0, "wall": "x",
                  "frames": []})
    (folder / "20261111-120000-pc.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")


def test_the_viewer_reads_only_that_gestures_uses_newest_first(tmp_path):
    _log(tmp_path / "use")
    out = cases(tmp_path / "use", "comp_custom_2_hold")
    assert [c["when"] for c in out] == ["2026-11-11 12:00:03", "2026-11-11 12:00:02", "2026-11-11 12:00:01"]
    assert [c["marked"] for c in out] == [False, False, True] and "F" in out[2]["mark_text"]
    c = out[0]
    assert 70 <= len(c["frames"]) <= 80 and len(c["frames"][0]) == 21                 # ~5 s at 15 pictures a second
    assert c["frames"][c["fire"]] and c["before"] == pytest.approx(3.0, abs=.1)       # the command 3 s in
    assert all(0 <= v <= 1 for f in c["frames"] for p in f for v in p)
    assert cases(tmp_path / "use", "comp_nothing") == []


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
    yield ui, app


def test_a_card_per_gesture_and_its_button_opens_those_uses(board, tmp_path):
    from PySide6.QtCore import QObject
    from PySide6.QtQuick import QQuickItem
    ui, app = board
    _log(tmp_path / "use")
    ui.use_log_folder = str(tmp_path / "use")
    root = ui.engine.rootObjects()[0]
    ui.learn_items = [{"key": "comp_custom_2_hold", "name": "옆따봉 유지", "state": "collecting", "n": 3, "need": 20,
                       "text": "20번이 되면 TCN 학습을 자동으로 시작", "hint": ""}]
    ui.learnChanged.emit()
    app.processEvents()
    banner = root.findChild(QQuickItem, "learnBanner")
    cards = []

    def walk(item):
        for c in item.childItems():
            if c.objectName() == "learnCard":
                cards.append(c)
            walk(c)
    walk(banner)
    assert len(cards) == 1                                                            # one card per gesture
    assert ui.learnAutoLine == "" and isinstance(ui.learnRunning, bool)              # the old flag keeps its meaning
    ui.openUseCases("comp_custom_2_hold", "옆따봉 유지")
    for _ in range(100):                     # QTest.qWait keeps the GIL: the reading thread would not run during it
        time.sleep(.02)
        app.processEvents()
        if not ui.useCases.get("loading"):
            break
    data = ui.useCases
    assert data["key"] == "comp_custom_2_hold" and len(data["items"]) == 3 and not data["error"]
    dialog = root.findChild(QObject, "useCasesDialog")
    dialog.setProperty("visible", True)
    app.processEvents()
    assert dialog.property("shown") is not None
    dialog.setProperty("visible", False)
