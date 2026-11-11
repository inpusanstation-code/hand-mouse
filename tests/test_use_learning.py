"""Learning while using, steps 2 and 3: which commands a watching model may stop, the use log as training samples, and the
automatic learning round (no camera, fake models)."""
from types import SimpleNamespace

import numpy as np
import pytest

from src import use_gate
from src.use_log import UseLog, read_events
from tests.test_use_log import Gate


def ev(key="right_click", label="thumb_ring", marked="", tcn=None, online=None, **more):
    def verdict(would_pass, model):
        return None if would_pass is None else {"label": label, "would_pass": would_pass, "model": model}
    return {"source": "rule", "key": key, "label": label, "marked": marked, "pc": "pc-a",
            "shadow": verdict(tcn, "tcn:1"), "shadow_online": verdict(online, "online:1"), **more}


def evidence(stop_marked=15, marked=20, stop_meant=1, meant=40, **more):
    return ([ev(marked="f_key", tcn=i >= stop_marked, **more) for i in range(marked)]
            + [ev(tcn=i >= stop_meant, **more) for i in range(meant)])


# ---------------------------------------------------------------- step 2: the decision
def test_a_model_earns_a_command_only_with_enough_marks_and_few_mistakes():
    models = {"tcn": "tcn:1", "online": "online:1"}
    decision = use_gate.decide(evidence(), "pc-a", models)
    assert decision["right_click:thumb_ring"]["model"] == "tcn" and decision["right_click:thumb_ring"]["version"] == "tcn:1"
    assert use_gate.decide(evidence(marked=19), "pc-a", models) == {}                 # too few marks
    assert use_gate.decide(evidence(stop_marked=9), "pc-a", models) == {}             # stops under half of the marked ones
    assert use_gate.decide(evidence(stop_meant=3), "pc-a", models) == {}              # stops 7.5 % of the meant ones


def test_only_this_pc_this_model_file_and_unenforced_commands_count():
    models = {"tcn": "tcn:1", "online": ""}
    assert use_gate.decide(evidence(), "pc-b", models) == {}
    assert use_gate.decide(evidence(), "pc-a", {"tcn": "tcn:2", "online": ""}) == {}  # verdicts of an older file
    assert use_gate.decide(evidence(enforced="tcn"), "pc-a", models) == {}            # those that ran had all passed
    assert use_gate.decide(evidence(gate_on="tcn"), "pc-a", models) == {}
    assert use_gate.decide(evidence(gate_on=True), "pc-a", models) == {}              # a step 1 file


def test_the_model_that_stops_more_marked_commands_gets_it_and_the_file_round_trips(tmp_path):
    both = [dict(e, shadow_online={"label": "thumb_ring", "would_pass": not e["marked"], "model": "online:1"}) for e in evidence()]
    decision = use_gate.decide(both, "pc-a", {"tcn": "tcn:1", "online": "online:1"})
    assert decision["right_click:thumb_ring"]["model"] == "online"                    # 20/20 against 15/20
    use_gate.save(tmp_path / "x" / "gate.json", decision)
    assert use_gate.load(tmp_path / "x" / "gate.json") == decision and use_gate.load(tmp_path / "none.json") == {}


# ---------------------------------------------------------------- step 2: the runtime
class Watcher(Gate):
    classes = ["none", "thumb_index"]

    def step(self, now, hand, aspect):
        pass

    def reset(self):
        pass


def click(rt):
    from tests.test_virtual_hand import pinch_hand
    opened = pinch_hand(rt)
    rt._step(); rt._step()
    rt.tracker.hand[:] = opened
    rt._step()


