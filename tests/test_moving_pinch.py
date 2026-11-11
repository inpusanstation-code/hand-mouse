"""A thumb + index pinch that closes while the hand is travelling (2026-11-11).

"가상손이 이동을 하긴 하는데 중간에 뚝뚝 끊기는 경우가 잦다" -> "이어서 줄여 줘". Of 198 logged thumb + index pinches 31 closed
with the palm travelling at 0.15 frame widths a second or more; each held the cursor (the click's aim) for a quarter to
half a second, and 10 clicked."""
import time

from tests.test_virtual_hand import box_runtime, pinch_hand


def _step(rt, dx=0.0, wait=1 / 60):
    rt.tracker.dx += dx
    time.sleep(wait)
    rt._step()
    return rt.mouse.last_screen_pos[0]


def test_a_pinch_on_a_travelling_hand_neither_stops_the_cursor_nor_clicks(tmp_path):
    rt = box_runtime(tmp_path)
    for _ in range(4):
        rt._step()
    xs = [_step(rt, .012) for _ in range(14)]              # travelling: about 0.7 frame widths a second
    opened = pinch_hand(rt)                                # the fingers brush together on the way
    xs += [_step(rt, .012) for _ in range(5)]
    assert rt.shape_pinch.closed and rt._pinch_moving
    rt.tracker.hand[:] = opened
    xs += [_step(rt, .012) for _ in range(8)]
    steps = [b - a for a, b in zip(xs[4:], xs[5:])]
    assert min(steps) > 0, steps                           # the cursor went on all the way (it stood still while closed)
    assert "left_click" not in rt.mouse.event_log and not rt.mouse.is_dragging
    assert not rt._pinch_moving                            # forgotten once the fingers part


def test_a_pinch_on_a_resting_hand_still_holds_the_cursor_and_clicks(tmp_path):
    rt = box_runtime(tmp_path)
    for _ in range(4):
        rt._step()
    for _ in range(14):                                    # the hand has stopped (a little tremor)
        _step(rt, .0005)
    opened = pinch_hand(rt)
    held = [_step(rt, .0005) for _ in range(4)]
    assert rt.shape_pinch.closed and not rt._pinch_moving and len(set(held[1:])) == 1     # the aim is held
    rt.tracker.hand[:] = opened
    _step(rt)
    assert rt.mouse.event_log.count("left_click") == 1


def test_a_travelling_pinch_that_is_held_on_still_becomes_a_drag_and_the_limit_can_be_switched_off(tmp_path):
    from src.virtual_hand import PINCH_HOLD
    rt = box_runtime(tmp_path)
    for _ in range(4):
        rt._step()
    for _ in range(14):
        _step(rt, .012)
    pinch_hand(rt)
    end = time.perf_counter() + PINCH_HOLD + .25
    while time.perf_counter() < end:
        _step(rt, .004)
    assert rt.mouse.is_dragging                            # closed and kept closed: a drag, as before
    rt2 = box_runtime(tmp_path / "b")
    rt2.engine.config["virtual_pinch_moving_speed"] = 0     # 0 = every pinch holds and clicks, as it was
    for _ in range(4):
        rt2._step()
    for _ in range(14):
        _step(rt2, .012)
    opened = pinch_hand(rt2)
    for _ in range(3):
        _step(rt2, .012)
    assert not rt2._pinch_moving
    rt2.tracker.hand[:] = opened
    _step(rt2)
    assert rt2.mouse.event_log.count("left_click") == 1


def _triple(rt):
    """Thumb, index and middle tips together (the right-click shape)."""
    from src.virtual_hand import TIPS
    hand = rt.tracker.hand
    opened = list(hand)
    tip = hand[TIPS["index"]]
    hand[4] = type(tip)(tip.x, tip.y, tip.z)
    hand[TIPS["middle"]] = type(tip)(tip.x, tip.y, tip.z)
    return opened


def test_three_fingers_meeting_on_a_travelling_hand_do_not_right_click_or_stop_the_cursor(tmp_path):
    """2026-11-11 report: "그냥 움직이기만 해도 우클릭 간섭이 심하다". On this PC's click log 8 of the 16 right clicks were
    made with the palm travelling at 0.1 frame widths a second or more; the left clicks' median was 0.02."""
    rt = box_runtime(tmp_path)
    for _ in range(4):
        rt._step()
    xs = [_step(rt, .012) for _ in range(14)]              # travelling
    opened = _triple(rt)                                   # the three tips line up for the camera on the way
    xs += [_step(rt, .012) for _ in range(5)]
    assert rt.shape_right.closed and rt._triple_moving
    rt.tracker.hand[:] = opened
    xs += [_step(rt, .012) for _ in range(6)]
    steps = [b - a for a, b in zip(xs[4:], xs[5:])]
    assert min(steps) > 0, steps                           # the cursor went on all the way
    assert "right_click" not in rt.mouse.event_log and "left_click" not in rt.mouse.event_log
    # a hand that has stopped right-clicks as before
    for _ in range(16):
        _step(rt)
    opened = _triple(rt)
    for _ in range(3):
        _step(rt)
    assert "right_click" not in rt.mouse.event_log         # together, but not yet for 0.6 s ("virtual_right_hold")
    _step(rt, wait=.3)
    assert "right_click" not in rt.mouse.event_log         # 0.3 s: the hold most stray ones lasted
    _step(rt, wait=.35)
    _step(rt)
    assert rt.mouse.event_log.count("right_click") == 1    # held: one right click, however long it stays
    rt.tracker.hand[:] = opened
    for _ in range(3):
        _step(rt)
    _triple(rt)                                            # the fingers only pass each other: no right click
    _step(rt); _step(rt)
    rt.tracker.hand[:] = opened
    for _ in range(3):
        _step(rt)
    assert rt.mouse.event_log.count("right_click") == 1
    # ... and the limit can be switched off
    rt2 = box_runtime(tmp_path / "off")
    rt2.engine.config["virtual_right_moving_speed"] = 0
    rt2.engine.config["virtual_right_hold"] = .15
    for _ in range(4):
        rt2._step()
    for _ in range(14):
        _step(rt2, .012)
    _triple(rt2)
    for _ in range(7):
        _step(rt2, .012, wait=.06)
    assert "right_click" in rt2.mouse.event_log


def test_f8_marks_the_click_just_made_and_says_so_when_there_is_none(tmp_path):
    """2026-11-11: F reaches the app only in its own window; F8 marks from anywhere (main.py posts "mark_recent")."""
    import json
    rt = box_runtime(tmp_path)
    rt.engine.config["virtual_click_log"] = True
    rt.engine.config["virtual_right_hold"] = .15
    said = []
    rt._say = lambda text, *a, **k: said.append(text)
    for _ in range(20):
        _step(rt)
    rt.post("mark_recent")
    _step(rt)
    assert said and "없어요" in said[-1]                    # nothing to mark: said, and nothing else happens
    _triple(rt)
    for _ in range(5):
        _step(rt, wait=.08)
    assert rt.mouse.event_log.count("right_click") == 1
    rt.post("mark_recent")
    _step(rt)
    assert "우클릭" in said[-1] and "클릭 아님" in said[-1]
    rt.post("mark_recent")
    _step(rt)
    assert "없어요" in said[-1]                             # a click is marked once
    if rt.click_log is not None and rt.click_log._path is not None:
        lines = [json.loads(x) for x in rt.click_log._path.read_text(encoding="utf-8").splitlines()]
        assert sum(1 for x in lines if x.get("type") == "mark") == 1
