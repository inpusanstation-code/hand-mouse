"""Everyday-use candidates (virtual-hand-20261110 online/segmenter + collector) -> MANUX recordings, labelled later."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from manux.core.contracts import FrameInfo, HandObservation, OutputTarget, RecordingIdentity
from manux.data import everyday
from manux.data.recording import read
from manux.data.training_center import recording_sets
from manux.perception.segmenter import MotionSegmenter


def hand(t, thumb_on_index=0.0, seed=0):
    """An open hand; `thumb_on_index` 0..1 moves the thumb tip onto the index tip."""
    rng = np.random.default_rng(seed)
    pts = {0: (0.0, 0.0), 1: (-.02, -.01), 2: (-.04, -.03), 3: (-.055, -.05)}
    for k, x in enumerate((-.02, 0.0, .02, .04)):
        base = 5 + 4 * k
        pts.update({base: (x, -.08), base + 1: (x, -.11), base + 2: (x, -.13), base + 3: (x, -.15)})
    far, near = np.array((-.065, -.07)), np.array(pts[8])
    pts[4] = tuple(far + (near - far) * thumb_on_index)
    world = tuple((p[0] + rng.normal(0, .0005), p[1] + rng.normal(0, .0005), 0.0) for p in (pts[i] for i in range(21)))
    lm = tuple((.5 + p[0] * 2, .6 + p[1] * 2, 0.0) for p in world)
    frame = FrameInfo(int(t * 30), t, 1280, 720, True)
    return HandObservation(frame, lm, "Right", .99, world)


def use(t0=0.0):
    """1 s still, a pinch (close 0.2 s, hold 0.3 s, open 0.2 s), 1.5 s still: (t, hand, action) at 30 fps."""
    out, t = [], t0
    plan = [0.0] * 30 + list(np.linspace(0, 1, 6)) + [1.0] * 9 + list(np.linspace(1, 0, 6)) + [0.0] * 45
    for i, k in enumerate(plan):
        out.append((t, hand(t, k, seed=i), "mouse.left_click" if i == 40 else None))
        t += 1 / 30
    return out


def segments(frames):
    seg, got = MotionSegmenter(), []
    for t, h, action in frames:
        done = seg.feed(t, h.landmarks, h.world, action, hand=h)
        if done:
            got.append(done)
    return got, seg


def test_a_still_hand_is_no_candidate_and_a_pinch_is_one():
    still, _ = segments([(i / 30, hand(i / 30, seed=i), None) for i in range(90)])
    assert still == []
    got, seg = segments(use())
    assert len(got) == 1 and not seg.open
    s = got[0]
    assert s.reason == "quiet" and 1.0 <= s.start <= 1.3 and s.top_action == "mouse.left_click"
    assert "contact" in s.triggers and len(s.frames) > 15            # pre-frames are kept


def write_candidate(tmp_path, preset="pinch"):
    from manux.desktop import EverydayCollector
    folder = everyday.folder_of(tmp_path / "recordings")
    collector = EverydayCollector(folder, meta=lambda: {"person": "dan", "profile": "dan", "preset": preset})
    got, _ = segments(use())
    return folder, collector.write(got[0], collector.meta())


def test_a_candidate_is_a_complete_recording_that_training_ignores(tmp_path):
    folder, path = write_candidate(tmp_path)
    rec = read(path)
    assert rec.complete and rec.meta["split"] == "candidate" and rec.meta["mode"] == "free"
    assert {f["label"]["target"] for f in rec.frames} == {"idle"}            # never a class
    assert "image" not in str(rec.meta) and all("lm" in f for f in rec.frames)
    train, evaluation = recording_sets(tmp_path / "recordings", RecordingIdentity("dan", "pinch"))
    assert path not in train and path not in evaluation
    rows = everyday.candidates(folder)
    assert len(rows) == 1 and rows[0]["action"] == "mouse.left_click" and rows[0]["seconds"] > 0


def test_labelling_turns_it_into_train_data_and_leaves_the_list(tmp_path):
    folder, path = write_candidate(tmp_path)
    everyday.label(folder, path, "thumb_middle", "left_click", "pinch.thumb_middle")
    rec = read(path)
    assert rec.complete and rec.meta["split"] == "train" and rec.meta["label_source"] == "user_corrected"
    targets = [f["label"]["target"] for f in rec.frames]
    assert targets[0] == "transition" and targets[-1] == "thumb_middle" and "idle" not in targets
    train, _ = recording_sets(tmp_path / "recordings", RecordingIdentity("dan", "pinch"))
    assert path in train and everyday.candidates(folder) == []
    import pytest
    with pytest.raises(ValueError):
        everyday.label(folder, path, "none")                                 # only once
    with pytest.raises(ValueError):
        everyday.label(folder, tmp_path / "elsewhere.jsonl.gz", "none")       # only inside the folder


def test_nothing_meant_is_none_and_discard_removes(tmp_path):
    folder, path = write_candidate(tmp_path)
    everyday.label(folder, path, everyday.NONE_CHOICE)
    assert {f["label"]["target"] for f in read(path).frames} == {"none"}
    _, other = write_candidate(tmp_path)
    everyday.discard(folder, other)
    assert not other.exists()


def test_the_runtime_collects_only_real_use_and_only_when_switched_on(tmp_path):
    from manux.app import schema
    from manux.desktop import EverydayCollector, build
    from manux.settings.store import Settings
    settings = Settings(schema())
    runtime = build(settings, SimpleNamespace(close=lambda: None), windows=False)
    try:
        runtime.everyday = EverydayCollector(tmp_path / "ev")
        fed = []
        runtime.everyday.feed = lambda t, h, a: fed.append((t, a))
        snap = lambda **kw: SimpleNamespace(**{"output": OutputTarget.WINDOWS, "control_on": True, "busy": frozenset(),
                                              "results": (("mouse.move", "hold", "ok"), ("mouse.left_click", "tap", "ok")), **kw})
        runtime._everyday_step(1.0, None, snap())
        assert fed == []                                                    # off by default
        settings.set("data.collect_everyday", True)
        runtime._everyday_step(1.0, None, snap())
        assert fed == [(1.0, "mouse.left_click")]
        for blocked in (dict(output=OutputTarget.PRACTICE), dict(control_on=False), dict(busy=frozenset({"recording"}))):
            runtime._everyday_step(2.0, None, snap(**blocked))
        assert len(fed) == 1
    finally:
        runtime.stop()


def test_a_full_queue_drops_instead_of_waiting(tmp_path):
    from manux.desktop import EverydayCollector
    collector = EverydayCollector(tmp_path / "ev")
    collector._thread = SimpleNamespace(is_alive=lambda: True)               # no writer: the queue fills
    got, _ = segments(use())
    for _ in range(collector.QUEUE + 3):
        collector._submit(got[0])
    assert collector.queue.qsize() == collector.QUEUE and collector.dropped == 3


def test_service_choices_and_labels(tmp_path):
    from manux.desktop import everyday_service
    folder, path = write_candidate(tmp_path)
    service = everyday_service(folder, lambda: "pinch")
    choices = service["choices"]()
    assert choices and len({c["target"] for c in choices}) == len(choices) and all(c["name"] for c in choices)
    assert [r["path"] for r in service["list"]()] == [str(path)]
    name = service["label"](str(path), 1)
    assert name == choices[0]["name"] and read(path).meta["split"] == "train" and service["list"]() == []
