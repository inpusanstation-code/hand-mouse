"""The skeletons' colours, opacity and thickness from the settings window (2026-11-12, src/skeleton_style.py)."""
import os

from src.skeleton_style import DEFAULTS, clean, color


def test_values_are_cleaned():
    assert color("46e5bd") == "#46E5BD" and color("#zzzzzz") == "" and color("") == ""
    out = clean({"main": "red", "other": "#f97316", "preview_alpha": 5, "vh_alpha": "x", "width": .1, "junk": 1})
    assert out["main"] == DEFAULTS["main"] and out["other"] == "#F97316"
    assert out["preview_alpha"] == 1.0 and out["vh_alpha"] == DEFAULTS["vh_alpha"] and out["width"] == .5
    assert "junk" not in out and clean(None) == DEFAULTS


def test_the_settings_keep_the_choice_and_refuse_a_bad_colour():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QObject
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication
    from src.qt_dashboard import QtDashboard
    from tests.test_use_review import _ALIVE
    app = QApplication.instance() or QApplication([])
    QQuickStyle.setStyle("Basic")
    ui = QtDashboard(dry_run=True)
    _ALIVE.append(ui)
    seen = []
    ui.skeletonStyleChanged.connect(lambda: seen.append(1))
    assert ui.setSkeletonStyle("other", "#f97316") and ui.skeletonStyle["values"]["other"] == "#F97316"
    assert ui.setSkeletonStyle("preview_alpha", .4) and ui.skeletonStyle["values"]["preview_alpha"] == .4
    assert not ui.setSkeletonStyle("main", "blue") and ui.skeletonStyle["values"]["main"] == DEFAULTS["main"]
    assert not ui.setSkeletonStyle("nope", 1)
    assert len(seen) == 2
    assert ui._read_skeleton_style(ui.preferences)["other"] == "#F97316"        # saved
    assert ui.window.findChild(QObject, "skeletonStyleBox") is not None
    ui.resetSkeletonStyle()
    assert ui.skeletonStyle["values"] == DEFAULTS
    app.processEvents()
