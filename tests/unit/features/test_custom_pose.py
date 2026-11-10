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


def test_registration_runs_rest_then_holds_learns_and_only_approval_adds_the_class():
    memory = PoseMemory()
    session = RegistrationSession("락", memory, ASPECT)
    assert session.slot == "slot1" and session.view()["state"] == "rest"
    demonstrate(session, ROCK)
    assert session.state == "review", session.message
    report = session.view()["report"]
    assert report["demos"] == 3 and report["recognised"] >= 2 and report["reliable"] and not report["rest_fires"]
    assert "락" not in memory.classes                              # nothing added before the person approves
    result = session.approve()
    assert result == {"event": "class_added", "label": "락", "slot": "slot1", "prototypes": 3, "neural_weights_changed": False,
                      "classifier": True}
    assert memory.classes["락"].source == USER_SOURCE and memory.classes["락"].mlp is not None
    demos = session.demo_frames()
    assert demos["label_source"] == "user_confirmed" and len(demos["demos"]) == 3 and demos["rest"]
    assert "image" not in str(demos.keys())


def test_registration_waits_for_the_hand_and_fails_on_too_little_demonstration():
    session = RegistrationSession("짧은", PoseMemory(), ASPECT, RegistrationConfig(demos=3, do_seconds=.3))
    lm, world = pose(**ROCK)
    for k in range(30):
        session.update(k / 30, None, None)                       # no hand: the clock does not run
    assert session.state == "rest" and not session.view()["hand"]
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
    memory.add_class("rock", feats, demo_ids=np.repeat(np.arange(3), 10), extra={"slot": "slot1", "hold": 0})
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
    memory.add_class("rock", feats, demo_ids=np.repeat(np.arange(3), 10), source=USER_SOURCE, extra={"slot": "slot3", "hold": 0})
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
    assert again.view()["poses"] == [{"slot": "slot1", "name": "락", "demos": 3, "action": "nav.back", "keys": "",
                                      "keys_label": "", "hold": .4}]           # no earlier data: the default hold
    again.set_hold("slot1", 1.25)
    assert CustomPoses(tmp_path / "custom_poses").view()["poses"][0]["hold"] == 1.25
    with pytest.raises(ValueError):
        again.set_hold("slot1", 9)
    again.set_hold("slot1", .4)
    engine = build_engine(Settings(schema()), "pinch")
    try:
        again.attach(engine)
        results, lm, world = [], *pose(**ROCK)
        for i in range(40):                                       # longer than the gesture's hold time
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
    assert failed.count(True) == 1 and cp.session is None and "지금" in cp.message
    assert not cp.step(31.0, lm, world)                          # nothing running any more



def test_a_registered_gesture_can_press_any_key_combination_including_win(tmp_path):
    from manux.app import build_engine, schema
    from manux.core.contracts import OutputTarget
    from manux.desktop import CustomPoses
    from manux.output.windows import FakeBackend, WindowsOutputConfig, WindowsOutputSink
    from manux.platform.monitors import ScreenLayout
    from manux.settings.store import Settings
    cp = CustomPoses(tmp_path / "cp")
    cp.start("캡처", ASPECT)
    demonstrate(cp.session, ROCK)
    cp.approve()
    cp.bind("slot1", "keys.press", "Win + Shift + S")
    row = cp.view()["poses"][0]
    assert row["action"] == "keys.press" and row["keys"] == "shift+win+s" and row["keys_label"] == "Shift + Win + S"
    for bad in ("alt+f4", "win+l", "pause", "ctrl+banana", ""):
        with pytest.raises(ValueError):
            cp.bind("slot1", "keys.press", bad)
    assert cp.view()["poses"][0]["keys"] == "shift+win+s"           # a refused combination keeps the old one
    with pytest.raises(ValueError):
        cp.bind("slot1", "window.close")                            # Alt+F4 is not offered
    engine = build_engine(Settings(schema()), "pinch")
    backend = FakeBackend((10, 10))
    try:
        engine.sinks[OutputTarget.WINDOWS] = WindowsOutputSink(backend, ScreenLayout.single(1920, 1080),
                                                               WindowsOutputConfig(), threaded=False)
        CustomPoses(tmp_path / "cp").attach(engine)                  # after a restart
        from manux.core.contracts import Stage
        from manux.engine.commands import SetControl, SetStage
        engine.commands.put(SetStage(Stage.MAIN)); engine.commands.put(SetControl(True))
        lm, world = pose(**ROCK)
        results = []
        for i in range(40):                                       # longer than the gesture's hold time
            frame = FrameInfo(i, 1 + i / 30, 1280, 720, True)
            results += engine.step(frame, HandObservation(frame, lm, "Right", .99, world)).results
        assert ("keys.press", "tap", "ok") in results
        assert [e[1] for e in backend.events if e[0] == "key" and e[2]] == ["shift", "win", "s"]
    finally:
        engine.shutdown()


def test_saving_the_review_registers_the_gesture_with_its_command_and_a_refused_key_registers_nothing(tmp_path):
    """2026-11-10: the command is picked in the review and nothing is registered before 저장."""
    from manux.desktop import CustomPoses
    cp = CustomPoses(tmp_path / "cp")
    cp.start("락", ASPECT)
    demonstrate(cp.session, ROCK)
    assert cp.view()["poses"] == [] and cp.session.state == "review"          # reviewed, not registered yet
    with pytest.raises(ValueError):
        cp.approve("keys.press", "alt+f4")
    assert cp.view()["poses"] == [] and cp.session is not None and cp.session.state == "review"
    assert not (tmp_path / "cp" / "memory.json").exists()
    cp.approve("keys.press", "ctrl + c")
    row = cp.view()["poses"][0]
    assert (row["name"], row["action"], row["keys"]) == ("락", "keys.press", "ctrl+c") and cp.session is None
    assert CustomPoses(tmp_path / "cp").view()["poses"][0]["keys"] == "ctrl+c"   # saved to disk


