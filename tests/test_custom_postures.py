"""2026-11-11: "리스트에 없는 동작은 억지로 끼워 맞추지 말고 없다고 하고 신규 동작으로 하고 유저에게 이름을 정하게 해줘"
and "예측 가능한 다양한 손 모양을 미리 추가"."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import custom_postures
from src.action_bindings import POSTURE_NAMES_KO


def test_a_named_shape_joins_every_posture_list_and_leaves_again(tmp_path):
    from src import llm_binding, sequence
    from src.motion_mode import custom_posture_ok
    path = tmp_path / "names.json"
    key = custom_postures.add("  여우  손 ", path)
    try:
        assert key == "custom_1" and custom_postures.load(path) == {"custom_1": "여우 손"}
        assert POSTURE_NAMES_KO[key] == "여우 손" and list(POSTURE_NAMES_KO)[-1] == "any"
        assert key in sequence.POSTURES and key in llm_binding._postures()
        assert not custom_posture_ok(key, {"lm": None})          # no rule knows it: only the taught model does
        with pytest.raises(ValueError):
            custom_postures.add("", path)
        assert custom_postures.add("여우손", path) == key          # the same name again (spaces aside): that shape
        assert custom_postures.load(path) == {"custom_1": "여우 손"}
        with pytest.raises(ValueError):
            custom_postures.add("주먹 쥐기", path)                 # a listed shape's name
        assert custom_postures.add("늑대", path) == "custom_2"
        assert custom_postures.remove(key, path) and key not in POSTURE_NAMES_KO and key not in sequence.POSTURES
        assert "custom_2" in POSTURE_NAMES_KO
    finally:
        path.unlink(missing_ok=True)
        custom_postures.register(path)
    assert not any(custom_postures.is_custom(k) for k in POSTURE_NAMES_KO)


def _hand(out, thumb="in", flip=False):
    """An upright right hand (wrist at the bottom): the fingers in `out` straight, the others folded onto the palm."""
    lm = [[.5, .8, 0.0]] + [[0, 0, 0.0] for _ in range(20)]
    for k, name in enumerate(("index", "middle", "ring", "pinky")):
        x = .44 + .04 * k
        mcp = 5 + 4 * k
        lm[mcp] = [x, .6, 0.0]
        ys = (.52, .46, .40) if name in out else (.56, .60, .64)
        for j, y in enumerate(ys):
            lm[mcp + 1 + j] = [x, y, 0.0]
    if thumb == "out":            # straight, away from the palm
        lm[1:5] = [[.45, .76, 0.0], [.39, .71, 0.0], [.33, .66, 0.0], [.27, .61, 0.0]]
    else:                       # bent across the palm
        lm[1:5] = [[.46, .76, 0.0], [.45, .70, 0.0], [.48, .66, 0.0], [.50, .64, 0.0]]
    return [SimpleNamespace(x=p[0], y=p[1], z=p[2]) for p in lm]


@pytest.mark.parametrize("out, thumb, name", [
    (("index",), "in", "index_point"), (("index",), "out", "l_sign"),
    (("pinky",), "in", "pinky_up"), (("pinky",), "out", "shaka"),
])
def test_the_shapes_told_by_which_fingers_are_out(out, thumb, name):
    from src.action_bindings import CompositeGestureDetector
    from src.motion_mode import custom_posture_ok, hand_features
    from src.pose_probe import _rule_posture
    from src.sequence import POSTURES
    lm = _hand(out, thumb)
    assert _rule_posture(lm, 1.0) == name
    assert CompositeGestureDetector._detect_base_posture_rules(lm, "", set()) == name
    assert name in POSTURE_NAMES_KO and name in POSTURES and custom_posture_ok(name, hand_features(lm))


def test_a_thumbs_down_needs_the_thumb_under_a_fist_that_does_not_point_down_itself():
    from src.pose_probe import pattern_posture
    # a fist lying sideways (the wrist to the right of the knuckles), the thumb straight down under it
    lm = [[.7, .6]] + [[.66, .66], [.62, .72], [.60, .80], [.58, .88]]
    for y in (.54, .58, .62, .66):
        lm += [[.5, y], [.48, y], [.52, y], [.56, y]]
    side = [SimpleNamespace(x=p[0], y=p[1], z=0.0) for p in lm]
    assert pattern_posture(side, 1.0) == "thumbs_down"
    lifted = [SimpleNamespace(x=p.x, y=p.y, z=0.0) for p in side]
    lifted[4] = SimpleNamespace(x=.6, y=.67, z=0.0)                               # the thumb tip not under the hand
    assert pattern_posture(lifted, 1.0) != "thumbs_down"
    # the same hand turned so that the fist itself points down (wrist on top): a fist, not this sign
    turned = [SimpleNamespace(x=.7 + (p.y - .6), y=.6 - (p.x - .7), z=0.0) for p in side]
    assert pattern_posture(turned, 1.0) != "thumbs_down"
    assert pattern_posture(_hand(("index", "middle", "ring")), 1.0) == ""         # "3" = the thumb + little finger pinch hand


def test_a_movement_that_is_no_stroke_and_no_drawing_is_not_forced_into_one():
    """A wiggle: far enough to be a movement, not straight, no drawing the app knows."""
    import math
    from src.pose_probe import PoseProbe
    probe = PoseProbe()
    probe.start(0.0)
    for i in range(60):
        u = i / 59
        probe.step(3.05 + i / 30, "fist", (5 + 3 * u, 5 + 1.2 * math.sin(u * 6 * math.pi)), 1.0, (90.0, 90.0))
    probe.finish_if_due(10.0)
    v = probe.result
    assert v["state"] == "done" and v.get("kind") in ("motion", "unknown_move", "drawn"), v
    if v.get("kind") == "unknown_move":
        assert v["unknown"] and "목록에 없는 움직임" in v["message"] and not v["approx"]
    # a movement of a hand with no listed shape: no shape is made up for it
    probe.start(20.0)
    for i in range(60):
        probe.step(23.05 + i / 30, "", (5 + 3 * i / 59, 5.0), 1.0, (90.0, 90.0))
    probe.finish_if_due(30.0)
    assert probe.result["unknown"] and probe.result["posture"] == "" and "kind" not in probe.result


def test_a_look_named_by_the_user_is_that_shape_from_then_on_not_what_the_rules_said(tmp_path):
    """2026-11-11 report: a sideways thumb told as a fist and named "옆 따봉" - "이렇게 주먹쥐기로 등록되면 어떻게든
    주먹쥐면 저 신호가 잡히는거 아닌가?"."""
    from src import llm_binding as lb
    from src.pose_probe import relabelled
    path = tmp_path / "names.json"
    key = custom_postures.add("옆 따봉", path)
    try:
        fist = {"state": "done", "posture": "fist", "name": "주먹 쥐기", "share": .57, "approx": False, "everyday": True,
                "gesture_key": ""}
        named = relabelled(fist, key)
        assert named["posture"] == key and named["name"] == "옆 따봉" and named["taught"] == key and not named["everyday"]
        # the AI is given the named shape, and a gesture made for "이 손모양" holds that shape - not the fist
        block = lb.context_block(named, "", [])
        assert "옆 따봉" in block and "주먹" not in block
        stand_in = lb.with_shown([], named)[0]
        assert stand_in["new_posture"] == key and not stand_in["everyday"]
        # confirming what the rules said changes nothing but the mark
        same = relabelled(fist, "fist")
        assert same["posture"] == "fist" and same["everyday"] and same["taught"] == "fist"
        # a look that was "not in the list" takes the name too
        none = {"state": "done", "posture": "", "name": "목록에 없는 손 모양", "unknown": True, "gesture_key": ""}
        assert relabelled(none, key)["posture"] == key and not relabelled(none, key)["unknown"]
    finally:
        path.unlink(missing_ok=True)
        custom_postures.register(path)