def test_an_earned_command_is_stopped_when_its_model_says_no_and_runs_when_it_says_yes(tmp_path):
    from tests.test_virtual_hand import box_runtime
    rt = box_runtime(tmp_path)
    rt._watchers["tcn"] = Watcher(ok=False)
    rt._step()
    rt._use_gate = {"left_click:thumb_index": {"model": "tcn", "version": rt._model_version("tcn")}}
    click(rt)
    assert "left_click" not in rt.mouse.event_log and rt.use_blocked == 1 and "실행하지 않았어요" in rt._status
    rt._watchers["tcn"].ok = True
    rt._step()
    click(rt)
    assert rt.mouse.event_log.count("left_click") == 1
    rt.use_log.close()
    (event,) = read_events(tmp_path / "use_events")
    assert event["enforced"] == "tcn" and event["shadow"]["would_pass"] is True


def test_a_decision_earned_by_another_model_file_stops_nothing(tmp_path):
    from tests.test_virtual_hand import box_runtime
    rt = box_runtime(tmp_path)
    rt._watchers["tcn"] = Watcher(ok=False)
    rt._step()
    rt._use_gate = {"left_click:thumb_index": {"model": "tcn", "version": "tcn:1"}}
    click(rt)
    assert rt.mouse.event_log.count("left_click") == 1 and rt.use_blocked == 0


def test_the_runtime_takes_the_decision_from_its_own_log(tmp_path):
    from tests.test_virtual_hand import box_runtime
    rt = box_runtime(tmp_path)
    version = rt._model_version("tcn")
    log = UseLog(tmp_path / "use_events", pc=rt_pc(rt), background=False)
    for i in range(60):
        marked = i < 20
        log.event("rule", "left_click", float(i), label="thumb_index",
                  shadow={"label": "thumb_index", "would_pass": not marked, "model": version})
        if marked:
            log.mark_last(i + .1)
    log.close()
    rt._step()                                              # the log starts: the decision is read (in tests without a thread)
    assert rt._use_gate["left_click:thumb_index"]["model"] == "tcn" and "확인해요" in rt._status
    assert use_gate.load(tmp_path / "use_events" / "gate.json") == rt._use_gate


def rt_pc(rt):
    from src.recorder import machine_info
    return machine_info(str(rt.engine.config.get("pc_alias", "")))["pc"]


# ---------------------------------------------------------------- step 3: asking for a round
def learning_runtime(tmp_path):
    from tests.test_virtual_hand import box_runtime
    rt = box_runtime(tmp_path)
    rt.engine.config["online_learning_enabled"] = True
    (tmp_path / "online").mkdir(exist_ok=True)
    (tmp_path / "online" / "encoder.json").write_text("{}", encoding="utf-8")
    rt._online_root = tmp_path / "online"
    rt._use_names["comp_x"] = "거꾸로 V 유지"
    from src.action_bindings import get_action_registry
    get_action_registry().composite_gestures["comp_x"] = {"key": "comp_x", "name": "거꾸로 V 유지"}   # it exists (not deleted)
    rt._step()
    return rt


def test_uses_of_a_taught_gesture_are_counted_shown_and_start_a_round_at_twenty(tmp_path):
    rt = learning_runtime(tmp_path)
    t = rt._use_t
    for i in range(19):
        rt._use_event("binding", "comp_x", t + i)
    assert rt._use_pending == {"comp_x@up": 19} and "'거꾸로 V 유지 · ↑ 위쪽' 사용 사례를 모으는 중 19/20" in rt._learn_note
    rt._use_event("rule", "left_click", t + 19.5, label="thumb_index")      # not a taught gesture: not counted
    rt._use_auto(t + 40)
    assert rt._learn_request == 0
    rt._use_event("binding", "comp_x", t + 50)
    assert "20개가 모였어요" in rt._learn_note
    rt._use_auto(t + 52)
    assert rt._learn_request == 0                           # right after a command: its mark may still come
    rt._use_auto(t + 57)
    assert rt._learn_request == 1 and rt._use_pending["comp_x@up"] == 0
    rt._step()
    assert rt._snap.learn_request == (1, str(tmp_path / "use_events"))
    for i in range(20):
        rt._use_event("binding", "comp_x", t + 60 + i)
    rt._use_auto(t + 100)
    assert rt._learn_request == 1                           # not again within the cooldown
    rt._use_auto(t + 700)
    assert rt._learn_request == 2
    rt.engine.config["auto_learn"] = False
    for i in range(20):
        rt._use_event("binding", "comp_x", t + 800 + i)
    rt._use_auto(t + 2000)
    assert rt._learn_request == 2


