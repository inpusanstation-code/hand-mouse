"""A gesture made in [말·글로 연결] can be marked "motion mode only" (2026-11-11 request)."""

from __future__ import annotations

import time
from types import SimpleNamespace

import src.llm_binding as lb
from src.action_bindings import ActionBindingRegistry, CompositeGestureDetector
from src.path_gesture import PathStore
from src.sequence import SequenceStore


def hand():
    return [SimpleNamespace(x=.5, y=.5, z=0.0) for _ in range(21)]


def held(det, scope, posture="v_sign_down", seconds=.8):
    """Hold `posture` still for `seconds`: the gesture that fired, if any."""
    t, hit = 100.0, None
    while t < 100.0 + seconds and hit is None:
        hit = det.step(t, hand(), "", set(), .5625, scope=scope, posture=posture)
        t += 1 / 30
    return hit


def test_a_motion_only_composite_fires_in_the_motion_scope_only(tmp_path):
    reg = ActionBindingRegistry(tmp_path / "b.json")
    comp = reg.register_composite_gesture("", "", "v_sign_down", "hold", "hotkey", "alt+f4", hold_seconds=.4)
    key = comp["key"]
    assert held(CompositeGestureDetector(reg), "normal")["key"] == key     # as before
    assert held(CompositeGestureDetector(reg), "motion") is None
    assert reg.set_composite_motion_only(key, True)
    assert held(CompositeGestureDetector(reg), "normal") is None
    assert held(CompositeGestureDetector(reg), "motion")["key"] == key
    det = CompositeGestureDetector(reg)
    det._active_posture = "v_sign_down"
    assert not det.commanding()                                            # not a command of the ordinary controls
    assert ActionBindingRegistry(tmp_path / "b.json").composite_gestures[key]["motion_only"] is True   # saved
    reg.set_composite_motion_only(key, False)
    assert "motion_only" not in ActionBindingRegistry(tmp_path / "b.json").composite_gestures[key]


def test_sequences_and_shape_drawings_can_be_motion_only(tmp_path):
    seqs = SequenceStore(tmp_path / "s.json")
    a = seqs.add("", ["v_sign", "fist"])
    b = seqs.add("", ["rock_sign", "fist"])
    assert seqs.set_motion_only(b, True)
    assert set(seqs.active()) == {a, b} and set(seqs.active(True)) == {a, b} and set(seqs.active(False)) == {a}
    assert SequenceStore(tmp_path / "s.json").rows()[1]["motion_only"] is True
    paths = PathStore(tmp_path / "p.json")
    p = paths.add("", "fist", "rotate_cw")
    paths.set_motion_only(p, True)
    assert p in paths.active(True) and p not in paths.active(False)
    paths.set_motion_only(p, False)
    assert p in PathStore(tmp_path / "p.json").active(False)


def proposal(**kw):
    base = {"gesture_key": lb.NEW, "new_name": "", "new_posture": "", "new_trigger": "", "new_sequence": [],
            "app_match": "", "action_type": "hotkey", "action_value": "alt+f4", "steps": [], "enabled": True,
            "motion_only": False, "reason": ""}
    return {"summary": "", "questions": [], "proposals": [{**base, **kw}]}