def test_the_guide_talks_about_the_shape_being_taught_only_and_leads_to_the_next_step():
    """2026-11-11: the screen listed every taught shape ("거꾸로 V 인식 89%") while the user was teaching 옆따봉."""
    from src.posture_teach import guide
    counts = {"custom_2": 1, "v_sign_down": 2}
    applied = {"examples": {"v_sign_down": 2}, "recognition": {"v_sign_down": .89}, "false_rate": 0.0}
    one = guide("custom_2", "옆따봉", counts, "", None, applied)
    assert "견본 1개" in one["text"] and "한 번 더 보여주기" in one["text"] and "③ 견본 1개 …" in one["steps"]
    assert "거꾸로" not in one["text"] + one["steps"] and "89" not in one["text"]
    counts["custom_2"] = 2
    report = {"examples": {"custom_2": 2, "v_sign_down": 2}, "recognition": {"custom_2": .8, "v_sign_down": .89},
              "false_rate": .001, "can_apply": True}
    ready = guide("custom_2", "옆따봉", counts, "ready", report, applied)
    assert "'옆따봉' 인식 80%" in ready["text"] and "[적용]" in ready["text"] and "더 정확해져요" in ready["text"]
    assert "89" not in ready["text"] and "④ 학습 ✓" in ready["steps"] and "⑤ 적용 …" in ready["steps"]
    bad = guide("custom_2", "옆따봉", counts, "ready", {**report, "false_rate": .03, "can_apply": False}, applied)
    assert "쓸 수 없어요" in bad["text"] and "실행되지 않아요" in bad["text"] and "[적용]을 누르면" not in bad["text"]
    done = guide("custom_2", "옆따봉", counts, "applied", None, report)
    assert "적용됨" in done["text"] and "⑤ 적용 ✓" in done["steps"] and "더 정확해져요" in done["text"]
    # good and enough: no nagging for more
    counts["custom_2"] = 4
    fine = guide("custom_2", "옆따봉", counts, "ready", {**report, "recognition": {"custom_2": .98}}, applied)
    assert "더 정확해져요" not in fine["text"] and "③ 견본 4개 ✓" in fine["steps"]
    assert guide("", "", counts, "", None, applied) == {"steps": "", "text": ""}