def test_marks_alone_start_a_round_and_the_count_survives_a_restart(tmp_path):
    from src.online.use_import import pending_counts
    rt = learning_runtime(tmp_path)
    t = rt._use_t
    for i in range(5):
        rt._use_event("rule", "left_click", t + i, label="thumb_index")
        rt._use_mark(t + i + .1, "f_key")
    rt._use_auto(t + 20)
    assert rt._learn_request == 1                           # five commands marked as not meant
    for i in range(3):
        rt._use_event("binding", "comp_x", t + 30 + i)
    rt._use_event("binding", "comp_x", t + 34)
    rt._use_mark(t + 34.1, "f_key")                         # a marked use is not an example
    rt._use_event("binding", "seq_a", t + 36)               # a sequence does not fit the model's window
    rt.use_log.close()
    assert pending_counts(tmp_path / "use_events", tmp_path / "online") == {"comp_x@up": 3}   # per hand direction
    again = learning_runtime(tmp_path)                      # the app starts again: counted from the log
    assert again._use_pending == {"comp_x@up": 3} and "3/20" in again._learn_note
    from src.action_bindings import get_action_registry
    del get_action_registry().composite_gestures["comp_x"]  # the gesture is deleted: its old uses are not counted any more
    from tests.test_virtual_hand import box_runtime
    rt2 = box_runtime(tmp_path)
    rt2.engine.config["online_learning_enabled"] = True
    rt2._online_root = tmp_path / "online"
    rt2._step()
    assert rt2._use_pending == {} and rt2._learn_note == ""


def test_a_taught_gesture_with_a_checking_model_is_named_checked_and_let_through_on_the_third_try(tmp_path):
    rt = learning_runtime(tmp_path)
    (tmp_path / "online" / "versions").mkdir(exist_ok=True)
    (tmp_path / "online" / "versions" / "production.pt").write_bytes(b"x")

    class Online(Watcher):
        classes = ["none", "comp_x@up"]
        verifiers = {"comp_x@up": SimpleNamespace(created=7.0)}                # the model of the hand pointing up

    rt._watchers["online"] = Online(ok=False)
    rt._step()
    rt._use_note()
    assert "TCN이 확인하는 자세: 거꾸로 V 유지 · ↑ 위쪽" in rt._learn_note
    assert rt._model_version("online", "comp_x@up").endswith("+v7") and "+v" not in rt._model_version("online", "thumb_ring")
    t = rt._use_t
    assert not rt._use_allows("comp_x", t) and rt.use_blocked == 1 and "거꾸로 V 유지" in rt._status
    ok, badge = rt._run_resolved(None, {"gesture_key": "comp_x", "action_type": "hotkey", "action_value": "x"})
    assert not ok and "의도한 동작" in badge and rt.use_blocked == 2
    assert rt._use_allows("comp_x", t + 2)                  # the third try within a few seconds: the person means it
    rt._use_event("binding", "comp_x", t + 2)
    assert not rt._use_allows("comp_x", t + 30)             # long after: counted from one again
    rt._watchers["online"].ok = True
    assert rt._use_allows("comp_x", t + 31)
    rt._use_event("binding", "comp_x", t + 31)
    rt._watchers["online"].ok = False
    rt.engine.config["taught_verifier_enforce"] = False     # watching only
    assert rt._use_allows("comp_x", t + 40)
    rt.use_log.close()
    first, second = read_events(tmp_path / "use_events", frames=False)
    assert first["forced"] is True and first["enforced"] == "online" and first["shadow_online"]["would_pass"] is False
    assert second["forced"] is False and second["shadow_online"]["model"].endswith("+v7")
    # a taught gesture without a checking model: stopped only once a watching model earned it (src/use_gate.py)
    rows = [dict(source="binding", key="comp_x", label="", marked="f_key" if i < 20 else "", pc="p",
                 shadow_online={"label": "comp_x", "would_pass": i >= 20, "model": "online:1"}) for i in range(60)]
    assert use_gate.decide(rows, "p", {"tcn": "", "online": "online:1"})["comp_x:comp_x"]["model"] == "online"


