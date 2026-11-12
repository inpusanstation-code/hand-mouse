"""The app trains a candidate of models/gesture_tcn.onnx from the collected uses by itself; the person looks at it and
applies it (2026-11-12: "틈틈이 onnx를 앱이 알아서 … 자동으로 모은 수집 데이터를 가지고 학습", "내가 확인 후 교체")."""

from __future__ import annotations

import json
import sys
import time
from types import SimpleNamespace

import numpy as np
import pytest

from src import onnx_candidate, use_training
from src.use_review import BAD, OK

CLASSES = ["none", "thumb_index", "thumb_ring"]


def event(t=10.0, **kw):
    from tests.test_online_data import hand_world
    world = [[float(v) for v in p] for p in hand_world()]
    frames = [{"t": round(t - 2.0 + i / 30, 4), "world": world,
               "lm": [[.5 + p[0] * .25 + .0005 * i, .5 + p[1] * .25, p[2] * .25] for p in world]} for i in range(75)]
    return {"source": "rule", "key": "left_click", "label": "thumb_index", "t": t, "id": 1, "file": "a.jsonl",
            "wall": "2026-11-12 00:00:00", "marked": "", "frames": frames, **kw}


def test_what_a_logged_command_teaches_the_exported_model():
    target = use_training.event_target
    assert target(event(), OK, CLASSES) == "thumb_index"                 # a click the person passed
    assert target(event(), "", CLASSES) is None                           # not looked at: nothing
    assert target(event(), BAD, CLASSES) == "none"                        # a false detection: the hand made no gesture
    assert target(event(marked="f_key"), "", CLASSES) == "none"           # marked with F / F8
    assert target(event(label="thumb_index_middle", key="right_click"), OK, CLASSES) is None      # no class for it
    assert target(event(source="binding", key="comp_x", label=""), OK, CLASSES) is None            # a taught gesture
    assert target(event(source="binding", key="comp_x", label=""), BAD, CLASSES) == "none"


def test_the_events_become_one_record_with_a_segment_each_and_every_fifth_is_kept_out():
    items = []
    for n in range(10):
        target = "thumb_index" if n % 2 else "none"
        items.append({"file": "a.jsonl", "id": n, "target": target, "frames": use_training._clip(event(), target),
                      "held": n % use_training.HOLD_OUT == use_training.HOLD_OUT - 1})
    assert all(i["frames"] for i in items) and sum(i["held"] for i in items) == 2
    path, meta, frames = use_training.as_record(items)
    extract = meta["_cached_extract"]
    assert meta["mode"] == "use" and len(extract["seg_ranges"]) == 8 and extract["features"].shape[0] == len(frames)
    assert set(extract["cond_keys"]) == {"unassigned"}
    targets = extract["valid_targets"]
    a, b = extract["seg_ranges"][0]
    labelled = [i for i in range(a, b) if targets[i] is not None]
    assert targets[a] is None and labelled and min(labelled) > a + 15       # context first, the labelled stretch last
    assert {targets[i] for i in labelled} == {items[0]["target"]}
    assert {t for t in targets if t} == {"none", "thumb_index"}
    assert use_training.as_record([{**i, "held": True} for i in items]) is None


def test_old_and_new_model_are_scored_on_the_held_out_events_only():
    items = [{"target": "none", "held": True, "frames": use_training._clip(event(), "none")},
             {"target": "thumb_index", "held": True, "frames": use_training._clip(event(), "thumb_index")},
             {"target": "none", "held": False, "frames": use_training._clip(event(), "none")}]
    info = {"classes": CLASSES, "threshold": .7, "frames_in_a_row": 3, "window": 15}
    always_pinch = lambda x: np.tile([.05, .9, .05], (len(x), 1))       # noqa: E731
    never = lambda x: np.tile([.9, .05, .05], (len(x), 1))              # noqa: E731
    assert use_training.score(always_pinch, info, items) == {"clicks": 1, "clicks_seen": 1, "rejected": 1, "rejected_fired": 1}
    assert use_training.score(never, info, items) == {"clicks": 1, "clicks_seen": 0, "rejected": 1, "rejected_fired": 0}


def test_training_takes_the_collected_uses_into_every_training_set():
    pytest.importorskip("torch")
    from scripts.train_tcn import pick, pick_with_conds, pick_with_weights
    x = np.zeros((4, 15, 3), np.float32)
    guided = {"meta": {"mode": "guided"}, "x": x, "y": np.array([0, 1, 1, -1]), "cond": np.array([0, 0, 1, 1])}
    uses = {"meta": {"mode": "use"}, "x": x, "y": np.array([-1, 1, 0, 0]), "cond": np.array([-1, -1, -1, -1])}
    for conds, want in (([0], 2 + 3), ([1], 1 + 3), ([0, 1], 3 + 3)):
        assert len(pick([guided, uses], conds)[1]) == want
        assert len(pick_with_conds([guided, uses], conds)[1]) == want
        assert len(pick_with_weights([guided, uses], conds)[1]) == want
    assert len(pick([guided], [0])[1]) == 2                              # without uses: as before


