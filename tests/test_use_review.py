"""The person judges the collected uses before they are learned from (2026-11-11 request: "유저가 오탐지인지 아닌지 판단하는
세션 … 유저가 통과시킨 데이터들만 TCN 학습")."""

from __future__ import annotations

import pytest

from src import use_review
from tests.test_use_learning import counts, write_log

KEY = "comp_new@down"
_ALIVE = []     # dashboards kept to the end: one garbage-collected while the next test's QML runs crashes Qt on Windows
NAME = "20261111-000001-pc.jsonl"


def log(tmp_path, n=12):
    pytest.importorskip("torch")
    from tests.test_online_update import frames
    write_log(tmp_path / "use", frames, n_marked=0, n_meant=0, n_taught=n, name=NAME)
    return tmp_path / "use"


def test_verdicts_are_kept_beside_the_log_and_split_the_count(tmp_path):
    from src.online.use_import import pending_counts, pending_detail
    folder, root = log(tmp_path), tmp_path / "online"
    waiting = use_review.waiting(folder, root, KEY)
    assert len(waiting) == 12 and all(ev["review"] == "" and ev["frames"] for ev in waiting)
    assert pending_detail(folder, root) == {KEY: {"ok": 0, "new": 12, "bad": 0}}
    ids = [ev["id"] for ev in waiting]
    use_review.set_verdicts(folder, [(NAME, i, use_review.OK) for i in ids[:7]] + [(NAME, i, use_review.BAD) for i in ids[7:10]])
    assert pending_detail(folder, root) == {KEY: {"ok": 7, "new": 2, "bad": 3}}
    assert pending_counts(folder, root) == {KEY: 9}                    # a false detection is not a use
    assert [ev["review"] for ev in use_review.waiting(folder, root, KEY)] == ["ok"] * 7 + ["bad"] * 3 + [""] * 2
    use_review.set_verdicts(folder, [(NAME, ids[0], "")])              # taken back
    assert pending_detail(folder, root)[KEY] == {"ok": 6, "new": 3, "bad": 3}
    use_review.set_verdicts(folder, [("gone.jsonl", 1, use_review.OK)])  # a log file that is not there: not kept
    assert "gone.jsonl" not in use_review.load(folder)


def test_only_passed_uses_are_learned_and_false_detections_become_what_the_gesture_is_not(tmp_path):
    from src.online.samples import PSEUDO_CANDIDATE, VALIDATED_PSEUDO, SampleStore
    from src.online.use_import import import_events, pending_detail
    folder = log(tmp_path)
    store = SampleStore(tmp_path / "online")
    classes = ["none", "thumb_index"]
    # nothing judged yet: nothing is taken, everything waits for the person
    assert import_events(store, folder, classes, new_min=5, require_review=True) == counts(skipped=1, unreviewed=12)
    assert store.samples() == []
    ids = [ev["id"] for ev in use_review.waiting(folder, store.root, KEY)]
    use_review.set_verdicts(folder, [(NAME, i, use_review.OK) for i in ids[:6]] + [(NAME, i, use_review.BAD) for i in ids[6:9]])
    out = import_events(store, folder, classes, new_min=5, require_review=True)
    assert out == counts(taught=6, negatives=3, unreviewed=3, new_classes=[KEY])
    taught = store.samples(sources=[PSEUDO_CANDIDATE])
    assert len(taught) == 6 and {s.label for s in taught} == {KEY}
    rejected = store.samples(sources=[VALIDATED_PSEUDO])               # kept as "not this gesture", like an F mark
    assert len(rejected) == 3 and {s.label for s in rejected} == {"none"}
    assert all(s.extra["marked"] == use_review.MARK and s.suggested_label == "comp_new" for s in rejected)
    # the three not looked at are still in the log, and are taken once judged
    assert pending_detail(folder, store.root) == {KEY: {"ok": 0, "new": 3, "bad": 0}}
    use_review.set_verdicts(folder, [(NAME, i, use_review.OK) for i in ids[9:]])
    assert import_events(store, folder, classes, new_min=5, require_review=True) == counts(taught=3, new_classes=[KEY])
    assert import_events(store, folder, classes, new_min=5, require_review=True) == counts()


def test_without_the_setting_unjudged_uses_are_learned_as_before_but_a_rejected_one_never_is(tmp_path):
    from src.online.samples import PSEUDO_CANDIDATE, SampleStore
    from src.online.use_import import import_events
    folder = log(tmp_path)
    store = SampleStore(tmp_path / "online")
    first = use_review.waiting(folder, store.root, KEY)[0]["id"]
    use_review.set_verdicts(folder, [(NAME, first, use_review.BAD)])
    out = import_events(store, folder, ["none", "thumb_index"], new_min=5)
    assert out == counts(taught=11, negatives=1, skipped=1, new_classes=[KEY])
    assert len(store.samples(sources=[PSEUDO_CANDIDATE])) == 11


