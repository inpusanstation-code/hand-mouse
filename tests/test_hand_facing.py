"""An open hand showing its back is told from one showing its palm, and can carry its own command (2026-11-11 request:
"손바닥을 카메라로 향하는지, 손등을 카메라로 향하는지를 구분해서 별개의 명령으로")."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import src.pose_probe as pp
from src.action_bindings import ActionBindingRegistry, CompositeGestureDetector, POSTURE_NAMES_KO
from src.gesture_preview import drawn
from src.path_gesture import PathDetector
from src.sequence import POSTURES, SequenceDetector


def open_hand(back=False, label="Left"):
    """The drawn open hand: a right hand in the mirrored picture (label "Left"), palm to the camera, thumb nearer the
    camera. `back`: the same hand turned round (the picture flips left-right, the thumb goes behind). label "Right":
    the other hand (the mirror image of all that)."""
    pts = [[x, y, 0.0] for x, y in drawn("open_hand")]
    pts[4][2] = pts[3][2] = -.06
    if back:
        pts = [[1 - x, y, -z] for x, y, z in pts]
    if label == "Right":
        pts = [[1 - x, y, z] for x, y, z in pts]
    return [SimpleNamespace(x=x, y=y, z=z) for x, y, z in pts]


@pytest.fixture(autouse=True)
def _label():
    pp.set_hand_label("Left")
    yield
    pp.set_hand_label("")


def test_palm_and_back_are_told_apart_for_either_hand():
    assert pp.hand_posture(open_hand()) == "open_hand"
    assert pp.hand_posture(open_hand(back=True)) == "open_hand_back"
    pp.set_hand_label("Right")
    assert pp.hand_posture(open_hand(label="Right")) == "open_hand"
    assert pp.hand_posture(open_hand(back=True, label="Right")) == "open_hand_back"
    assert "open_hand_back" in POSTURE_NAMES_KO and "open_hand_back" in POSTURES and drawn("open_hand_back")


def test_an_unknown_hand_or_a_disagreeing_thumb_is_never_the_back():
    pp.set_hand_label("")                               # which hand is not known: the open hand, as before
    assert pp.hand_posture(open_hand(back=True)) == "open_hand"
    pp.set_hand_label("Left")
    hand = open_hand(back=True)
    hand[4].z = -.2                                     # the turn says back, the thumb says palm: not sure -> open hand
    assert pp.hand_posture(hand) == "open_hand"
    assert pp.hand_posture(open_hand(back=True), taught=False) == "open_hand"     # the bare rules (teaching) do not split
    seen = []
    import threading
    t = threading.Thread(target=lambda: seen.append(pp.hand_label()))            # another thread (training) sees no label
    t.start(); t.join()
    assert seen == [""]


def pose_for(hand, side="Left", off=.02):
    """Pose joints 11-16 ([x, y, visibility]; shoulders, elbows, wrists, left then right) with `side`'s wrist on the hand."""
    w = hand[0]
    here, away = [w.x + off, w.y, .9], [w.x + .6, w.y, .9]
    wrists = [here, away] if side == "Left" else [away, here]
    return [[.4, .3, .9], [.6, .3, .9], [.4, .5, .9], [.6, .5, .9]] + wrists


def test_the_arm_confirms_the_hand_and_then_the_turn_alone_decides():
    hand = open_hand(back=True)
    hand[4].z = -.2                                     # the thumb's depth disagrees (it did in 24 % of the recordings)
    assert pp.arm_label(pose_for(hand, "Left"), hand) == "Left"
    assert pp.arm_label(pose_for(hand, "Right"), hand) == "Right"
    assert pp.arm_label(None, hand) == "" and pp.arm_label(pose_for(hand, "Left", off=.5), hand) == ""    # too far
    faint = pose_for(hand, "Left")
    faint[4][2] = .2
    assert pp.arm_label(faint, hand) == ""              # the wrist is not really seen
    pp.set_hand_label("Left", pp.arm_label(pose_for(hand, "Left"), hand))
    assert pp.hand_posture(hand) == "open_hand_back"    # the arm says it is this hand: back
    pp.set_hand_label("Left", "Right")                  # the arm says the other hand: it does not overrule the label,
    assert pp.hand_posture(hand) == "open_hand"         # ... and the thumb still disagrees
    pp.set_hand_label("Left", "Left")
    assert pp.hand_posture(open_hand()) == "open_hand"  # a palm stays a palm whatever the arm says


