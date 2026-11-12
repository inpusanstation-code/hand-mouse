"""An open hand needs every finger straight at both joints (2026-11-11, "손펴기 판정이 너무 후하다. 손가락의 첫째 두번째
마디도 다 펴졌을 때를 기준으로"). Fixture: the 3 s before '손 펴기 유지' fired that evening; 4 of them were held with bent fingers."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import pose_probe as pp

DATA = json.loads((Path(__file__).parent / "fixtures" / "open_hand_joints_20261111.json").read_text(encoding="utf-8"))


def _lm(frame):
    return [SimpleNamespace(x=a[0], y=a[1], z=a[2]) for a in frame]


def _hold_detector():
    from src.action_bindings import ActionBindingRegistry, CompositeGestureDetector
    reg = ActionBindingRegistry.__new__(ActionBindingRegistry)
    ActionBindingRegistry.__init__(reg)
    reg.composite_gestures = {"comp_open_hand_hold": {"key": "comp_open_hand_hold", "name": "손 펴기 유지",
                                                      "base_posture": "open_hand", "trigger_type": "hold",
                                                      "hold_seconds": 1.0, "enabled": True}}
    reg.bindings["comp_open_hand_hold"] = {"gesture_key": "comp_open_hand_hold", "track": "composite",
                                           "action_type": "hotkey", "action_value": "f5", "enabled": True,
                                           "app_overrides": []}
    return CompositeGestureDetector(reg)


def _fires(case):
    det, hits = _hold_detector(), []
    for t, eng, lm in zip(case["t"], case["engine"], case["lm"]):
        hit = det.step(t, _lm(lm), eng, set(), 720 / 1280, scope="normal")
        if hit:
            hits.append(hit["key"])
    return hits


@pytest.mark.parametrize("name", [k for k, c in DATA["cases"].items() if c["kind"] == "bent"])
def test_a_hand_with_bent_fingers_does_not_hold_open(name):
    case = DATA["cases"][name]
    assert not pp.fingers_straight(_lm(case["lm"][-8]))
    assert _fires(case) == []


@pytest.mark.parametrize("name", [k for k, c in DATA["cases"].items() if c["kind"] == "straight"])
def test_a_really_open_hand_still_holds(name):
    case = DATA["cases"][name]
    assert pp.fingers_straight(_lm(case["lm"][-8]))
    assert _fires(case) == ["comp_open_hand_hold"]


def test_a_straight_finger_bends_zero_and_a_curled_one_a_lot():
    straight = [SimpleNamespace(x=.5, y=1 - i * .05, z=0.0) for i in range(21)]
    assert max(max(b) for b in pp.finger_bends(straight)) < 1
    hooked = list(straight)
    for tip in (8, 12, 16, 20):
        hooked[tip] = SimpleNamespace(x=.55, y=hooked[tip - 1].y, z=0.0)      # the end joint bent 90 deg
    assert all(b[1] > 80 for b in pp.finger_bends(hooked)) and not pp.fingers_straight(hooked)
