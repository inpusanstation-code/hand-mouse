"""Gestures added from a few demonstrations (ported from virtual-hand-20261110 online/pose_memory + registration)."""
from __future__ import annotations

import numpy as np
import pytest

from manux.actions.bindings import resolve_bindings
from manux.core.contracts import FrameInfo, HandObservation
from manux.features import custom_pose
from manux.perception.pose_memory import USER_SOURCE, PoseMemory, PoseRecognizer, pose_features
from manux.perception.pose_registration import RegistrationConfig, RegistrationError, RegistrationSession

ASPECT = 720 / 1280


def pose(curled=(), jitter=0.0, seed=0):
    """A hand: (image landmarks, world landmarks). Fingers in `curled` fold toward the palm."""
    rng = np.random.default_rng(seed)
    pts = {0: (0.0, 0.0), 1: (-.02, -.01), 2: (-.04, -.03), 3: (-.055, -.05), 4: (-.065, -.07)}
    for k, (name, x) in enumerate(zip(("index", "middle", "ring", "pinky"), (-.02, 0.0, .02, .04))):
        base = 5 + 4 * k
        if name in curled:
            pts.update({base: (x, -.08), base + 1: (x, -.10), base + 2: (x, -.08), base + 3: (x, -.06)})
        else:
            pts.update({base: (x, -.08), base + 1: (x, -.11), base + 2: (x, -.13), base + 3: (x, -.15)})
    world = [(pts[i][0] + rng.normal(0, jitter), pts[i][1] + rng.normal(0, jitter), rng.normal(0, jitter)) for i in range(21)]
    lm = [(.5 + p[0] * 2, .6 + p[1] * 2, 0.0) for p in world]
    return tuple(lm), tuple(world)


OPEN = dict(curled=())
ROCK = dict(curled=("middle", "ring"))
FIST = dict(curled=("index", "middle", "ring", "pinky"))


def demonstrate(session, shape, rest=OPEN, fps=30, t=0.0, seconds=30.0):
    """Feed the session until it leaves prep/do/rest: `shape` while doing, `rest` otherwise."""
    n = 0
    while session.active and t < seconds:
        current = shape if session.state == "do" else rest
        lm, world = pose(**current, jitter=.002, seed=n)
        session.update(t, lm, world)
        t += 1 / fps
        n += 1
    return t


def test_pose_features_are_the_first_63_local3d_columns():
    lm, world = pose(**OPEN)
    x = pose_features([{"t": 0.0, "lm": lm, "world": world}], ASPECT)
    assert x.shape == (1, 63) and np.isfinite(x).all() and np.abs(x).sum() > 0
    assert not pose_features([{"t": 0.0}], ASPECT).any()             # a lost hand is all zeros


def test_a_registered_class_wins_only_inside_its_spread_and_against_known_poses():
    memory = PoseMemory()
    feats = lambda shape, n: np.concatenate([pose_features([dict(zip(("lm", "world"), pose(**shape, jitter=.002, seed=i)), t=0.0)], ASPECT) for i in range(n)])
    memory.add_known("open", feats(OPEN, 20))
    memory.add_class("rock", feats(ROCK, 30), demo_ids=np.repeat(np.arange(3), 10))
    assert memory.classify(feats(ROCK, 1))["label"] == "rock"
    assert memory.classify(feats(OPEN, 1))["label"] == "open"
    assert memory.classify(feats(FIST, 1))["label"] in ("unknown", "open")     # an unseen shape is never "rock"
    again = PoseMemory.from_dict(memory.to_dict())
    assert again.classify(feats(ROCK, 1))["label"] == "rock" and np.isinf(again.classes["open"].threshold)


def test_registration_runs_prep_do_rest_checks_and_only_approval_adds_the_class():
    memory = PoseMemory()
    session = RegistrationSession("락", memory, ASPECT)
    assert session.slot == "slot1" and session.view()["state"] == "prep"
    demonstrate(session, ROCK)
    assert session.state == "review", session.message
    report = session.view()["report"]
    assert report["demos"] == 5 and report["recognised"] >= 3 and report["reliable"] and not report["rest_fires"]
    assert "락" not in memory.classes                              # nothing added before the person approves
    result = session.approve()
    assert result == {"event": "class_added", "label": "락", "slot": "slot1", "prototypes": 3, "neural_weights_changed": False}
    assert memory.classes["락"].source == USER_SOURCE
    demos = session.demo_frames()
    assert demos["label_source"] == "user_confirmed" and len(demos["demos"]) == 5 and "image" not in str(demos.keys())


def test_registration_waits_for_the_hand_and_fails_on_too_little_demonstration():
    session = RegistrationSession("짧은", PoseMemory(), ASPECT, RegistrationConfig(demos=3, do_seconds=.3))
    lm, world = pose(**ROCK)
    for k in range(30):
        session.update(k / 30, None, None)                       # no hand: the clock does not run
    assert session.state == "prep" and not session.view()["hand"]
    demonstrate(session, ROCK)
    assert session.state == "failed" and session.message