def test_the_dashboard_starts_one_round_per_request_and_shows_what_it_is_doing(tmp_path):
    import time

    from src.qt_dashboard import QtDashboard
    started = []
    job = SimpleNamespace(start=lambda **kw: started.append(kw) or True, running=True)
    board = SimpleNamespace(_online_job=lambda: job, online_job=job, learn_message="", learnChanged=SimpleNamespace(emit=lambda: None))
    banner = lambda: QtDashboard.learnBanner.fget(board)   # noqa: E731
    QtDashboard.set_learn_note(board, "'거꾸로 V 유지' 사용 사례를 모으는 중 3/20")
    assert banner().startswith("'거꾸로 V 유지'")              # collecting: the runtime's line
    auto = QtDashboard.auto_learn
    auto(board, (0, "logs"))
    auto(board, (1, "logs"))
    auto(board, (1, "logs"))
    auto(board, None)
    assert started == [{"use_events": "logs"}] and "자동" in board.learn_message
    assert banner().startswith("자동 학습 · ")                 # a round is running: its progress
    job.running = False
    board.learn_banner_until = time.time() + 100
    board.learn_message = "새 모델을 반영했어요."
    assert banner() == "자동 학습 · 새 모델을 반영했어요."       # the result stays for a while
    board.learn_banner_until = 0.0
    assert banner().startswith("'거꾸로 V 유지'")


def test_the_job_passes_the_log_folder_to_the_learning_script(tmp_path, monkeypatch):
    import subprocess

    from src.online.app_job import OnlineJob
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(OSError("not started in tests")))
    job = OnlineJob(tmp_path)
    assert not job.start(use_events="logs/use_events", weak=False)
    assert job.last_args[-3:] == ["--use-events", "logs/use_events", "--no-weak"]
    job.state = {"phase": "imported"}
    assert job.running


# ---------------------------------------------------------------- step 3: the log as samples, and a round that learns from it
def write_log(folder, frames_of, n_marked=4, n_meant=6, n_taught=0, label="thumb_index", name=None):
    """Commands at 3 s intervals: `n_marked` marked rule commands, `n_meant` unmarked ones, then `n_taught` uses of the taught
    gesture "comp_new" (the hand makes the "new" shape). frames_of(kind, seed) -> recording-style frames."""
    log = UseLog(folder, pc="pc-test", background=False)
    if name:
        log._path = folder / name
        folder.mkdir(parents=True, exist_ok=True)
    t = 0.0
    for i in range(n_marked + n_meant + n_taught):
        marked, taught = i < n_marked, i >= n_marked + n_meant
        for f in frames_of("none" if marked else "new" if taught else label, seed=i):
            lm = np.asarray(f["lm"], dtype=float)
            hand = SimpleNamespace(landmarks=[SimpleNamespace(x=p[0], y=p[1], z=p[2]) for p in lm],
                                   world=np.asarray(f["world"], dtype=float).tolist())
            log.frame(t + f["t"], hand)
        at = t + 1.2
        if taught:
            log.event("binding", "comp_new", at)
        else:
            log.event("rule", "scroll_grab", at, label=label, shadow=None)
        if marked:
            log.mark_last(at + .2)
        t += 3.0
    log.event("binding", "seq_long", t - 1.5)               # a sequence: not something the model's window can hold
    log.close()


def counts(**kw):
    return {"negatives": 0, "weak": 0, "taught": 0, "waiting": 0, "skipped": 0, "new_classes": [], **kw}


