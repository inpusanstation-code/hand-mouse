"""Left / right clicks get their own checking model, learned from the person's clicks (2026-11-11).

The person: "좌우클릭 판정은 카메라 각도에 따라서 pinch위치가 아니라도 pinch 위치인것처럼 보여서 오판정이 자주 나는데" ->
"[시간 흐름으로 판단하는] 방법으로 하고, 좌우 클릭의 맥락 데이터도 모아서 tcn으로 자동학습하도록 만들게 하자".
The clicks were already logged with what the hand did before and after (src/use_log.py); what was missing is a model that
learns from them. It is the taught gestures' checking model (src/online/verifier.py), keyed "<action>:<model label>".
"""
from types import SimpleNamespace

import numpy as np
import pytest

from src.use_log import UseLog, read_events
from tests.test_use_learning import Watcher, click, hands, learning_runtime

KEY = "left_click:thumb_index"


def write_clicks(folder, frames_of, name, clicks=0, marked=0, action="left_click", label="thumb_index"):
    """`clicks` real clicks (the hand pinches) and `marked` ones the person marked as not meant (the hand does nothing)."""
    log = UseLog(folder, pc="pc-test", background=False)
    folder.mkdir(parents=True, exist_ok=True)
    log._path = folder / name
    t = 0.0
    for i in range(clicks + marked):
        wrong = i >= clicks
        kind = "none" if wrong else label if label == "thumb_index" else "new"     # (the test hands: none / thumb_index / new)
        for f in frames_of(kind, seed=i + (1000 if wrong else 0)):
            lm = np.asarray(f["lm"], dtype=float)
            log.frame(t + f["t"], SimpleNamespace(landmarks=[SimpleNamespace(x=p[0], y=p[1], z=p[2]) for p in lm],
                                                  world=np.asarray(f["world"], dtype=float).tolist()))
        log.event("rule", action, t + 1.2, label=label, shadow=None)
        if wrong:
            log.mark_last(t + 1.4)
        t += 3.0
    log.close()


def test_clicks_are_kept_for_their_checking_model_even_without_a_class_and_counted(tmp_path):
    pytest.importorskip("torch")
    from src.online.samples import PSEUDO_CANDIDATE, VALIDATED_PSEUDO, SampleStore
    from src.online.use_import import click_key, import_events, pending_counts
    from tests.test_online_update import frames
    assert click_key("rule", "left_click", "thumb_index") == KEY and click_key("rule", "scroll_grab", "thumb_index") == ""
    assert click_key("binding", "left_click", "thumb_index") == "" and click_key("rule", "left_click", "") == ""
    use = tmp_path / "use"
    write_clicks(use, frames, "20261111-000001-pc.jsonl", clicks=5, marked=2)
    write_clicks(use, frames, "20261111-000002-pc.jsonl", clicks=3, action="right_click", label="thumb_index_middle")
    store = SampleStore(tmp_path / "online")
    assert pending_counts(use, store.root) == {KEY: 5, "right_click:thumb_index_middle": 3}      # the marked ones are not uses
    out = import_events(store, use, ["none", "thumb_index"])        # the model has no class for the right click's gesture
    assert (out["weak"], out["negatives"], out["skipped"]) == (8, 2, 0)
    kept = store.samples(sources=[PSEUDO_CANDIDATE])
    assert sorted({s.label for s in kept}) == ["thumb_index", "thumb_index_middle"] and all(s.extra["click"] for s in kept)
    assert all(not s.extra["click"] and s.extra["key"] == "left_click" for s in store.samples(sources=[VALIDATED_PSEUDO]))
    assert pending_counts(use, store.root) == {}
    # a log read before clicks were kept (its state has no "clicks" mark): the dropped clicks are taken on the next reading
    import json
    old = SampleStore(tmp_path / "online_old")
    write_clicks(tmp_path / "use_old", frames, "20261110-000001-pc.jsonl", clicks=4, action="right_click", label="thumb_index_middle")
    size = (tmp_path / "use_old" / "20261110-000001-pc.jsonl").stat().st_size
    (old.root / "use_import.json").write_text(json.dumps({"20261110-000001-pc.jsonl": {"size": size, "ids": [1, 2, 3, 4],
                                                                                       "waiting": False}}), encoding="utf-8")
    assert import_events(old, tmp_path / "use_old", ["none", "thumb_index"])["weak"] == 4
    assert import_events(old, tmp_path / "use_old", ["none", "thumb_index"])["weak"] == 0 and len(old.samples()) == 4