def test_a_taught_shape_may_replace_what_the_rules_say_in_use_too():
    """The engine says "fist", the composite detector then says fist or fingers bent: both are what the rules call the
    examples in use, so the model may replace them."""
    from src.posture_teach import _rule_answers
    data = json.loads((Path(__file__).parent / "fixtures" / "index_point_20261111.json").read_text(encoding="utf-8"))
    said = _rule_answers({"frames": data["frames"]})
    assert "index_point" in said and all(isinstance(s, str) for s in said)


def test_deleting_a_named_shape_takes_its_gestures_examples_and_place_in_the_model_with_it():
    """2026-11-11 request: "잘못 지은 손 모양 이름 지우는 화면". (conftest points every store at a temporary folder.)"""
    import src.posture_teach as pt
    from src.action_bindings import get_action_registry
    from src.sequence import SequenceStore
    wrong = custom_postures.add("옆따봉ㅇ")
    keep = custom_postures.add("늑대")
    try:
        reg = get_action_registry()
        reg.register_composite_gesture("", "옆따봉ㅇ 유지", wrong, "hold", "hotkey", "f5")
        reg.register_composite_gesture("", "늑대 유지", keep, "hold", "hotkey", "f6")
        seq = SequenceStore().add("늑대 다음 오타", [keep, wrong])
        frame = [[0.0, 0.0, 0.0]] * 21
        pt.save_example(wrong, [frame])
        pt.save_example(wrong, [frame])
        pt.save_example(keep, [frame])
        model = {"classes": ["other", wrong, keep], "replaces": {wrong: [""], keep: [""]},
                 "report": {"examples": {wrong: 2, keep: 1}, "recognition": {wrong: 1.0, keep: None}}}
        pt.MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        pt.MODEL_PATH.write_text(json.dumps(model), encoding="utf-8")
        assert {k for k, _, _ in custom_postures.uses(wrong)} == {"composite", "sequence"}

        assert custom_postures.delete(wrong) == {"gestures": 2, "examples": 2}
        assert wrong not in POSTURE_NAMES_KO and custom_postures.load() == {keep: "늑대"}
        assert [c["base_posture"] for c in get_action_registry().composite_gestures.values()] == [keep]
        assert all(r["key"] != seq for r in SequenceStore().rows())
        assert pt.example_counts() == {keep: 1}
        left = json.loads(pt.MODEL_PATH.read_text(encoding="utf-8"))
        assert left["replaces"] == {keep: [""]} and left["report"]["examples"] == {keep: 1}     # never told again
        assert custom_postures.delete(wrong) == {} and custom_postures.delete("fist") == {}     # gone / not a named one
    finally:
        custom_postures.PATH.unlink(missing_ok=True)
        custom_postures.register()