def test_the_card_asks_for_a_review_and_the_round_starts_only_from_passed_uses(tmp_path):
    from tests.test_use_learning import learning_runtime
    rt = learning_runtime(tmp_path)
    need = rt._use_need(KEY)
    rt._use_pending, rt._use_new = {KEY: 0}, {KEY: need}              # enough collected, none judged
    rt._use_note()
    card = next(i for i in rt._learn_items if i["key"] == KEY)
    assert card["state"] == "review" and card["review"] == need and card["n"] == need
    before = rt._learn_request
    rt._use_auto(1e6)
    assert rt._learn_request == before                                 # not looked at: no learning
    rt._use_pending, rt._use_new = {KEY: need - 3}, {KEY: 0}          # judged: three were false detections
    rt._use_note()
    card = next(i for i in rt._learn_items if i["key"] == KEY)
    assert card["state"] == "collecting" and card["n"] == need - 3
    rt._use_auto(1e6)
    assert rt._learn_request == before
    rt._use_pending, rt._use_new = {KEY: need}, {KEY: 2}              # enough passed (two newer ones wait for the next look)
    rt._use_note()
    assert next(i for i in rt._learn_items if i["key"] == KEY)["state"] == "ready"
    rt._use_auto(1e6)
    assert rt._learn_request == before + 1


def test_the_dashboard_session_writes_verdicts_and_asks_for_a_recount(tmp_path):
    pytest.importorskip("PySide6")
    import os
    import time
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication
    from src.qt_dashboard import QtDashboard
    folder = log(tmp_path, n=5)
    app = QApplication.instance() or QApplication([])
    QQuickStyle.setStyle("Basic")
    ui = QtDashboard(dry_run=True)
    ui.use_log_folder = str(folder)
    ui.online_root = tmp_path / "online"
    ui.openUseReview(KEY, "새 동작")
    end = time.time() + 10
    while ui.useCases.get("loading") and time.time() < end:
        time.sleep(.02)
        app.processEvents()
    items = ui.useCases["items"]
    assert ui.useCases["review"] and len(items) == 5 and all(i["review"] == "" and i["frames"] for i in items)
    ui.judgeUseCase(0, "ok")
    ui.judgeUseCase(1, "bad")
    assert [i["review"] for i in ui.useCases["items"]] == ["ok", "bad", "", "", ""]
    ui.judgeUseRest("ok")
    assert [i["review"] for i in ui.useCases["items"]] == ["ok", "bad", "ok", "ok", "ok"]
    saved = use_review.load(folder)[NAME]
    assert sorted(saved.values()) == ["bad", "ok", "ok", "ok", "ok"]
    _ALIVE.append(ui)
    ui.online_commands.clear()
    ui.finishUseReview()
    assert ("use_recount",) in ui.online_commands
    # the job is started with the setting the runtime reports
    started = {}

    class Job:
        running = False

        def start(self, **kw):
            started.update(kw)
            return True

    ui._online_job = lambda: Job()
    ui.auto_learn((getattr(ui, "learn_request_seen", 0) + 1, str(folder), True))
    assert started == {"use_events": str(folder), "require_review": True}


def test_a_verdict_keeps_the_list_where_it_was_and_the_played_row_on_screen(tmp_path):
    """2026-11-11: each [통과]/[오탐지] scrolled the list back to the top, so a long session meant scrolling down every time."""
    pytest.importorskip("PySide6")
    import os
    import time
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QMetaObject, QObject, Q_ARG
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication
    from src.qt_dashboard import QtDashboard
    folder = log(tmp_path, n=30)
    app = QApplication.instance() or QApplication([])
    QQuickStyle.setStyle("Basic")
    ui = QtDashboard(dry_run=True)
    ui.use_log_folder = str(folder)
    ui.online_root = tmp_path / "online"
    _ALIVE.append(ui)
    dialog = ui.window.findChild(QObject, "useCasesDialog")
    listview = ui.window.findChild(QObject, "useCasesList")
    ui.openUseReview(KEY, "새 동작")
    end = time.time() + 10
    while ui.useCases.get("loading") and time.time() < end:
        time.sleep(.02)
        app.processEvents()
    dialog.setProperty("visible", True)

    def settle():
        for _ in range(20):
            time.sleep(.01)
            app.processEvents()

    def row_on_screen(i):
        top = i * 48                                                # 44 high + 4 apart
        y, h = listview.property("contentY"), listview.property("height")
        return y - 1 <= top and top + 44 <= y + h + 1

    settle()
    assert len(ui.useCases["items"]) == 30
    dialog.setProperty("current", 20)                               # a row far down: the list follows it
    settle()
    assert listview.property("contentY") > 0 and row_on_screen(20)
    before = listview.property("contentY")
    QMetaObject.invokeMethod(dialog, "judge", Q_ARG("QVariant", "ok"))
    settle()
    assert ui.useCases["items"][20]["review"] == "ok"
    assert dialog.property("current") == 21 and row_on_screen(21)
    assert listview.property("contentY") >= before - 1            # not back at the top