def test_marked_commands_become_none_and_unmarked_ones_weak_examples_once(tmp_path):
    pytest.importorskip("torch")
    from src.online.samples import PSEUDO_CANDIDATE, VALIDATED_PSEUDO, SampleStore
    from src.online.use_import import import_events
    from tests.test_online_update import frames
    write_log(tmp_path / "use", frames)
    store = SampleStore(tmp_path / "online")
    assert import_events(store, tmp_path / "use", ["none", "thumb_index"]) == counts(negatives=4, weak=6, skipped=1)
    negatives = store.samples(sources=[VALIDATED_PSEUDO])
    assert {s.label for s in negatives} == {"none"} and {s.label for s in store.samples(sources=[PSEUDO_CANDIDATE])} == {"thumb_index"}
    one = negatives[0]
    assert one.extra["origin"] == "use_event" and one.extra["marked"] == "f_key" and one.suggested_label == "thumb_index"
    assert 0 < one.extra["context_frames"] < one.frames and one.session.startswith("use-") and one.pc == "pc-test"
    assert import_events(store, tmp_path / "use", ["none", "thumb_index"]) == counts()
    assert len(store.samples()) == 10
    # a model without the gesture's class takes only the marked ones
    other = SampleStore(tmp_path / "online2")
    assert import_events(other, tmp_path / "use", ["none", "thumb_ring"]) == counts(negatives=4, skipped=7)


def test_a_taught_gesture_waits_in_the_log_until_it_has_enough_uses_then_becomes_a_class(tmp_path):
    pytest.importorskip("torch")
    from src.online.samples import PSEUDO_CANDIDATE, SampleStore
    from src.online.use_import import import_events, pending_counts
    from tests.test_online_update import frames
    write_log(tmp_path / "use", frames, n_marked=0, n_meant=0, n_taught=12, name="20261111-000001-pc.jsonl")
    store = SampleStore(tmp_path / "online")
    classes = ["none", "thumb_index"]
    assert import_events(store, tmp_path / "use", classes) == counts(waiting=12, skipped=1)
    assert store.samples() == [] and pending_counts(tmp_path / "use", store.root) == {"comp_new@down": 12}
    assert import_events(store, tmp_path / "use", classes) == counts(waiting=12)      # still waiting: read again, nothing lost
    write_log(tmp_path / "use", frames, n_marked=0, n_meant=0, n_taught=9, name="20261111-000002-pc.jsonl")
    out = import_events(store, tmp_path / "use", classes)
    assert out == counts(taught=21, skipped=1, new_classes=["comp_new@down"])                # 12 + 9: both files' uses go in
    taught = store.samples(sources=[PSEUDO_CANDIDATE])
    assert len(taught) == 21 and {s.label for s in taught} == {"comp_new@down"} and all(s.extra["taught"] for s in taught)
    assert pending_counts(tmp_path / "use", store.root) == {} and import_events(store, tmp_path / "use", classes) == counts()


def hands(frames_list, start=0.0):
    for f in frames_list:
        lm = np.asarray(f["lm"], dtype=float)
        yield start + f["t"], SimpleNamespace(landmarks=[SimpleNamespace(x=p[0], y=p[1], z=p[2]) for p in lm],
                                              world=np.asarray(f["world"], dtype=float).tolist(), score=1.0)