class _Scripted:
    """A CompositeGestureDetector fed a script of postures (one per frame, 30 fps)."""

    def __init__(self, tmp_path, holds):
        from src.action_bindings import ActionBindingRegistry, CompositeGestureDetector
        reg = ActionBindingRegistry(tmp_path / "b.json")
        for posture, seconds in holds.items():
            reg.register_composite_gesture("", posture + " 유지", posture, "hold", "hotkey", "f5", hold_seconds=seconds)
        script = self.script = []

        class Det(CompositeGestureDetector):
            @staticmethod
            def _detect_base_posture(landmarks, active_gesture, pinched_fingers):
                return script.pop(0)

        self.det, self.t = Det(reg), 0.0
        self.lm = [SimpleNamespace(x=.5, y=.5, z=0.0) for _ in range(21)]

    def run(self, postures):
        fired = []
        for p in postures:
            self.script.append(p)
            out = self.det.step(self.t, self.lm, "", set())
            if out:
                fired.append((round(self.t, 2), out["base_posture"]))
            self.t += 1 / 30
        return fired


def test_a_hold_runs_once_however_long_the_shape_is_held_and_flickers(tmp_path):
    """2026-11-11 report: "youtube 페이지를 여러 개 한꺼번에 아주 늦게 뒤에 여는 문제가 반복됨" - the shape of a hand held
    up for seconds flickers, and every flicker started a new hold."""
    s = _Scripted(tmp_path, {"custom_2": .5})
    held = (["custom_2"] * 25 + ["fist"] * 8) * 6             # 6.6 s: the shape, broken by 0.27 s of "fist" again and again
    assert [p for _, p in s.run(held)] == ["custom_2"]         # once (it was 6 times)
    assert s.run([""] * 20 + ["custom_2"] * 30) == []          # away for 0.67 s only: still the same hold
    again = s.run([""] * 40 + ["custom_2"] * 30)               # away for more than a second, then held again
    assert [p for _, p in again] == ["custom_2"]


def test_another_hold_does_not_fire_right_after_one(tmp_path):
    """... "옆따봉을 했는데 거꾸로 V로 등록한 명령이 나오거나": while (or just after) one shape is held, frames read as
    another shape must not run that one's command too."""
    s = _Scripted(tmp_path, {"custom_2": .5, "v_sign_down": .4})
    fired = s.run(["custom_2"] * 20 + ["v_sign_down"] * 20 + ["custom_2"] * 20)      # 0.67 s read as the other shape
    assert [p for _, p in fired] == ["custom_2"]
    later = s.run([""] * 60 + ["v_sign_down"] * 20)                                  # 2 s later, on purpose
    assert [p for _, p in later] == ["v_sign_down"]


