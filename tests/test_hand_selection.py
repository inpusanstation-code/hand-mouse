from types import SimpleNamespace
from src.hand_selection import HandFollower, HandSelection, physical_side, selected_detection


def detection(side, score=0.95):
    return SimpleNamespace(handedness=side, score=score)


def hand_at(side, x=.5, y=.5, size=.04, score=.95):
    corners = [SimpleNamespace(x=x - size / 2, y=y - size / 2), SimpleNamespace(x=x + size / 2, y=y + size / 2)]
    return SimpleNamespace(handedness=side, score=score, landmarks=corners)


def following():
    """Mirrored camera, right hand as the control hand: MediaPipe should say "Left"."""
    follower = HandFollower()
    assert follower.select([hand_at("Left")], "Right", True, 0.0) is not None
    assert not follower.followed
    return follower


def test_follower_needs_a_strict_reading_to_start():
    follower = HandFollower()
    assert follower.select([hand_at("Right")], "Right", True, 0.0) is None
    assert follower.select([hand_at("Left", score=.5)], "Right", True, .1) is None
    assert follower.select([], "Right", True, .2) is None


def test_follower_keeps_a_flipped_or_unsure_hand_and_corrects_its_side():
    follower = following()
    flipped = hand_at("Right", x=.51)
    kept = follower.select([flipped], "Right", True, .1)
    assert follower.followed and kept.handedness == "Left" and kept.landmarks is flipped.landmarks
    assert flipped.handedness == "Right"
    assert follower.select([hand_at("Left", x=.52, score=.5)], "Right", True, .2) is not None
    assert follower.followed
    assert follower.select([hand_at("Left", x=.52)], "Right", True, .3) is not None
    assert not follower.followed


def test_follower_refuses_a_hand_elsewhere_or_of_another_size():
    assert following().select([hand_at("Right", x=.7)], "Right", True, .1) is None
    assert following().select([hand_at("Right", y=.7)], "Right", True, .1) is None
    assert following().select([hand_at("Right", size=.1)], "Right", True, .1) is None
    assert following().select([hand_at("Right", size=.01)], "Right", True, .1) is None


def test_follower_takes_the_one_hand_in_place_when_the_other_is_elsewhere():
    """2026-11-11: with two detections it used to give up, and the virtual hand vanished."""
    follower = following()
    near = hand_at("Right", x=.51)
    kept = follower.select([near, hand_at("Right", x=.8)], "Right", True, .1)
    assert follower.followed and kept.landmarks is near.landmarks and kept.handedness == "Left"


def test_follower_refuses_two_hands_when_both_could_be_it():
    follower = following()
    assert follower.select([hand_at("Right", x=.49), hand_at("Right", x=.52)], "Right", True, .1) is None
    assert not follower.followed


def test_the_same_hand_found_twice_counts_once():
    """2026-11-11 failure logs: 'Left,Left' (206 frames) and 'Right,Right' (93) dropped the control hand."""
    from src.hand_selection import merge_duplicates
    best, twin = hand_at("Left", score=.99), hand_at("Left", x=.505, score=.81)
    assert merge_duplicates([twin, best]) == [best]
    assert selected_detection(merge_duplicates([twin, best]), "Right", True) is best
    other = hand_at("Left", x=.8)
    assert len(merge_duplicates([best, other])) == 2              # two real hands stay two
    follower = HandFollower()
    assert follower.select([best, twin], "Right", True, 0.0) is best   # no history needed for a duplicate


def test_follower_stops_after_a_long_gap():
    follower = following()
    assert follower.select([], "Right", True, .4) is None
    assert follower.select([hand_at("Right")], "Right", True, .49) is not None
    assert follower.select([hand_at("Right")], "Right", True, 1.0) is None


def test_follower_stops_without_a_strict_reading_and_starts_again_with_one():
    follower = following()
    t = 0.0
    while t < 2.9:
        t += .1
        assert follower.select([hand_at("Right")], "Right", True, t) is not None
    assert follower.select([hand_at("Right")], "Right", True, 3.1) is None
    assert follower.select([hand_at("Left")], "Right", True, 3.2) is not None
    assert follower.select([hand_at("Right")], "Right", True, 3.3) is not None
    assert follower.followed


def test_follower_forgets_the_hand_when_the_control_hand_changes():
    follower = following()
    assert follower.select([hand_at("Right")], "Left", True, .1) is not None
    assert not follower.followed
    assert follower.select([hand_at("Left")], "Left", True, .2) is not None
    assert follower.followed
    follower = following()
    follower.reset()
    assert follower.select([hand_at("Right")], "Right", True, .1) is None


def test_setup_accepts_only_one_stable_high_confidence_hand():
    gate = HandSelection()
    left = detection("Right")
    for i in range(5):
        assert gate.observe([left], True, i * .1) == ""
    assert gate.observe([left, detection("Left")], True, .5) == ""
    for i in range(50):
        assert gate.observe([left], True, 1 + i * .1) == ""
    assert gate.observe([left], True, 6.0) == "Left"
    assert gate.observe([left], True, 6.4) == ""
    assert gate.seconds_remaining(6.4) == 5.0


def test_selected_hand_is_used_even_when_opposite_hand_appears_first():
    left, right = detection("Right"), detection("Left")
    assert physical_side(left, False) == "Right"
    assert selected_detection([right, left], "Left", True) is left
    assert selected_detection([right], "Left", True) is None
    assert selected_detection([detection("Right", .4)], "Left", True) is None
    assert selected_detection([left, left], "Left", True) is None


def test_a_small_reading_inside_the_hand_never_wins_over_the_hand():
    """2026-11-11 evening ("가상 손이 위로 점프 튀었다가 제자리로 2번 정도 반복"): MediaPipe gave the hand and, inside it at
    the fingers, a hand a third of its size - both "Left" with scores .97-1.00 - and whichever scored higher was used."""
    from src.hand_selection import merge_duplicates
    follower = HandFollower()
    picked = []
    for n in range(12):
        hand = hand_at("Left", x=.47, y=.76, size=.30, score=.98 if n % 2 else 1.0)
        part = hand_at("Left", x=.46, y=.65, size=.11, score=1.0 if n % 2 else .98)       # the scores take turns
        order = [hand, part] if n % 3 else [part, hand]
        assert merge_duplicates(order) == [hand]
        picked.append(follower.select(order, "Right", True, n / 30) is hand)
    assert all(picked)
    # two readings of about one size: the one like the frame before stays, whatever the scores do
    follower = HandFollower()
    assert follower.select([hand_at("Left", x=.50, size=.30)], "Right", True, 0.0) is not None
    near, shifted = hand_at("Left", x=.505, size=.30, score=.97), hand_at("Left", x=.56, size=.33, score=.99)
    assert follower.select([shifted, near], "Right", True, .03) is near
    # a clearly better score still decides
    sure, unsure = hand_at("Left", size=.11, score=.99), hand_at("Left", size=.30, score=.6)
    assert merge_duplicates([unsure, sure]) == [sure]