def test_a_taught_gesture_gets_its_own_checking_model_and_the_models_gestures_stay_as_they_were(tmp_path):
    torch = pytest.importorskip("torch")
    from src.online.safety import OnlineGate
    from src.online.verifier import encoder_fingerprint, load_verifiers, train_verifiers
    from src.online.versions import ModelManager
    from tests.test_online_update import CLASSES, fast, frames, make_root
    from src.online.verifier import read_status
    root, store = make_root(tmp_path)
    write_log(tmp_path / "use", frames, n_marked=0, n_meant=0, n_taught=20, name="20261111-000001-pc.jsonl")
    out = fast(root, use_events=tmp_path / "use")
    assert out["imported"]["taught"] == 20 and out["status"] == "nothing"          # the uses are stored, the model learns nothing
    before = ModelManager(root).load()
    first = train_verifiers(root)["comp_new@down"]
    assert (first["status"], first["reason"], first["uses"], first["newest_day"]) == ("waiting", "one_day", 20, "20261111")
    assert load_verifiers(root) == {} and read_status(root)["comp_new@down"]["status"] == "waiting"   # one day: nothing to test it on
    write_log(tmp_path / "use", frames, n_marked=0, n_meant=0, n_taught=6, name="20261112-000001-pc.jsonl")
    assert fast(root, use_events=tmp_path / "use")["imported"]["taught"] == 6
    report = train_verifiers(root)["comp_new@down"]                                     # the second day's uses are the test
    assert report["status"] == "saved" and report["uses"] == 26 and report["held"] == 6 and report["days"] == 2
    assert report["recall"] >= .8 and read_status(root)["comp_new@down"]["status"] == "saved"
    after = ModelManager(root).load()
    assert after["info"]["classes"] == CLASSES and all(torch.equal(before["state"][k], after["state"][k]) for k in before["state"])
    verifier = load_verifiers(root, encoder_fingerprint(after["state"]))["comp_new@down"]
    assert verifier.uses == 26 and verifier.metrics["test"] == "newest_day" and load_verifiers(root, "another-encoder") == {}
    # in the app: the gate answers for the gesture's key from its checking model
    gate = OnlineGate(root, {})
    assert gate.classes == CLASSES + ["comp_new@down"] and gate.thresholds["comp_new@down"] == verifier.threshold
    for t, hand in hands(frames("new", n=60, seed=99)):
        gate.step(t, hand, 720 / 1280)
    assert gate.confirmed("comp_new@down", 59 / 30)
    gate.reset()
    for t, hand in hands(frames("none", n=60, seed=98), start=10.0):
        gate.step(t, hand, 720 / 1280)
    assert not gate.confirmed("comp_new@down", 10 + 59 / 30)
    # used more: the next round trains it again from all the uses; with nothing new it is left alone
    assert train_verifiers(root)["comp_new@down"]["status"] == "kept"
    write_log(tmp_path / "use", frames, n_marked=0, n_meant=0, n_taught=5, name="20261113-000001-pc.jsonl")
    assert fast(root, use_events=tmp_path / "use")["imported"]["taught"] == 5
    again = train_verifiers(root)["comp_new@down"]                                      # tested on the third day now
    assert again["status"] == "saved" and again["uses"] == 31 and again["held"] == 5 and load_verifiers(root)["comp_new@down"].uses == 31


def test_a_checking_model_that_fails_its_test_is_not_saved(tmp_path):
    pytest.importorskip("torch")
    from src.online.verifier import load_verifiers, train_verifiers
    from tests.test_online_update import fast, frames, make_root
    root, store = make_root(tmp_path)
    # the "taught gesture" is the hand doing nothing: it cannot be told from the recordings of doing nothing
    nothing = lambda kind, seed: frames("none", seed=seed + 50)   # noqa: E731
    write_log(tmp_path / "use", nothing, n_marked=0, n_meant=0, n_taught=20, name="20261111-000001-pc.jsonl")
    write_log(tmp_path / "use", nothing, n_marked=0, n_meant=0, n_taught=6, name="20261112-000001-pc.jsonl")
    fast(root, use_events=tmp_path / "use")
    report = train_verifiers(root)["comp_new@down"]
    assert report["status"] == "rejected" and report["reason"] in ("fires_on_other_things", "misses_uses")
    assert load_verifiers(root) == {}


def test_a_gesture_waiting_for_another_day_says_so_and_is_tested_after_a_few_uses_on_that_day(tmp_path):
    import time
    rt = learning_runtime(tmp_path)
    t = rt._use_t
    rt._use_status = {"comp_x@up": {"status": "waiting", "reason": "one_day", "uses": 20, "newest_day": time.strftime("%Y%m%d")}}
    for i in range(4):
        rt._use_event("binding", "comp_x", t + i)
    assert "'거꾸로 V 유지 · ↑ 위쪽' 사용 사례 24개 저장됨 · 다른 날에도 쓰면" in rt._learn_note and "모으는 중" not in rt._learn_note
    rt._use_auto(t + 20)
    assert rt._learn_request == 0                           # still the same day: more uses today change nothing
    rt._use_status["comp_x@up"]["newest_day"] = "20200101"     # the stored uses are from an earlier day
    rt._use_auto(t + 21)
    assert rt._learn_request == 1                           # four uses on a new day are enough to test it