def test_a_v_needs_index_and_middle_straight_in_3d_for_the_rules_and_for_the_taught_model():
    """A fist pointing at the camera: its wrist-to-knuckle length shrinks in the picture, so the finger ratios grow and
    the picture alone calls it a V."""
    from src.pose_probe import _finger_ratios, _rule_posture, is_v, is_v_hand
    from src.posture_teach import plausible
    data = json.loads((Path(__file__).parent / "fixtures" / "v_sign_down_20261110.json").read_text(encoding="utf-8"))
    real = [SimpleNamespace(x=p[0], y=p[1], z=p[2]) for p in data["frames"][0]]
    assert is_v_hand(real, 720 / 1280) and plausible("v_sign_down", real) and not plausible("v_sign", real)
    # index and middle 2 knuckle-lengths long in the picture but folded toward the camera (z): short in 3D
    lm = [[.5, .52, 0.0]] + [[.5, .5, 0.0]] * 4
    for k, y in enumerate((.58, .58, .53, .53)):
        x = .47 + .02 * k
        lm += [[x, .5, -.25], [x, (y + .5) / 2, -.2], [x, y, -.1], [x, y, -.02]]
    fake = [SimpleNamespace(x=p[0], y=p[1], z=p[2]) for p in lm]
    assert is_v(_finger_ratios(fake)) and not is_v_hand(fake, 1.0)
    assert _rule_posture(fake, 1.0) not in ("v_sign", "v_sign_down") and not plausible("v_sign_down", fake, 1.0)
    assert plausible("custom_9", fake)                           # a shape the user named has no such check


def test_the_fixture_of_the_report_is_listed():
    data = json.loads((Path(__file__).parent / "fixtures" / "index_point_20261111.json").read_text(encoding="utf-8"))
    assert len(data["frames"]) == 10


def test_index_and_middle_held_together_is_its_own_shape_and_the_upside_down_v_stays_one():
    """2026-11-11: "손가락이 붙었을 때랑 떨어졌을 때를 구분하게 하고 별도로 다른 동작을 연결"."""
    from src.action_bindings import CompositeGestureDetector
    from src.motion_mode import custom_posture_ok, hand_features
    from src.pose_probe import V_TOGETHER, _rule_posture, v_shape, v_spread
    from src.sequence import POSTURES
    together = _hand(("index", "middle"))                       # the two fingers straight up side by side
    spread = _hand(("index", "middle"))
    for joint, dx in ((6, -.01), (7, -.02), (8, -.03), (10, .01), (11, .02), (12, .03)):
        spread[joint].x += dx                                   # the tips 2.5 knuckle gaps apart
    assert v_spread(together) == pytest.approx(1.0) and v_spread(spread) == pytest.approx(2.5) and 1.0 < V_TOGETHER < 2.5
    for lm, name in ((together, "two_fingers"), (spread, "v_sign")):
        assert v_shape(lm) == _rule_posture(lm, 1.0) == name
        assert CompositeGestureDetector._detect_base_posture_rules(lm, "", set()) == name
    assert "two_fingers" in POSTURE_NAMES_KO and "two_fingers" in POSTURES
    assert custom_posture_ok("two_fingers", hand_features(together)) and not custom_posture_ok("two_fingers", hand_features(spread))
    # upside down the fingers are seen end-on and look together either way (the person's uses: spread 1.47 at the median)
    for lm in (together, spread):
        down = [SimpleNamespace(x=p.x, y=1.6 - p.y, z=p.z) for p in lm]
        assert v_shape(down) == "v_sign_down"
    assert v_shape(_hand(("index",))) == ""


def _held(s, postures, xs=None):
    """Feeds `postures` (one per frame) to a _Scripted detector with the palm at xs[i] (default: where it was)."""
    fired = []
    for i, p in enumerate(postures):
        if xs is not None:
            for q in s.lm:
                q.x = xs[i]
        s.script.append(p)
        out = s.det.step(s.t, s.lm, "", set())
        if out:
            fired.append(round(s.t, 2))
        s.t += 1 / 30
    return fired