def test_the_ai_can_create_a_motion_only_gesture_and_the_card_switches_it(tmp_path):
    reg = ActionBindingRegistry(tmp_path / "b.json")
    history = lb.History(tmp_path / "ai.json", tmp_path / "s.json", tmp_path / "p.json")
    row = lb.check(proposal(new_posture="v_sign_down", new_trigger="hold", motion_only=True), lb.gesture_list(reg))["proposals"][0]
    assert row["ok"] and row["motion_only"] and "모션 모드에서만" in row["gesture_name"]
    done = lb.apply([row], reg, history=history)
    key = next(iter(reg.composite_gestures))
    assert reg.composite_gestures[key]["motion_only"] is True and "모션 모드에서만" in done[0]
    card = history.rows(reg)[0]
    assert card["mode_option"] and card["motion_only"]
    assert "평소" in history.set_motion_only(card["index"], reg, False)
    card = history.rows(reg)[0]
    assert card["mode_option"] and not card["motion_only"] and "motion_only" not in reg.composite_gestures[key]
    assert "모션 모드에서만" in history.set_motion_only(card["index"], reg, True)
    assert "(모션 모드에서만)" in next(g for g in lb.gesture_list(reg) if g["key"] == key)["instruction"]
    # a motion_<direction> gesture is a motion-mode gesture anyway: no switch, the mark is shown
    row = lb.check(proposal(new_posture="v_sign", new_trigger="motion_left", motion_only=True), lb.gesture_list(reg))["proposals"][0]
    assert row["ok"] and not row["motion_only"]
    lb.apply([row], reg, history=history)
    card = history.rows(reg)[0]
    assert card["motion"] and card["motion_only"] and not card["mode_option"]


def test_a_sequence_card_switches_too_and_a_built_in_gesture_has_no_switch(tmp_path):
    reg = ActionBindingRegistry(tmp_path / "b.json")
    store = SequenceStore(tmp_path / "s.json")
    history = lb.History(tmp_path / "ai.json", tmp_path / "s.json", tmp_path / "p.json")
    row = lb.check(proposal(new_sequence=["v_sign", "fist"], motion_only=True), lb.gesture_list(reg))["proposals"][0]
    lb.apply([row], reg, history=history, sequences=store)
    key = next(iter(store.items))
    assert SequenceStore(tmp_path / "s.json").items[key]["motion_only"] is True
    card = history.rows(reg)[0]
    assert card["mode_option"] and card["motion_only"]
    history.set_motion_only(card["index"], reg, False)
    assert "motion_only" not in SequenceStore(tmp_path / "s.json").items[key]
    built_in = lb.check(proposal(gesture_key="thumb_pinky", motion_only=True), lb.gesture_list(reg))["proposals"][0]
    assert built_in["ok"] and not built_in["motion_only"]
    lb.apply([built_in], reg, history=history)
    card = history.rows(reg)[0]
    assert not card["mode_option"] and not card["motion_only"]


def test_the_runtime_runs_a_motion_only_gesture_only_in_motion_mode(tmp_path, monkeypatch):
    import src.qt_runtime as qr
    from src.action_bindings import get_action_registry
    from tests.test_qt_runtime import runtime
    rt = runtime(tmp_path)
    rt.paused = False
    reg = get_action_registry()
    comp = reg.register_composite_gesture("", "거꾸로 V 유지", "v_sign_down", "hold", "hotkey", "alt+f4", hold_seconds=.4)
    reg.set_composite_motion_only(comp["key"], True)
    ran = []
    monkeypatch.setattr(rt, "_run_resolved", lambda r, resolved: (ran.append(resolved["gesture_key"]) or True, "Alt+F4"))
    monkeypatch.setattr(qr, "hand_posture", lambda lm, aspect=1.0: "v_sign_down")

    def run(seconds):
        start = time.perf_counter()
        while time.perf_counter() - start < seconds and not ran:
            rt._step()
            time.sleep(1 / 120)

    run(1.0)
    assert ran == [] and not rt.motion.active               # the ordinary controls: nothing
    rt.ui = __import__("dataclasses").replace(rt.ui, motion_request=rt.ui.motion_request + 1)   # the [모션 모드] button
    run(2.0)
    assert rt.motion.active and ran == [comp["key"]]
    # with the control off (simulation) it is told on the screen, not run
    ran.clear()
    rt.motion_composite_detector = CompositeGestureDetector(reg)
    rt.paused = True
    start = time.perf_counter()
    while time.perf_counter() - start < 2.0 and "시뮬레이션" not in rt._motion_last:
        rt._step()
        time.sleep(1 / 120)
    assert rt.motion.active and ran == [] and "거꾸로 V 유지" in rt._motion_last
