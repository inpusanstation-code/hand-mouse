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