def test_an_open_hand_hold_survives_a_moment_of_another_shape_and_runs_once_the_hand_has_stopped(tmp_path):
    """2026-11-11 report: "손 펴기 유지가 작동도 잘 안 되는데 … 손가락 펴도 손 위치가 이동하면 안 되는 거임??"."""
    # a few frames read as another shape (.1 s) do not restart the second; a real change (.3 s) does
    s = _Scripted(tmp_path, {"open_hand": 1.0})
    assert len(_held(s, ["open_hand"] * 14 + ["v_sign"] * 3 + ["open_hand"] * 16)) == 1
    s = _Scripted(tmp_path / "b", {"open_hand": 1.0})
    assert _held(s, ["open_hand"] * 14 + ["v_sign"] * 9 + ["open_hand"] * 16) == []
    # the hand turned its edge to the camera (read as the knife hand): still the open hand, as nothing is bound to the knife hand
    s = _Scripted(tmp_path / "c", {"open_hand": 1.0})
    assert len(_held(s, ["open_hand"] * 10 + ["knife_hand"] * 12 + ["open_hand"] * 11)) == 1
    s = _Scripted(tmp_path / "d", {"open_hand": 1.0, "knife_hand": .5})
    assert _held(s, ["open_hand"] * 10 + ["knife_hand"] * 12 + ["open_hand"] * 11) == []     # the knife hand has its own gesture
    # the hand opened while moving, then stopped: it runs a second after it stopped (it never ran before)
    moving = [.3 + .2 * min(1.0, i / 15) for i in range(60)]                  # .2 of the frame in the first half second
    s = _Scripted(tmp_path / "e", {"open_hand": 1.0})
    fired = _held(s, ["open_hand"] * 60, moving)
    assert len(fired) == 1 and 1.2 <= fired[0] <= 1.7                           # (the last .06 of the way counts as still)
    s = _Scripted(tmp_path / "f", {"open_hand": 1.0})
    s.det.STILL_ROLLING = False                                                # as it was
    assert _held(s, ["open_hand"] * 60, moving) == []
    # a hand that keeps moving is moving the cursor, not holding
    s = _Scripted(tmp_path / "g", {"open_hand": 1.0})
    assert _held(s, ["open_hand"] * 90, [.2 + .006 * i for i in range(90)]) == []


def test_an_open_hand_being_held_stays_one_while_the_fingers_only_relax_a_little():
    from src.action_bindings import ActionBindingRegistry, CompositeGestureDetector
    from src.pose_probe import _finger_ratios
    det = CompositeGestureDetector.__new__(CompositeGestureDetector)
    hand = _hand(("index", "middle", "ring", "pinky"))
    relaxed = _hand(("index", "middle", "ring", "pinky"))
    for j, y in zip((6, 7, 8), (.56, .53, .50)):             # the index tips toward the camera: shorter, still straight
        relaxed[j].y = y
    hooked = _hand(("index", "middle", "ring", "pinky"))
    hooked[8].y = hooked[5].y - .085                         # the index tip folded back at the end joint (2026-11-11:
    assert not det._open_goes_on(hooked, "", [])             # "마디도 다 펴졌을 때를 기준으로" - no longer an open hand)
    bent = _hand(("middle", "ring", "pinky"))                 # the index folded: the hand changed
    assert min(_finger_ratios(hand)) >= 1.55 and 1.35 <= min(_finger_ratios(relaxed)) < 1.55 and min(_finger_ratios(bent)) < 1.35
    assert det._open_goes_on(relaxed, "", []) and not det._open_goes_on(bent, "", [])
    assert not det._open_goes_on(relaxed, "thumb_index", [])                   # a pinch is another hand whatever the fingers
    assert det._open_goes_on(hand, "knife_hand", []) and not det._open_goes_on(hand, "knife_hand", [{"base_posture": "knife_hand"}])
