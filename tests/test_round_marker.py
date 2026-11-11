"""A learning round cut off by closing the app is started again with the app (2026-11-11: "앱을 끄면 학습 멈췄다가, 앱 다시
켜면 … 다시 학습 시작하는 거지?")."""

from __future__ import annotations

import json
import os

import pytest

from src.online import round_marker

GONE = 2 ** 22 + 12345          # a process number nothing runs under


def mark(root, pid=GONE, tries=1):
    root.mkdir(parents=True, exist_ok=True)
    (root / round_marker.FILE).write_text(json.dumps({"started": "2026-11-11 22:00:00", "pid": pid, "tries": tries}),
                                          encoding="utf-8")


def test_a_mark_whose_process_is_gone_is_an_unfinished_round(tmp_path):
    root = tmp_path / "online"
    assert not round_marker.unfinished(root)                    # nothing was running
    round_marker.begin(root)
    assert round_marker.read(root)["pid"] == os.getpid() and round_marker.read(root)["tries"] == 1
    assert not round_marker.unfinished(root)                    # it is still running (this process)
    round_marker.end(root)
    assert not round_marker.unfinished(root) and not (root / round_marker.FILE).exists()
    mark(root)
    assert round_marker.unfinished(root)                        # cut off
    round_marker.begin(root)                                    # tried again: counted
    assert round_marker.read(root)["tries"] == 2
    mark(root, tries=round_marker.MAX_TRIES)
    assert not round_marker.unfinished(root)                    # cut off that often: not asked for again


def test_the_app_asks_for_the_cut_off_round_once_when_it_starts(tmp_path):
    from tests.test_use_learning import learning_runtime
    rt = learning_runtime(tmp_path)
    before = rt._learn_request
    rt._use_auto(1e6)
    assert rt._learn_request == before                          # nothing collected, nothing cut off
    mark(tmp_path / "online")
    rt._use_cut_checked = False                                 # (as when the app starts)
    rt._use_auto(1e6)
    assert rt._learn_request == before + 1
    rt._use_auto(2e6)
    assert rt._learn_request == before + 1                      # once


def run_script(monkeypatch, tmp_path, run_update, emit_fails=False):
    pytest.importorskip("torch")
    import builtins
    import scripts.online_update as script
    import src.online.update_job as update_job
    import src.online.verifier as verifier
    monkeypatch.setattr(update_job, "run_update", run_update)
    monkeypatch.setattr(verifier, "train_verifiers", lambda root, emit=None: {})
    if emit_fails:
        def no_listener(*a, **k):
            raise OSError("the app closed: nobody reads the progress")
        monkeypatch.setattr(builtins, "print", no_listener)
    root = tmp_path / "online"
    try:
        code = script.main(["--progress", "--root", str(root), "--use-events", str(tmp_path / "use")])
    except OSError:
        code = "died"
    return code, (root / round_marker.FILE).exists()


def test_the_round_leaves_its_mark_only_when_it_was_cut_off(tmp_path, monkeypatch):
    seen = {}

    def fine(root, **kw):
        seen["mark_while_running"] = round_marker.read(root).get("pid") == os.getpid()
        return {"status": "nothing"}

    assert run_script(monkeypatch, tmp_path, fine) == (0, False) and seen["mark_while_running"]

    def broken(root, **kw):
        raise ValueError("a failure of the round's own")

    assert run_script(monkeypatch, tmp_path, broken) == (1, False)          # shown by the app, not tried over and over

    def cut(root, **kw):
        kw["emit"]("update", step=1)                                         # the app is gone: this print fails
        return {}

    assert run_script(monkeypatch, tmp_path, cut, emit_fails=True) == ("died", True)
    # every round that ended wrote its times; the cut-off one is written when the app notices it
    lines = round_marker.records(tmp_path / "online")
    assert [r["status"] for r in lines] == ["nothing", "error"] and all("stages" in r and r["auto"] for r in lines)
    assert round_marker.read(tmp_path / "online")["stage"] == "update"


def test_without_a_base_model_the_card_says_so_and_the_app_asks_for_one_once(tmp_path):
    """2026-11-11: a fresh copy of the project had no data/online base model; the card said "곧 학습" and nothing began."""
    from types import SimpleNamespace
    from src.qt_dashboard import QtDashboard
    from tests.test_use_learning import learning_runtime
    rt = learning_runtime(tmp_path)
    key = "comp_x@up"
    rt._use_pending, rt._use_new = {key: rt._use_need(key)}, {}
    (tmp_path / "online" / "encoder.json").unlink()                 # no base model
    assert not rt._use_base_ready()
    before, asked = rt._learn_request, getattr(rt, "_base_request", 0)
    rt._use_note()
    card = next(i for i in rt._learn_items if i["key"] == key)
    assert card["state"] == "nobase" and "기본 모델" in card["text"]
    rt._use_auto(1e6)
    rt._use_auto(2e6)
    assert rt._learn_request == before and rt._base_request == asked + 1          # the base model first, asked once
    assert "자동" in next(i for i in rt._learn_items if i["key"] == key)["text"]
    (tmp_path / "online" / "encoder.json").write_text("{}", encoding="utf-8")     # it has been made
    rt._use_auto(3e6)
    assert rt._learn_request == before + 1                                        # now the round
    # the dashboard starts the making script once per request and words its result
    started = []
    job = SimpleNamespace(start=lambda **kw: started.append(kw) or True)
    board = SimpleNamespace(_online_job=lambda: job, online_root=None, learnChanged=SimpleNamespace(emit=lambda: None))
    QtDashboard.auto_base(board, 0)
    QtDashboard.auto_base(board, 1)
    QtDashboard.auto_base(board, 1)
    assert len(started) == 1 and started[0]["command"][-2].endswith("online_make_base.py") and "기본 모델" in board.learn_message
    line, notice = QtDashboard._learn_summary(SimpleNamespace(learn_auto=True, _gesture_name=str), {"status": "base_built"})
    assert "기본 모델을 만들었어요" in line and notice