def test_the_dashboard_words_what_happened_to_a_checking_model():
    from src.qt_dashboard import QtDashboard
    board = SimpleNamespace(_gesture_name=lambda key: "거꾸로 V 유지")
    words = lambda reports: QtDashboard._verifier_words(board, reports)   # noqa: E731
    assert "하루치뿐이라" in words({"comp_x": {"status": "waiting", "reason": "one_day", "uses": 20}})
    saved = words({"comp_x": {"status": "saved", "recall": 1.0, "held": 6, "false_rate": .016}})
    assert "가장 최근 날의 사용 6/6번 인식" in saved and "1.6%" in saved
    assert "아직 쓰지 않아요" in words({"comp_x": {"status": "rejected", "reason": "misses_uses", "recall": .5, "false_rate": .01}})


def test_a_round_imports_the_log_and_learns_from_it_without_new_classes(tmp_path):
    pytest.importorskip("torch")
    from src.online.versions import ModelManager
    from tests.test_online_update import CLASSES, fast, frames, make_root
    root, store = make_root(tmp_path)
    assert fast(root)["status"] == "nothing"                # no corrections: nothing to learn without the log
    write_log(tmp_path / "use", frames)
    events = []
    out = fast(root, use_events=tmp_path / "use", emit=lambda e, **k: events.append(e))
    assert out["imported"] == counts(negatives=4, weak=6, skipped=1) and "imported" in events
    assert out["status"] in ("promoted", "rejected") and out["updates"] >= 20 and out["new_classes"] == []
    assert ModelManager(root).load()["info"]["classes"] == CLASSES
    only_marked = fast(root, use_events=tmp_path / "use", weak=False)
    assert only_marked["status"] in ("promoted", "rejected", "rolled_back") and only_marked["imported"]["weak"] == 0