def test_a_click_gets_a_checking_model_from_the_persons_clicks_and_the_marked_ones(tmp_path):
    torch = pytest.importorskip("torch")
    from src.online.safety import OnlineGate
    from src.online.verifier import load_verifiers, train_verifiers
    from src.online.versions import ModelManager
    from tests.test_online_update import CLASSES, fast, frames, make_root
    root, store = make_root(tmp_path)                    # guided recordings of every class, "thumb_index" among them
    use = tmp_path / "use"
    write_clicks(use, frames, "20261111-000001-pc.jsonl", clicks=20, marked=3)
    out = fast(root, use_events=use)
    assert out["imported"]["weak"] == 20 and out["imported"]["negatives"] == 3
    before = ModelManager(root).load()
    first = train_verifiers(root)[KEY]
    assert (first["status"], first["reason"], first["uses"]) == ("waiting", "one_day", 20)      # one day: nothing to test it on
    write_clicks(use, frames, "20261112-000001-pc.jsonl", clicks=6, marked=2)
    fast(root, use_events=use)
    report = train_verifiers(root)[KEY]
    # saved: the guided recordings of the same pinch are not held against it (as "no" examples it could not pass)
    assert report["status"] == "saved" and report["uses"] == 26 and report["held"] == 6 and report["marked"] == 5
    # the model's classes stay as they were (clicks of a gesture it knows are also its weak examples, as before)
    assert ModelManager(root).load()["info"]["classes"] == CLASSES == before["info"]["classes"]
    verifier = load_verifiers(root)[KEY]
    assert verifier.uses == 31 and verifier.metrics["marked"] == 5
    gate = OnlineGate(root, {})
    assert KEY in gate.classes
    for t, hand in hands(frames("thumb_index", n=60, seed=99)):
        gate.step(t, hand, 720 / 1280)
    assert gate.confirmed(KEY, 59 / 30)
    gate.reset()
    for t, hand in hands(frames("none", n=60, seed=98), start=10.0):
        gate.step(t, hand, 720 / 1280)
    assert not gate.confirmed(KEY, 10 + 59 / 30)
    # nothing new: left alone; one more marked click: trained again
    assert train_verifiers(root)[KEY]["status"] == "kept"
    write_clicks(use, frames, "20261112-000002-pc.jsonl", marked=1)
    fast(root, use_events=use)
    assert train_verifiers(root)[KEY]["status"] == "saved" and load_verifiers(root)[KEY].metrics["marked"] == 6


def test_a_click_its_model_does_not_see_is_stopped_and_goes_through_on_the_third_try(tmp_path):
    rt = learning_runtime(tmp_path)
    (tmp_path / "online" / "versions").mkdir(exist_ok=True)
    (tmp_path / "online" / "versions" / "production.pt").write_bytes(b"x")

    class Online(Watcher):
        classes = ["none", KEY]
        verifiers = {KEY: SimpleNamespace(created=7.0)}

    rt._watchers["online"] = Online(ok=False)
    rt._step()
    rt._use_note()
    assert "TCN이 확인하는 자세: 좌클릭" in rt._learn_note or "클릭" in rt._learn_note
    rt._step()
    click(rt)
    assert "left_click" not in rt.mouse.event_log and rt.use_blocked == 1 and "실행하지 않았어요" in rt._status
    rt._step()
    click(rt)
    assert "left_click" not in rt.mouse.event_log and rt.use_blocked == 2
    click(rt)                                               # the third try within a few seconds: the person means it
    assert rt.mouse.event_log.count("left_click") == 1
    rt._watchers["online"].ok = True
    rt._step()
    click(rt)
    assert rt.mouse.event_log.count("left_click") == 2
    rt._watchers["online"].ok = False
    rt.engine.config["click_verifier_enforce"] = False      # watching only
    rt._step()
    click(rt)
    assert rt.mouse.event_log.count("left_click") == 3
    rt.use_log.close()
    events = [e for e in read_events(tmp_path / "use_events", frames=False) if e["key"] == "left_click"]
    assert [e.get("forced") for e in events[:2]] == [True, False] and events[0]["enforced"] == "online"
    assert "forced" not in events[2] or events[2]["forced"] is False


def test_clicks_are_counted_on_the_main_screen_and_start_a_round_at_forty(tmp_path):
    rt = learning_runtime(tmp_path)
    t = rt._use_t
    for i in range(39):
        rt._use_event("rule", "left_click", t + i, label="thumb_index")
    assert rt._use_pending[KEY] == 39 and "모으는 중 39/40" in rt._learn_note and "F8(어느 창에서든)을 누르면" in rt._learn_note
    asked = rt._learn_request
    rt._use_auto(t + 200)
    assert rt._learn_request == asked                       # 39: not yet (a taught gesture asks at 20)
    rt._use_event("rule", "left_click", t + 201, label="thumb_index")
    rt._use_auto(t + 400)
    assert rt._learn_request == asked + 1 and rt._use_pending[KEY] == 0
    rt._use_event("rule", "scroll_grab", t + 401, label="thumb_index")     # not a click: not counted
    assert rt._use_pending[KEY] == 0
