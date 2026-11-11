"""Teaching a shown hand shape (src/posture_teach.py): a small MLP on the joints, checked, applied, used by both
posture functions only where the rules told that shape's examples otherwise."""
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import src.posture_teach as pt
from src.action_bindings import CompositeGestureDetector
from src.pose_probe import hand_posture
from tests.test_pose_probe_upside_down import FRAME as TODAY     # 2026-11-11 look, a frame no rule matched

FIX = Path(__file__).with_name("fixtures")


def _frames(name):
    out = []
    for f in json.loads((FIX / name).read_text(encoding="utf-8"))["frames"]:
        lm = f["lm"] if isinstance(f, dict) else (f[1] if len(f) == 2 else f)
        if lm:
            out.append([list(p) + [0.0] * (3 - len(p)) for p in lm])
    return out


def _pts(lm):
    return [SimpleNamespace(x=p[0], y=p[1], z=p[2]) for p in lm]


def _negatives():
    """'other': half-fist moving, ring contact, a scroll stroke, and the 11-10 upside-down V turned upright."""
    lms = (_frames("half_fist_moving.json") + _frames("half_fist_ring_contact.json")
           + _frames("scroll_grab_stroke_and_return.json")
           + [[[p[0], 1.0 - p[1], p[2]] for p in lm] for lm in _frames("v_sign_down_20261110.json")])
    x = np.array([pt.features(lm) for lm in lms], np.float32)
    rules = np.array([hand_posture(_pts(lm), pt.ASPECT, taught=False) for lm in lms], dtype="<U24")
    return {"x": x, "rule": rules, "rec": np.arange(len(lms), dtype=np.int32) % 4}


def _teach(tmp_path):
    down = _frames("v_sign_down_20261110.json")
    rule = [hand_posture(_pts(lm), pt.ASPECT, taught=False) for lm in down]
    ex = [{"label": "v_sign_down", "frames": down[:5], "rule_said": rule[:5] + [""], "aspect": pt.ASPECT},
          {"label": "v_sign_down", "frames": down[5:], "rule_said": rule[5:] + [""], "aspect": pt.ASPECT}]
    report = pt.train(ex, _negatives(), out=pt.CANDIDATE_PATH)
    return report


def test_examples_are_saved_as_joints_and_counted(tmp_path):
    pt.save_example("v_sign_down", [TODAY], [""])
    pt.save_example("v_sign_down", [TODAY], [""])
    assert pt.example_counts() == {"v_sign_down": 2}
    saved = json.loads(next(pt.EXAMPLES_DIR.glob("*.json")).read_text(encoding="utf-8"))
    assert set(saved) == {"label", "created", "aspect", "rule_said", "frames"}          # no picture
    assert pt.delete_examples("v_sign_down") == 2 and pt.example_counts() == {}


def test_trained_on_one_day_it_knows_another_days_upside_down_v_but_not_the_upright_one(tmp_path):
    report = _teach(tmp_path)
    assert report["can_apply"] and report["false_rate"] == 0.0
    model = pt.TaughtModel(json.loads(pt.CANDIDATE_PATH.read_text(encoding="utf-8")))
    label, p = model.predict(_pts(TODAY))                       # 2026-11-11, not in the training
    assert label == "v_sign_down" and p >= pt.THRESHOLD
    upright = [[q[0], 1.0 - q[1], q[2]] for q in TODAY]
    assert model.predict(_pts(upright))[0] == "other"


def test_applied_model_fills_in_where_the_rules_gave_nothing_in_both_posture_functions(tmp_path):
    _teach(tmp_path)
    assert hand_posture(_pts(TODAY), pt.ASPECT) == ""           # not applied yet: the rules alone
    assert pt.apply_candidate() and not pt.CANDIDATE_PATH.exists()
    pt.reset_cache()
    assert hand_posture(_pts(TODAY), pt.ASPECT) == "v_sign_down"
    assert hand_posture(_pts(TODAY), pt.ASPECT, taught=False) == ""
    assert CompositeGestureDetector._detect_base_posture(_pts(TODAY), "", set()) == "v_sign_down"
    pt.turn_off()
    pt.reset_cache()
    assert hand_posture(_pts(TODAY), pt.ASPECT) == ""


def test_the_model_replaces_only_what_the_rules_said_for_its_examples(tmp_path):
    _teach(tmp_path)
    model = pt.TaughtModel(json.loads(pt.CANDIDATE_PATH.read_text(encoding="utf-8")))
    assert model.override(_pts(TODAY), "") == "v_sign_down"
    assert model.override(_pts(TODAY), "thumb_pinky") == "thumb_pinky"    # never seen for these examples: kept


def test_too_many_misfires_cannot_be_applied(tmp_path, monkeypatch):
    monkeypatch.setattr(pt, "MAX_FALSE", -1.0)
    assert not _teach(tmp_path)["can_apply"]
