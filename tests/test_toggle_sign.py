"""The V sign (index and middle finger up, ring and little finger folded) held still switches the mouse control on / off."""
from src.motion_mode import hand_features
from src.toggle_sign import ToggleSign
from tests.test_motion_mode import hand, run


def vsign(cx=0.5, cy=0.5, thumb="out", spread=.02):
    """Index and middle up and apart (`spread` = how far each tip leans out; 0 = the two fingers held together)."""
    lm = hand(cx=cx, cy=cy, fingers="open", thumb=thumb, bent=(13, 17))
    for base, side in ((5, -1), (9, 1)):
        for n, j in enumerate((base + 1, base + 2, base + 3), start=1):
            lm[j].x += side * spread * n / 3
    return lm


def test_two_fingers_held_together_still_switch_the_control():
    """Two straight fingers held together are a shape of their own elsewhere ("two_fingers"), but the on/off sign takes
    them too: 8 of the 23 logged V signs that switched the control on had the fingers together (2026-11-11 replay)."""
    assert [e.kind for e in run(ToggleSign(), [vsign(spread=0)] * 60)[0]] == ["toggle"]
    assert [e.kind for e in run(ToggleSign(), [vsign()] * 60)[0]] == ["toggle"]


def _turned(lm, degrees):
    """The same hand turned about its wrist on the screen."""
    import math
    from types import SimpleNamespace
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    w = lm[0]
    return [SimpleNamespace(x=w.x + (p.x - w.x) * c - (p.y - w.y) * s, y=w.y + (p.x - w.x) * s + (p.y - w.y) * c, z=p.z) for p in lm]


def test_the_sign_is_index_and_middle_stretched_straight_up():
    """2026-11-11: "V 마우스제어 켜기끄기는 검지중지를 위로 바짝 폈을 때 작동해야 하는데 다른 동작 중에 많이 간섭이 들어간다"."""
    ts = ToggleSign()
    ts.aspect = 1.0
    assert [e.kind for e in run(ts, [vsign()] * 60)[0]] == ["toggle"]
    for degrees in (60, 90, -60, 180):                                       # the V leaning over, sideways, upside down
        ts = ToggleSign()
        ts.aspect = 1.0
        assert not run(ts, [_turned(vsign(), degrees)] * 60)[0], degrees
    ts = ToggleSign()
    ts.aspect = 1.0
    assert [e.kind for e in run(ts, [_turned(vsign(), 20)] * 60)[0]] == ["toggle"]   # a little off upright is still the sign
    # index and middle only half stretched (the old pose test passed them at 1.4): not the sign
    half = hand(fingers="open", bent=(13, 17))
    for base in (5, 9):
        half[base + 3].y = half[base].y - 0.045
    feats = hand_features(half)
    assert 1.4 <= min(feats["curl"][:2]) < 1.65 and not ToggleSign().pose(feats)
    assert not ToggleSign().pose(feats, model_confirmed=True)                # a model's yes does not loosen that


def test_the_pose_is_only_index_and_middle_finger_up():
    ts = ToggleSign()
    assert ts.pose(hand_features(vsign()))
    assert ts.pose(hand_features(vsign(thumb="tucked")))                       # the thumb does not matter
    assert not ts.pose(hand_features(hand(fingers="open")))                    # open hand
    assert not ts.pose(hand_features(hand(fingers="folded")))                  # fist
    assert not ts.pose(hand_features(hand(fingers="open", bent=(9, 13, 17))))  # pointing with the index only
    assert not ts.pose(hand_features(hand(fingers="open", bent=(9, 13))))      # the rock sign (index and little finger)
    assert not ts.pose(hand_features(hand(fingers="open", bent=(5, 9))))       # ring and little finger up


def test_holding_the_sign_toggles_once_and_it_must_be_let_go_before_it_counts_again():
    ts = ToggleSign()
    ev, t = run(ts, [vsign()] * 12)                                            # 0.4 s: not yet (hold 0.6 s)
    assert not ev and 0.4 < ts.progress(t) < 1.0
    ev, t = run(ts, [vsign()] * 10, t0=t)                                      # past 0.6 s
    assert [e.kind for e in ev] == ["toggle"]
    ev, t = run(ts, [vsign()] * 60, t0=t)                                      # holding on: nothing more
    assert not ev
    ev, t = run(ts, [hand(fingers="open")] * 12 + [vsign()] * 40, t0=t)        # let go, made again: toggles back
    assert [e.kind for e in ev] == ["toggle"]


def test_a_moving_or_blocked_hand_and_a_disabled_sign_never_toggle():
    assert not run(ToggleSign(), [vsign(cx=0.3 + 0.01 * i) for i in range(60)])[0]
    assert not run(ToggleSign(), [vsign()] * 60, blocked=True)[0]
    assert not run(ToggleSign({"toggle_sign_enabled": 0.0}), [vsign()] * 60)[0]
    ts = ToggleSign()
    frames = [vsign()] * 12 + [hand(fingers="open")] + [vsign()] * 22           # a noisy frame in the middle of the hold
    assert [e.kind for e in run(ts, frames)[0]] == ["toggle"]
    ts = ToggleSign()
    frames = [vsign()] * 12 + [hand(fingers="open")] * 12 + [vsign()] * 14     # a real dropout: starts over, 0.47 s left < hold
    assert not run(ts, frames)[0]