def test_names_and_slots_are_checked():
    memory = PoseMemory()
    with pytest.raises(RegistrationError):
        RegistrationSession("  ", memory, ASPECT)
    with pytest.raises(RegistrationError):
        RegistrationSession("x" * 31, memory, ASPECT)
    for i in range(8):
        memory.add_class(f"g{i}", np.random.default_rng(i).normal(size=(10, 63)), extra={"slot": f"slot{i + 1}"})
    with pytest.raises(RegistrationError, match="8개"):
        RegistrationSession("하나 더", memory, ASPECT)


def test_recognizer_fires_once_per_hold_after_the_run():
    memory = PoseMemory()
    feats = np.concatenate([pose_features([dict(zip(("lm", "world"), pose(**ROCK, jitter=.002, seed=i)), t=0.0)], ASPECT) for i in range(30)])
    memory.add_class("rock", feats, demo_ids=np.repeat(np.arange(3), 10), extra={"slot": "slot1"})
    rec = PoseRecognizer(memory)
    lm, world = pose(**ROCK)
    fired = [rec.step(i / 30, lm, world, ASPECT) for i in range(10)]
    assert fired.count("rock") == 1 and fired.index("rock") == 3
    assert rec.step(1.0, None, None, ASPECT) is None
    assert [rec.step(1 + i / 30, lm, world, ASPECT) for i in range(5)].count("rock") == 1


def test_feature_slots_are_unbound_by_default_and_fire_their_slot():
    bindings, problems = resolve_bindings(custom_pose.DEFAULT_BINDINGS, gesture_phases=custom_pose.GESTURE_PHASES)
    assert not problems and bindings == {}                        # D-004: nothing runs until the person picks a command
    f = custom_pose.CustomPoseFeature()
    from manux.core.contracts import FrameContext, OutputTarget, Stage
    frame = FrameInfo(0, 0.0, 1280, 720, True)
    ctx = FrameContext(frame, Stage.MAIN, OutputTarget.WINDOWS, "pinch")
    lm, world = pose(**ROCK)
    assert f.step(HandObservation(frame, lm, "Right", .99, world), ctx) == ()      # no memory: nothing
    memory = PoseMemory()
    feats = np.concatenate([pose_features([dict(zip(("lm", "world"), pose(**ROCK, jitter=.002, seed=i)), t=0.0)], ASPECT) for i in range(30)])
    memory.add_class("rock", feats, demo_ids=np.repeat(np.arange(3), 10), source=USER_SOURCE, extra={"slot": "slot3"})
    f.set_memory(memory)
    out = []
    for i in range(6):
        fr = FrameInfo(i, i / 30, 1280, 720, True)
        out += f.step(HandObservation(fr, lm, "Right", .99, world), FrameContext(fr, Stage.MAIN, OutputTarget.WINDOWS, "pinch"))
    assert [(i.gesture, i.phase, i.info["name"]) for i in out] == [("custom_pose.slot3", "tap", "rock")]


def test_register_bind_and_run_through_the_real_engine(tmp_path):
    from manux.app import build_engine, schema
    from manux.desktop import CustomPoses
    from manux.settings.store import Settings
    cp = CustomPoses(tmp_path / "custom_poses")
    cp.start("락", ASPECT)
    demonstrate(cp.session, ROCK)
    cp.approve()
    cp.bind("slot1", "nav.back")
    with pytest.raises(ValueError):
        cp.bind("slot1", "mouse.drag")                            # only tap commands
    assert (tmp_path / "custom_poses" / "memory.json").is_file() and list((tmp_path / "custom_poses" / "demos").glob("*.json"))
    again = CustomPoses(tmp_path / "custom_poses")                # survives a restart
    assert again.view()["poses"] == [{"slot": "slot1", "name": "락", "demos": 5, "action": "nav.back"}]
    engine = build_engine(Settings(schema()), "pinch")
    try:
        again.attach(engine)
        results, lm, world = [], *pose(**ROCK)
        for i in range(8):
            frame = FrameInfo(i, 1 + i / 30, 1280, 720, True)
            results += engine.step(frame, HandObservation(frame, lm, "Right", .99, world)).results
        assert ("nav.back", "tap", "ok") in results
        again.remove("slot1")
        again.attach(engine)
        assert "custom_pose.slot1" not in engine.router.bindings and again.view()["poses"] == []
    finally:
        engine.shutdown()



def test_a_failed_registration_is_dropped_with_a_reason(tmp_path):
    from manux.desktop import CustomPoses
    cp = CustomPoses(tmp_path / "cp")
    cp.start("짧은", ASPECT)
    cp.session.config.do_seconds = .3                            # every demonstration too short
    lm, world = pose(**ROCK)
    failed = [cp.step(k / 30, lm, world) for k in range(30 * 30)]
    assert failed.count(True) == 1 and cp.session is None and "짧" in cp.message
    assert not cp.step(31.0, lm, world)                          # nothing running any more