def test_the_classifier_learns_the_pose_against_the_rest_block_and_earlier_resting_hands():
    """2026-11-10: rest and command poses recorded in separate blocks, a small MLP learns them (measured better than the
    distance to demonstrations at the same false-fire rate on the person's recordings)."""
    feats = lambda shape, n, seed=0: np.concatenate([pose_features([dict(zip(("lm", "world"), pose(**shape, jitter=.004, seed=seed + i)), t=0.0)], ASPECT) for i in range(n)])
    past = [feats(OPEN, 200, 1000), feats(dict(curled=("ring", "pinky")), 200, 2000), feats(OPEN, 200, 3000)]
    session = RegistrationSession("락", PoseMemory(), ASPECT, negatives=past)
    demonstrate(session, ROCK)
    report = session.view()["report"]
    assert session.state == "review" and report["reliable"] and report["recognised"] >= 2
    assert report["fires_per_min"] is not None and report["fires_per_min"] <= 2.0 and report["checked_minutes"] > 0
    session.approve()
    memory = session.memory
    assert memory.classes["락"].mlp is not None
    assert memory.classify(feats(ROCK, 1, 77))["label"] == "락"
    assert memory.classify(feats(OPEN, 1, 78))["label"] != "락"
    again = PoseMemory.from_dict(memory.to_dict())                 # the classifier survives saving
    assert again.classify(feats(ROCK, 1, 79))["label"] == "락"


def test_a_pose_the_person_makes_all_the_time_is_called_unsafe():
    feats = lambda shape, n, seed=0: np.concatenate([pose_features([dict(zip(("lm", "world"), pose(**shape, jitter=.002, seed=seed + i)), t=0.0)], ASPECT) for i in range(n)])
    past = [feats(ROCK, 300, 500), feats(ROCK, 300, 900)]          # earlier resting hands ARE the new pose (same jitter)
    session = RegistrationSession("락", PoseMemory(), ASPECT, negatives=past)
    demonstrate(session, ROCK)
    report = session.view()["report"]
    assert session.state == "review" and not report["reliable"] and report["rest_fires"]


def test_the_app_trains_in_the_background_and_reports_when_done():
    session = RegistrationSession("락", PoseMemory(), ASPECT, threaded=True)
    t = demonstrate(session, ROCK, seconds=60.0)
    import time
    deadline = time.perf_counter() + 20
    while session.state == "training" and time.perf_counter() < deadline:
        lm, world = pose(**OPEN)
        session.update(t, lm, world); t += 1 / 30
        time.sleep(.01)
    assert session.state == "review" and session.report["fires_per_min"] is None   # no earlier data: rest block only


def test_earlier_resting_hands_are_read_once_and_then_come_from_the_cache(tmp_path, monkeypatch):
    import time
    from manux.desktop import PastNegatives
    (tmp_path / "rec").mkdir()
    (tmp_path / "rec" / "a.jsonl.gz").write_bytes(b"x")
    calls = []

    def fake_read(self, paths):
        calls.append(len(paths))
        return [np.ones((12, 63), np.float32), np.zeros((15, 63), np.float32)]
    monkeypatch.setattr(PastNegatives, "_read", fake_read)
    for _ in range(2):
        n = PastNegatives(tmp_path / "rec", tmp_path / "cp" / "negatives.npz")
        n.start()
        deadline = time.perf_counter() + 5
        while n.get() is None and time.perf_counter() < deadline:
            time.sleep(.01)
        assert [len(s) for s in n.get()] == [12, 15] and not n.error
    assert calls == [1]                                            # the second time from the cache


def test_a_gesture_fires_only_after_its_hold_time_and_registration_chooses_one():
    """2026-11-10 '지나가는 동작에도 너무 금방 반응한다': a hold in seconds (decimals), chosen at registration."""
    memory = PoseMemory()
    feats = np.concatenate([pose_features([dict(zip(("lm", "world"), pose(**ROCK, jitter=.002, seed=i)), t=0.0)], ASPECT) for i in range(30)])
    memory.add_class("rock", feats, demo_ids=np.repeat(np.arange(3), 10), extra={"slot": "slot1", "hold": .5})
    rec = PoseRecognizer(memory)
    lm, world = pose(**ROCK)
    fired = [rec.step(i / 30, lm, world, ASPECT) for i in range(30)]
    assert fired.count("rock") == 1 and fired.index("rock") == 15            # 0.5 s at 30 fps
    passing = [rec.step(2 + i / 30, *pose(**(ROCK if i % 12 < 8 else OPEN)), ASPECT) for i in range(60)]
    assert "rock" not in passing                                              # 0.27 s glimpses never fire
    feats_of = lambda shape, n, seed: np.concatenate([pose_features([dict(zip(("lm", "world"), pose(**shape, jitter=.002, seed=seed + i)), t=0.0)], ASPECT) for i in range(n)])
    session = RegistrationSession("락", PoseMemory(), ASPECT, negatives=[feats_of(OPEN, 300, 100), feats_of(OPEN, 300, 400)])
    demonstrate(session, ROCK)
    report = session.view()["report"]
    assert report["hold"] in (.2, .3, .4, .5, .6, .7, .8, 1.0) and report["fires_at_hold"] is not None
    session.approve(hold=.75)
    assert session.memory.classes["락"].extra["hold"] == .75                  # the person's choice wins