def held(det, hand, seconds=1.3):
    t, hit = 10.0, None
    while t < 10.0 + seconds and hit is None:
        hit = det.step(t, hand, "", set(), 1.0, scope="normal")
        t += 1 / 30
    return hit


def tilted(hand, deg=-50.0):
    """The hand tipped about the left-right axis through the wrist: a palm then faces up, a back's palm the floor."""
    import math
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    w = hand[0]
    return [SimpleNamespace(x=p.x, y=w.y + (p.y - w.y) * c - (p.z - w.z) * s, z=w.z + (p.y - w.y) * s + (p.z - w.z) * c)
            for p in hand]


def test_the_open_hand_is_named_by_where_the_palm_faces():
    """2026-11-12: "기존 명령은 손바닥을 카메라로 향할때만 … 바닥으로 할때나 위로 할때 다른 명령을"."""
    assert pp.faced("open_hand", open_hand()) == "open_hand"
    assert pp.faced("open_hand", open_hand(back=True)) == "open_hand_back"
    assert pp.faced("open_hand", tilted(open_hand(back=True))) == "open_hand_down"
    assert pp.faced("open_hand", tilted(open_hand())) == "open_hand_up"
    assert pp.faced("open_hand", tilted(open_hand(), -20)) == "open_hand"          # a palm leaning back a little
    assert pp.faced("fist", tilted(open_hand())) == "fist"                         # only the open hand is split
    pp.set_hand_label("Right")                                                     # the other hand: the mirror image
    assert pp.faced("open_hand", tilted(open_hand(back=True, label="Right"))) == "open_hand_down"
    assert pp.faced("open_hand", tilted(open_hand(label="Right"))) == "open_hand_up"
    pp.set_hand_label("")                                                          # which hand is not known: not split
    assert pp.faced("open_hand", tilted(open_hand())) == "open_hand"
    for shape in pp.FACINGS:
        assert shape in POSTURE_NAMES_KO and shape in POSTURES and drawn(shape) and shape in pp.EVERYDAY_POSTURES


def test_the_open_hand_command_is_for_the_palm_to_the_camera_only(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "faced", lambda posture, lm, aspect=1.0: "open_hand_back" if posture == "open_hand" and pp.back_of_hand(lm, 1.0) else posture)
    reg = ActionBindingRegistry(tmp_path / "b.json")
    palm = reg.register_composite_gesture("", "", "open_hand", "hold", "hotkey", "win+d", hold_seconds=1.0)["key"]
    assert held(CompositeGestureDetector(reg), open_hand())["key"] == palm
    assert held(CompositeGestureDetector(reg), open_hand(back=True)) is None       # not the palm to the camera: nothing
    back = reg.register_composite_gesture("", "", "open_hand_back", "hold", "hotkey", "alt+tab", hold_seconds=1.0)["key"]
    assert back != palm
    assert held(CompositeGestureDetector(reg), open_hand())["key"] == palm
    assert held(CompositeGestureDetector(reg), open_hand(back=True))["key"] == back


def test_the_back_and_the_palm_down_hand_stand_in_for_each_other_when_one_is_bound():
    assert pp.unless_bound("open_hand_back", {"open_hand"}) == "open_hand_back"
    assert pp.unless_bound("open_hand_down", {"open_hand"}) == "open_hand_down"
    assert pp.unless_bound("open_hand_back", {"open_hand", "open_hand_down"}) == "open_hand_down"
    assert pp.unless_bound("open_hand_down", {"open_hand_back"}) == "open_hand_back"
    assert pp.unless_bound("open_hand_down", {"open_hand_back", "open_hand_down"}) == "open_hand_down"
    assert pp.unless_bound("open_hand_up", {"open_hand", "open_hand_down"}) == "open_hand_up"
    assert pp.unless_bound("open_hand", {"open_hand_down"}) == "open_hand"


def test_sequences_and_shape_drawings_take_the_back_only_when_they_ask_for_it():
    det = SequenceDetector()
    t = 0.0
    fired = None
    for shape in ("fist", "open_hand_back"):
        for _ in range(12):
            fired = fired or det.step(t, shape, {"seq_a": ("fist", "open_hand")})
            t += 1 / 30
    assert fired is None
    det, t, fired = SequenceDetector(), 0.0, None
    for shape in ("fist", "open_hand_back"):
        for _ in range(12):
            fired = fired or det.step(t, shape, {"seq_a": ("fist", "open_hand"), "seq_b": ("fist", "open_hand_back")})
            t += 1 / 30
    assert fired == "seq_b"
    paths = PathDetector()
    paths.step(0.0, "open_hand_back", (.5, .5), .1, {"path_a": ("open_hand", "draw_circle")}, None)
    assert paths.posture != "open_hand"
    paths = PathDetector()
    paths.step(0.0, "open_hand_back", (.5, .5), .1, {"path_a": ("open_hand", "draw_circle"),
                                                    "path_b": ("open_hand_back", "draw_circle")}, None)
    assert paths.posture == "open_hand_back"


