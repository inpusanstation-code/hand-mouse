"""Letting go of a fist scroll (2026-11-11).

"주먹 스크롤브라우징에서 스크롤하다가 손을 펴면 다른 위치로 jump하고 의도하지 않은 추가 스크롤이 일어나 정밀 컨트롤을
할 수가 없다". The 19 logged releases (logs/failures/*inertia.json): the page kept scrolling for 12-14 frames after the
fist had opened (the grip's grace), and the cursor went 133-996 px in one frame when the grip ended."""
import math
import time
from types import SimpleNamespace

from src.virtual_hand import PALM, BoxMapper
from tests.test_virtual_hand import box_runtime, forcing

BOX = (0.0, 0.0, 1.0, 1.0)


def _hand(x, y=.5):
    return [SimpleNamespace(x=x, y=y, z=0.0) for _ in range(21)]


def test_the_cursor_does_not_jump_to_the_hand_when_a_hold_ends_far_from_it():
    m, t = BoxMapper(), 0.0
    for _ in range(10):
        start = m.target(_hand(.30), BOX, now=t)
        t += 1 / 30
    for i in range(30):                                    # held (a fist scrolls) while the hand travels to the right
        held = m.target(_hand(.30 + .01 * i), BOX, hold=True, keep=True, now=t)
        t += 1 / 30
    assert held == start
    for _ in range(15):                                    # let go, the hand standing still: the cursor stays
        after = m.target(_hand(.59), BOX, now=t)
        t += 1 / 30
        assert math.dist(after, start) < .005, after       # (it went to the hand, .29 of the monitor away)
    prev, hand_x = after, .59
    for _ in range(60):                                    # the hand moves on: the cursor moves with it and closes the gap
        hand_x += .004
        now = m.target(_hand(hand_x), BOX, now=t)
        t += 1 / 30
        assert now[0] - prev[0] < .02                      # never more than a few hand-steps at once
        prev = now
    for _ in range(140):
        hand_x -= .004
        now = m.target(_hand(hand_x), BOX, now=t)
        t += 1 / 30
    assert abs(now[0] - hand_x) < .01                      # caught up: the hand's place is the cursor's place again
    # a hold that ends near the hand (a click aimed and made) goes on as before
    m, t = BoxMapper(), 0.0
    for _ in range(10):
        m.target(_hand(.30), BOX, now=t); t += 1 / 30
    m.target(_hand(.31), BOX, hold=True, now=t); t += 1 / 30
    for _ in range(20):
        near = m.target(_hand(.31), BOX, now=t); t += 1 / 30
    assert abs(near[0] - .31) < .003 and m._offset == (0.0, 0.0)


def test_the_page_stops_when_the_fist_opens_though_the_grip_holds_on_a_moment(tmp_path):
    rt = box_runtime(tmp_path)
    rt._step()
    restore = forcing(rt, active_gesture="fist")
    sent = []
    rt.mouse._send_scroll = lambda v, h: sent.append(v)
    for _ in range(rt.grip.SOLID + 2):                     # the fist is held: a meant grip
        rt._step()
    assert rt.grip.solid
    for _ in range(8):
        rt.tracker.dx += .03
        time.sleep(1 / 60)
        rt._step()
    scrolled = sum(sent)
    assert scrolled != 0
    rt.engine.process = restore                            # the hand opens (no fist any more) and keeps moving
    still = tuple(rt.mouse.last_screen_pos)
    for _ in range(6):                                     # inside the grip's grace (0.4 s)
        rt.tracker.dx += .03
        time.sleep(1 / 60)
        rt._step()
        assert rt.grip.mode == "scroll"
    # the hand moved on by 6 more steps: none of that is scrolled. What still comes is the wheel's own smoothing running
    # out (the last fist frame's movement, halving each frame) - under one step's worth, where it was six steps more
    step = max(abs(v) for v in sent)                       # what one frame of this movement scrolls
    tail = [abs(v) for v in sent[-6:]]
    assert abs(sum(sent) - scrolled) <= 1.2 * step and tail == sorted(tail, reverse=True), (sent, scrolled)
    end = time.perf_counter() + rt.grip.GRACE + .05         # the open hand stays in view while the grip runs out
    biggest, last = 0.0, tuple(rt.mouse.last_screen_pos)
    while time.perf_counter() < end:
        rt.tracker.dx += .002
        time.sleep(1 / 60)
        rt._step()
        biggest = max(biggest, math.dist(rt.mouse.last_screen_pos, last))
        last = tuple(rt.mouse.last_screen_pos)
    # no frame jumps (the logged releases went 133-996 px in one frame). 2026-11-12: the total below follows the hand's own
    # slow movement in this loop, and the faster cursor filter follows it more closely (42 px seen once against 40)
    assert biggest < 20, biggest
    assert rt.grip.mode is None and not rt.mouse.scroll_coasting      # and nothing to coast on
    assert abs(sum(sent) - scrolled) <= 1.2 * step
    scrolled = sum(sent)
    # the cursor was held over the page; the hand is now far to the right: no jump there
    moved = math.dist(rt.mouse.last_screen_pos, still)
    assert moved < 60, moved
    restore2 = forcing(rt, active_gesture="fist")          # a new fist scrolls again from here
    for _ in range(rt.grip.SOLID + 2):
        rt._step()
    for _ in range(6):
        rt.tracker.dx -= .03
        time.sleep(1 / 60)
        rt._step()
    assert sum(sent) != scrolled
    rt.engine.process = restore2