def summary(**kw):
    model = lambda fired, seen: {"trained": "2026-11-08 19:40:07", "classes": CLASSES,      # noqa: E731
                                 "uses": {"clicks": 4, "clicks_seen": seen, "rejected": 10, "rejected_fired": fired},
                                 "held_out_posture": {"thumb_index": {"rate": .84, "total": 75, "rules_rate": .7}},
                                 "misfires_per_min": 6.8, "rules_misfires_per_min": 13.1}
    new = model(2, 4)
    new["classes"] = CLASSES + ["swipe_tab_left"]
    return {"created": "2026-11-12 01:00:00", "seconds": 600.0, "uses": {"none": 54}, "trained_on": 43, "held_out": 14,
            "candidate": new, "current": model(6, 3), **kw}


def candidate(tmp_path, **kw):
    models = tmp_path / "models"
    cand = models / "candidate"
    cand.mkdir(parents=True)
    for name, text in (("gesture_tcn.onnx", "OLD"), ("gesture_tcn.json", "{}")):
        (models / name).write_text(text, encoding="utf-8")
    for name, text in (("gesture_tcn.onnx", "NEW"), ("gesture_tcn.json", '{"new": 1}'), ("spatial_mlp.json", "{}")):
        (cand / name).write_text(text, encoding="utf-8")
    (cand / "summary.json").write_text(json.dumps(summary(**kw)), encoding="utf-8")
    return models, cand


def test_the_comparison_is_put_in_words_and_nothing_is_ready_without_a_summary(tmp_path):
    models, cand = candidate(tmp_path)
    view = onnx_candidate.view(cand, models)
    assert view["ready"] and view["trained_on"] == 43 and view["minutes"] == 10.0 and not view["can_rollback"]
    first, second = view["rows"][0], view["rows"][1]
    assert first["current"] == "6 / 10" and first["candidate"] == "2 / 10" and first["better"] == "yes"
    assert second["current"] == "3 / 4" and second["candidate"] == "4 / 4" and second["better"] == "yes"
    assert any("84%" in r["candidate"] for r in view["rows"]) and any("추가로 아는 동작" in n for n in view["notes"])
    (cand / "summary.json").unlink()
    assert onnx_candidate.view(cand, models) == {"ready": False, "rows": [], "notes": [], "can_rollback": False}


def test_applying_keeps_the_old_model_and_rolling_back_restores_it(tmp_path):
    models, cand = candidate(tmp_path)
    backup = onnx_candidate.apply(cand, models)
    assert (models / "gesture_tcn.onnx").read_text(encoding="utf-8") == "NEW"
    assert json.loads((models / "gesture_tcn.json").read_text(encoding="utf-8")) == {"new": 1}
    assert (backup / "gesture_tcn.onnx").read_text(encoding="utf-8") == "OLD" and not cand.exists()
    assert not (models / "spatial_mlp.json").exists()                    # only the gesture model is replaced
    assert onnx_candidate.view(cand, models)["can_rollback"]
    with pytest.raises(ValueError):
        onnx_candidate.apply(cand, models)                               # nothing waits now
    assert onnx_candidate.rollback(models) == backup.name
    assert (models / "gesture_tcn.onnx").read_text(encoding="utf-8") == "OLD" and not backup.exists()
    with pytest.raises(ValueError):
        onnx_candidate.rollback(models)
    models2, cand2 = candidate(tmp_path / "b")
    onnx_candidate.discard(cand2)
    assert not cand2.exists() and (models2 / "gesture_tcn.onnx").read_text(encoding="utf-8") == "OLD"


def test_the_app_asks_for_a_candidate_once_enough_new_uses_were_judged(tmp_path):
    from tests.test_use_learning import learning_runtime
    rt = learning_runtime(tmp_path)
    config = rt.engine.config
    rt._onnx_waiting, rt._onnx_done = False, 0                           # (whatever waits in the real models/ folder)
    need = rt._onnx_need()
    assert need == 50                                                   # the first candidate: enough to keep ten out
    rt._onnx_fresh = 12
    card = rt._onnx_item()
    assert card["key"] == rt.ONNX_KEY and card["state"] == "collecting" and (card["n"], card["need"]) == (12, 50)
    asked = lambda: getattr(rt, "_onnx_request", 0)                      # noqa: E731
    rt._onnx_fresh, rt._onnx_waiting, rt._onnx_last = need - 1, False, 0.0
    rt._onnx_auto(config)
    assert asked() == 0                                                  # not enough yet
    rt._onnx_fresh = need
    rt._onnx_waiting = True
    rt._onnx_auto(config)
    assert asked() == 0                                                  # a candidate is waiting for the person
    rt._onnx_waiting, rt._onnx_last = False, time.time()
    rt._onnx_auto(config)
    assert asked() == 0                                                  # the last one is not an hour old
    rt._onnx_last = 0.0
    rt._onnx_auto(config)
    rt._onnx_auto(config)
    assert asked() == 1                                                  # once for this many uses
    rt._onnx_done = 54                                                   # a candidate was made from 54: 30 more next time
    assert rt._onnx_need() == 30
    rt._onnx_waiting = True
    assert rt._onnx_item()["state"] == "candidate"
    rt._onnx_waiting = False
    config["onnx_auto"] = False
    assert rt._onnx_item() is None
    rt._onnx_fresh = need + 50
    rt._onnx_auto(config)
    assert asked() == 1