def test_the_ai_can_make_a_gesture_for_the_back_of_the_hand(tmp_path):
    import src.llm_binding as lb
    reg = ActionBindingRegistry(tmp_path / "b.json")
    answer = {"summary": "", "questions": [], "proposals": [{
        "gesture_key": lb.NEW, "new_name": "손등 유지", "new_posture": "open_hand_back", "new_trigger": "hold",
        "new_sequence": [], "app_match": "", "action_type": "hotkey", "action_value": "alt+tab", "steps": [],
        "enabled": True, "motion_only": False, "reason": ""}]}
    row = lb.check(answer, lb.gesture_list(reg))["proposals"][0]
    assert row["ok"] and row["risky"]                       # an everyday hand: ticked by the person, not by default
    row["checked"] = True
    lb.apply([row], reg)
    comp = next(iter(reg.composite_gestures.values()))
    assert comp["base_posture"] == "open_hand_back" and comp["hold_seconds"] == lb.HOLD_MIN_EVERYDAY
    assert "open_hand_back" in lb.system_prompt(lb.gesture_list(reg))


def loosened(hand, factor):
    """The same hand with every finger a little shorter in the picture (straight joints, the tips nearer the wrist):
    what an open hand that relaxes while it is held looks like to the rules ("no shape")."""
    out = [SimpleNamespace(x=p.x, y=p.y, z=p.z) for p in hand]
    for mcp in (5, 9, 13, 17):
        for i in (mcp + 1, mcp + 2, mcp + 3):
            out[i] = SimpleNamespace(x=hand[mcp].x + (hand[i].x - hand[mcp].x) * factor,
                                     y=hand[mcp].y + (hand[i].y - hand[mcp].y) * factor,
                                     z=hand[mcp].z + (hand[i].z - hand[mcp].z) * factor)
    return out


def test_a_held_palm_down_hand_that_loosens_is_still_that_hand(tmp_path):
    """2026-11-12 (the check after the palm facings were added): the "an open hand being held stays one while it only
    loosens" rule knew the palm-to-the-camera hand only, so a hold on the palm-to-the-floor hand ended with the first
    relaxed finger. It goes for every facing now, and the loosened hand is asked again where its palm faces."""
    from src.pose_probe import _finger_ratios
    reg = ActionBindingRegistry(tmp_path / "b.json")
    down = reg.register_composite_gesture("", "", "open_hand_down", "hold", "hotkey", "f5", hold_seconds=1.0)["key"]
    palm = reg.register_composite_gesture("", "", "open_hand", "hold", "hotkey", "win+d", hold_seconds=1.0)["key"]
    firm = tilted(loosened(open_hand(back=True), 1.25))                  # fingers stretched: clearly open also when tipped
    assert CompositeGestureDetector._detect_base_posture(firm, "", set()) == "open_hand_down"
    loose = next(h for h in (tilted(loosened(open_hand(back=True), f)) for f in (1.0, .95, .9, .85, .8))
                 if 1.35 <= min(_finger_ratios(h)) < 1.55)
    assert CompositeGestureDetector._detect_base_posture(loose, "", set()) == ""        # by itself: no shape

    def run(frames):
        det, t, hit = CompositeGestureDetector(reg), 10.0, None
        for hand in frames:
            hit = hit or det.step(t, hand, "", set(), 1.0, scope="normal")
            t += 1 / 30
        return hit

    assert run([firm] * 8 + [loose] * 34)["key"] == down                 # loosened while held: the hold goes on
    assert run([loose] * 42) is None                                     # never clearly open: nothing starts
    camera = open_hand()
    slack = next(h for h in (loosened(camera, f) for f in (.8, .75, .7, .65, .6, .55)) if 1.35 <= min(_finger_ratios(h)) < 1.55)
    assert run([camera] * 8 + [slack] * 34)["key"] == palm               # the palm-to-the-camera hand: as before
    # a hand held palm to the camera that loosens AND turns to the floor is not the camera hand any more
    assert run([camera] * 8 + [loose] * 20) is None
    assert set(pp.FACINGS) <= set(CompositeGestureDetector.MOVING_HANDS)  # a resting hand, whichever way it faces