def test_a_click_is_classed_by_mode_fingers_and_kind_and_a_kind_gets_its_own_model_only_with_enough_uses(tmp_path):
    """2026-11-11: "어떤 모드의, 어떤 식의 좌클릭인지도 세부 분류해서", "필요하다면 멀티 TCN을 … 앱이 알아서 구성"."""
    pytest.importorskip("torch")
    from src.online.samples import PSEUDO_CANDIDATE, SampleStore
    from src.online.use_import import (DOUBLE, click_base, click_key, click_kinds, click_name, click_parts, import_events,
                                       pending_counts, split_click_kinds)
    from src.online.verifier import read_status, train_verifiers
    from tests.test_online_update import fast, frames, make_root
    assert click_key("rule", "left_click", "thumb_index") == "left_click:thumb_index"
    assert click_key("rule", "left_click", "thumb_index", DOUBLE) == "left_click:thumb_index:double"
    assert click_key("rule", "right_click", "thumb_ring", DOUBLE) == "right_click:thumb_ring"        # only a left click doubles
    assert click_key("pointer", "left_click", "thumb_index") == "" and click_parts("comp_x") == ("", "", "")
    assert click_base("left_click:thumb_index:double") == "left_click:thumb_index" == click_base("left_click:thumb_index")
    assert click_name("left_click:thumb_index:double") == "좌클릭 · 가상 손 (엄지+검지) · 더블클릭의 두 번째"
    assert click_name("right_click:thumb_ring") == "우클릭 · 손바닥 모드 (엄지+약지)"
    # the kind the app logged wins; without one, a left click within .7 s of the one before is the second tap
    events = [{"id": 1, "key": "left_click", "source": "rule", "t": 1.0}, {"id": 2, "key": "left_click", "source": "rule", "t": 1.4},
              {"id": 3, "key": "left_click", "source": "rule", "t": 3.0, "click_kind": "double"},
              {"id": 4, "key": "right_click", "source": "rule", "t": 3.2}, {"id": 5, "key": "left_click", "source": "rule", "t": 3.3, "click_kind": ""}]
    assert click_kinds(events) == {1: "", 2: "double", 3: "double", 5: ""}

    def log_clicks(name, singles, doubles):
        log = UseLog(tmp_path / "use", pc="pc-test", background=False)
        log._path = tmp_path / "use" / name
        (tmp_path / "use").mkdir(parents=True, exist_ok=True)
        t = 0.0
        for i in range(singles + doubles):
            for f in frames("thumb_index", seed=i):
                lm = np.asarray(f["lm"], dtype=float)
                log.frame(t + f["t"], SimpleNamespace(landmarks=[SimpleNamespace(x=p[0], y=p[1], z=p[2]) for p in lm],
                                                      world=np.asarray(f["world"], dtype=float).tolist()))
            log.event("rule", "left_click", t + 1.2, label="thumb_index", extra={"virtual": True})          # no kind logged:
            if i >= singles:                                                                                 # worked out from the time
                log.event("rule", "left_click", t + 1.45, label="thumb_index", extra={"virtual": True})
            t += 3.0
        log.close()

    root, store = make_root(tmp_path)
    log_clicks("20261111-000001-pc.jsonl", singles=22, doubles=5)
    assert pending_counts(tmp_path / "use", root) == {"left_click:thumb_index": 27, "left_click:thumb_index:double": 5}
    fast(root, use_events=tmp_path / "use")
    store = SampleStore(root)
    kinds = [s.extra.get("kind") for s in store.samples(sources=[PSEUDO_CANDIDATE]) if s.extra.get("click")]
    assert kinds.count("double") == 5 and kinds.count("") == 27
    # clicks stored before the kind was kept get it from the log they came from
    for s in store.samples(sources=[PSEUDO_CANDIDATE]):
        s.extra.pop("kind", None)
    assert split_click_kinds(store, tmp_path / "use") == 32
    assert [s.extra["kind"] for s in store.samples(sources=[PSEUDO_CANDIDATE]) if s.extra.get("click")].count("double") == 5
    # five second taps are too few for a model of their own: learned with the plain click's (one model, 32 uses)
    train_verifiers(root)
    status = read_status(root)
    assert set(status) == {"left_click:thumb_index"} and status["left_click:thumb_index"]["uses"] == 32
    # another day brings enough second taps: now the app sets up two models by itself
    log_clicks("20261112-000001-pc.jsonl", singles=6, doubles=20)
    fast(root, use_events=tmp_path / "use")
    reports = train_verifiers(root)
    assert set(reports) == {"left_click:thumb_index", "left_click:thumb_index:double"}
    assert reports["left_click:thumb_index:double"]["uses"] == 25 and reports["left_click:thumb_index"]["uses"] == 27 + 26


def test_the_runtime_logs_the_kind_of_click_and_asks_the_kinds_model_only_when_there_is_one(tmp_path):
    from tests.test_virtual_hand import box_runtime
    rt = box_runtime(tmp_path)
    rt._step()
    click(rt)
    rt._step()                                              # the fingers stay open for a frame
    click(rt)                                               # right after: the second tap of a double click
    rt.use_log.close()
    first, second = read_events(tmp_path / "use_events", frames=False)
    assert (first["key"], first["click_kind"], second["click_kind"]) == ("left_click", "", "double")
    assert rt._use_pending == {"left_click:thumb_index": 1, "left_click:thumb_index:double": 1}
    assert rt._use_name("left_click:thumb_index:double") == "좌클릭 · 가상 손 (엄지+검지) · 더블클릭의 두 번째"
    # no model for the kind yet: the plain click's answers; once there is one, it does
    assert rt._click_model("left_click:thumb_index:double") == "left_click:thumb_index"
    rt._use_watchers = {"online": SimpleNamespace(verifiers={"left_click:thumb_index:double": object()})}
    assert rt._click_model("left_click:thumb_index:double") == "left_click:thumb_index:double"