# ---------------------------------------------------------------------------- times per stage, and what the app makes of them
def test_the_stages_of_a_round_are_timed_from_its_progress_events(tmp_path, monkeypatch):
    clock = {"t": 0.0}
    stages = round_marker.Stages(clock=lambda: clock["t"])
    for event, dt in (("imported", 2.0), ("loading", 0.0), ("update", 30.0), ("update", 5.0), ("checking", 40.0)):
        clock["t"] += dt
        stages.enter(round_marker.STAGE_OF_EVENT[event])
    clock["t"] += 10.0
    stages.enter("verifier")
    clock["t"] += 3.0
    out = stages.result()
    assert out == {"seconds": 90.0, "stages": {"import": 2.0, "prepare": 30.0, "update": 45.0, "check": 10.0, "verifier": 3.0}}

    def fine(root, **kw):
        for event in ("imported", "loading", "update", "checking"):
            kw["emit"](event)
        return {"status": "rejected"}

    assert run_script(monkeypatch, tmp_path, fine) == (0, False)
    rec = round_marker.records(tmp_path / "online")[-1]
    assert rec["status"] == "rejected" and set(rec["stages"]) == set(round_marker.STAGES) and "when" in rec


def times(root, *rounds):
    for r in rounds:
        round_marker.record(root, r)


def finished(seconds, update, verifier=0.0):
    rest = seconds - update - verifier
    return {"seconds": seconds, "status": "promoted", "auto": True,
            "stages": {"import": 1.0, "prepare": rest * .6, "update": update, "check": rest * .4 - 1.0, "verifier": verifier}}


CUT = {"cut": True, "stage": "update", "seconds": 40.0, "tries": 1}


def test_a_cut_off_round_is_written_once_with_where_it_was(tmp_path):
    root = tmp_path / "online"
    mark(root)
    doc = round_marker.read(root)
    doc.update(t0=1000.0, at=1042.5, stage="check")
    (root / round_marker.FILE).write_text(json.dumps(doc), encoding="utf-8")
    assert round_marker.note_cut(root) and not round_marker.note_cut(root)
    rec = round_marker.records(root)
    assert len(rec) == 1 and rec[0]["cut"] and rec[0]["stage"] == "check" and rec[0]["seconds"] == 42.5
    assert round_marker.unfinished(root)                        # still to be started again
    mark(root, pid=os.getpid())
    assert not round_marker.note_cut(root)                      # a round that is running is not a cut-off one


def test_the_app_judges_whether_saving_in_the_middle_would_help(tmp_path):
    kind = lambda root: round_marker.advice(root).get("kind")       # noqa: E731
    a = tmp_path / "a"
    times(a, finished(200, 150), CUT)
    assert round_marker.advice(a) == {}                         # one cut-off round: nothing is said yet
    times(a, CUT)
    out = round_marker.advice(a)
    assert out["kind"] == "checkpoint" and "중간 저장이 필요" in out["text"] and out["seconds"] == 200 and out["resumable"] == 150
    b = tmp_path / "b"                                          # long, but the time is preparing and checking
    times(b, finished(300, 20, 10), CUT, CUT)
    assert kind(b) == "cache" and "준비한 자료" in round_marker.advice(b)["text"]
    c = tmp_path / "c"                                          # a short round: just leave the app open that long
    times(c, finished(40, 30), CUT, CUT)
    assert kind(c) == "keep_open" and "필요 없고" in round_marker.advice(c)["text"]
    d = tmp_path / "d"                                          # nothing ever finished: where the time goes is unknown
    times(d, CUT, CUT)
    assert kind(d) == "unknown"
    e = tmp_path / "e"                                          # the cut-off rounds are long ago: nothing to say
    times(e, CUT, CUT, *[finished(200, 150)] * round_marker.LOOK_BACK)
    assert round_marker.advice(e) == {}


def test_the_running_app_says_its_judgement_once_as_a_notice(tmp_path):
    from types import SimpleNamespace
    from src.qt_dashboard import QtDashboard
    from tests.test_use_learning import learning_runtime
    rt = learning_runtime(tmp_path)
    root = tmp_path / "online"
    times(root, finished(200, 150), CUT)
    mark(root)                                                  # ... and one more cut off just now
    rt._use_cut_checked = False
    rt._use_auto(1e6)
    assert "중간 저장이 필요" in rt._learn_advice and len(round_marker.records(root)) == 3
    said = []
    board = SimpleNamespace(notify=said.append, set_learn_note=lambda note: None, auto_learn=lambda request: None,
                            auto_base=lambda number: None, auto_onnx=lambda number: None, throttle_learning=lambda fps: None, learn_items=[], stage_name="x")
    snap = SimpleNamespace(learn_advice=rt._learn_advice, learn_note="", learn_items=[], learn_request=None, fps=30.0)
    for _ in range(2):
        try:
            QtDashboard.apply_snapshot(board, snap)
        except AttributeError:
            pass                                                # (the rest of the snapshot is not what this test is about)
    assert said == [rt._learn_advice]