def test_a_few_stray_fist_frames_on_a_moving_hand_do_not_stop_the_cursor_or_shift_it(tmp_path):
    """2026-11-11: "가상손이 이동을 하긴 하는데 중간에 뚝뚝 끊기는 경우가 잦다. 중간에 스크롤 판정이 나서 가상손이 멈추면
    좌표가 좀 어그러지는 거 같으니". Of the 45 logged fist scrolls 12 never had 10 fist frames; each held the cursor about
    half a second while the hand moved on."""
    rt = box_runtime(tmp_path)
    for _ in range(3):
        rt._step()
    sent = []
    rt.mouse._send_scroll = lambda v, h: sent.append(v)
    xs = []
    restore = None
    for i in range(40):                                    # the hand moves steadily to the right
        if i == 12:
            restore = forcing(rt, active_gesture="fist")   # 3 frames read as a fist on the way
        if i == 15:
            rt.engine.process = restore
        rt.tracker.dx += .01
        time.sleep(1 / 120)
        rt._step()
        xs.append(rt.mouse.last_screen_pos[0])
    assert not sent and rt.grip.mode is None               # no scroll, no grip
    steps = [b - a for a, b in zip(xs[5:], xs[6:])]
    assert min(steps) > 0, steps                           # the cursor never stood still
    assert rt.box_mapper._offset == (0.0, 0.0)             # and it is where the hand is: the box and the monitor line up


def test_a_fist_just_over_the_engine_limit_still_grabs_in_the_virtual_hand(tmp_path):
    """2026-11-12 ("주먹 스크롤이 적용 안되는 경우가 잦다"): curls of 1.04-1.05 with the thumb along the side, a thumb half out
    read as the thumbs-up pose, the thumb on the index read as a pinch - the engine said no fist."""
    from tests.test_gesture_mouse import make_real_hand
    rt = box_runtime(tmp_path)
    rt.tracker.hand = make_real_hand(curled=True)              # (the open test hand has its thumb straight up: excluded)
    rt._step()
    forcing(rt, active_gesture="no_pinch")                      # the engine: no fist
    rt.engine.finger_curl_ratios = lambda pts: (0.97, 1.03, 1.04, 1.01)
    rt.shape_pinch.reset()
    for _ in range(rt.grip.START + 2):
        rt._step()
    assert rt.grip.mode == "scroll"
    # looser than that, or the index out: no
    rt2 = box_runtime(tmp_path)
    rt2.tracker.hand = make_real_hand(curled=True)
    rt2.engine.finger_curl_ratios = lambda pts: (0.97, 1.03, 1.04, 1.01)
    assert rt2._loose_fist(rt2.tracker.hand)
    rt2.engine.finger_curl_ratios = lambda pts: (1.08, 1.03, 1.04, 1.01)
    assert not rt2._loose_fist(rt2.tracker.hand)
    rt2.engine.finger_curl_ratios = lambda pts: (0.97, 1.1, 1.04, 1.01)
    assert not rt2._loose_fist(rt2.tracker.hand)