def test_the_dashboard_starts_the_training_and_tries_again_while_the_process_is_busy(tmp_path):
    from src.qt_dashboard import QtDashboard
    started, busy = [], {"on": True}
    job = SimpleNamespace(start=lambda **kw: (not busy["on"]) and (started.append(kw) or True))
    board = SimpleNamespace(_online_job=lambda: job, online_root=tmp_path / "online", _use_folder=lambda: tmp_path / "use",
                            learnChanged=SimpleNamespace(emit=lambda: None))
    QtDashboard.auto_onnx(board, 1)
    assert started == [] and getattr(board, "onnx_request_seen", 0) == 0     # busy: asked again next time
    busy["on"] = False
    QtDashboard.auto_onnx(board, 1)
    QtDashboard.auto_onnx(board, 1)
    assert len(started) == 1 and board.onnx_request_seen == 1
    command = started[0]["command"]
    assert command[2].endswith("onnx_auto_update.py") and "--use-events" in command and "후보" in board.learn_message
    line, notice = QtDashboard._learn_summary(SimpleNamespace(learn_auto=True, _gesture_name=str), {"status": "onnx_candidate"})
    assert "새 모델 확인" in line and notice


def test_the_baseline_trained_without_the_uses_stands_next_to_the_candidate(tmp_path):
    """2026-11-12: the model in use was checked another way, so the candidate's held-out numbers had nothing to stand
    next to. The same training without the collected uses does: its column, and a word when a gesture got worse."""
    base = summary()["current"]
    base["held_out_posture"] = {"thumb_index": {"rate": .91, "total": 75, "rules_rate": .7}}
    base["misfires_per_min"] = 5.0
    models, cand = candidate(tmp_path, baseline=base)
    view = onnx_candidate.view(cand, models)
    assert view["has_baseline"]
    posture = next(r for r in view["rows"] if "학습에 안 쓴 자세" in r["what"])
    assert posture["baseline"] == "91% (75회)" and posture["candidate"] == "84% (75회)"
    assert next(r for r in view["rows"] if "오작동" in r["what"])["baseline"] == "분당 5.0회"
    assert any("기준보다 낮아진" in n and "91% → 84%" in n for n in view["notes"])
    assert any("알 수 없는 동작" in n for n in view["notes"])               # the quick check saw one gesture only
    models2, cand2 = candidate(tmp_path / "b")                              # an older summary: no column, as before
    old = onnx_candidate.view(cand2, models2)
    assert not old["has_baseline"] and all(r["baseline"] == "" for r in old["rows"])


def test_a_baseline_is_trained_once_for_the_same_recordings_and_code(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("onnx_auto_update", Path(__file__).resolve().parents[1] / "scripts" / "onnx_auto_update.py")
    mod = importlib.util.module_from_spec(spec)
    path0 = list(sys.path)
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path[:] = path0
    key = {"mode": "fast", "code": "abc", "recordings": [["a.jsonl.gz", 1, 2]]}
    monkeypatch.setattr(mod, "baseline_key", lambda mode: {**key, "mode": mode})
    calls = []

    def run(command, **kw):
        calls.append(command)
        assert "--use-events" not in command and "--resume" not in command
        out = Path(command[command.index("--output-dir") + 1])
        if len(calls) != 2:
            (out / "gesture_tcn.onnx").write_text("B", encoding="utf-8")
            (out / "gesture_tcn.json").write_text("{}", encoding="utf-8")
        return SimpleNamespace(returncode=1 if len(calls) == 2 else 0)

    folder = tmp_path / "baseline"
    assert mod.make_baseline(folder, "fast", run=run)["reused"] is False and len(calls) == 1
    assert mod.make_baseline(folder, "fast", run=run) == {"ok": True, "reused": True, "seconds": 0.0} and len(calls) == 1
    key["code"] = "changed"                                                 # the training code changed: trained again
    assert mod.make_baseline(folder, "fast", run=run)["ok"] is False        # ... and that one failed: not taken as whole
    assert not mod.baseline_ready(folder, mod.baseline_key("fast"))
    assert mod.make_baseline(folder, "fast", run=run)["ok"] is True and len(calls) == 3
