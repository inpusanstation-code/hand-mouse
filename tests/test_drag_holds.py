"""A thumb + index drag is not taken over by other signals (2026-11-11).

"엄지검지 드래그 판정이 많이 풀어지기는 했는데, 중간에 스크롤이나 다른 신호들의 간섭이 많아서 중간에 끊어지는 경우가 많다.
드래그 판정일 때는 엄지검지가 떨어지기 전에는 웬만하면 간섭들은 무시하고 드래그 상태가 유지되도록" - a dragging hand has
its other fingers curled and moves: it read as a fist (the page scroll ended the drag), as the thumb + index + middle
right click (the cursor stood still), as a taught pose or a composite gesture."""
import time

from tests.test_fist_scroll_release import forcing
from tests.test_virtual_hand import box_runtime, pinch_hand


def _drag(tmp_path):
    from src.virtual_hand import PINCH_HOLD
    rt = box_runtime(tmp_path)
    rt._step()
    opened = pinch_hand(rt)
    rt._step(); rt._step()
    time.sleep(PINCH_HOLD + .05)
    rt._step()
    assert rt.mouse.is_dragging
    return rt, opened


def _move(rt, frames=6, dx=.03):
    xs = []
    for _ in range(frames):
        rt.tracker.dx += dx
        time.sleep(1 / 60)
        rt._step()
        xs.append(rt.mouse.last_screen_pos[0])
    return xs


def test_a_dragging_hand_read_as_a_fist_keeps_dragging_and_does_not_scroll(tmp_path):
    rt, opened = _drag(tmp_path)
    sent = []
    rt.mouse._send_scroll = lambda v, h: sent.append(v)
    start = rt.mouse.last_screen_pos[0]
    restore = forcing(rt, active_gesture="fist")           # the curled fingers of the dragging hand read as a fist
    xs = _move(rt, frames=rt.grip.SOLID + 4)
    assert rt.mouse.is_dragging and rt.grip.step(None, time.perf_counter()) is None
    assert sum(sent) == 0 and "mouseUp" not in rt.mouse.event_log
    assert xs[-1] > start and all(b > a for a, b in zip(xs, xs[1:]))        # the held thing went on with the hand
    rt.engine.process = restore
    rt.tracker.hand[:] = opened                            # only the fingers parting ends it
    rt._step(); rt._step()
    assert not rt.mouse.is_dragging and "mouseUp" in rt.mouse.event_log


def test_the_middle_finger_joining_a_drag_is_not_a_right_click_and_does_not_stop_the_cursor(tmp_path):
    from src.virtual_hand import TIPS
    rt, opened = _drag(tmp_path)
    tip = rt.tracker.hand[TIPS["index"]]
    rt.tracker.hand[12] = type(tip)(tip.x, tip.y, tip.z)   # the middle fingertip drifts onto the thumb and index
    start = rt.mouse.last_screen_pos[0]
    xs = _move(rt)
    assert rt.mouse.is_dragging and "right_click" not in rt.mouse.event_log and not rt.shape_right.closed
    assert xs[-1] > start and all(b > a for a, b in zip(xs, xs[1:]))
    rt.tracker.hand[:] = opened
    rt._step(); rt._step()
    assert not rt.mouse.is_dragging and "right_click" not in rt.mouse.event_log


def test_a_taught_pose_or_a_pointing_hand_seen_during_a_drag_does_not_take_it_over(tmp_path):
    rt, opened = _drag(tmp_path)
    rt._online_recognize = lambda *a, **k: True            # a registered pose is "recognised" on every frame
    rt.point.step = lambda *a, **k: (_ for _ in ()).throw(AssertionError("pointing mode was asked during a drag"))
    start = rt.mouse.last_screen_pos[0]
    xs = _move(rt)
    assert rt.mouse.is_dragging and xs[-1] > start and "mouseUp" not in rt.mouse.event_log


# ---------------------------------------------------------------- 2026-11-12: "끌기 바꾸기 만들기"
def _held_pinch(tmp_path, binding):
    """A thumb + index pinch kept closed past the drag time, with the held move ("vh_drag") connected as given."""
    from src.action_bindings import get_action_registry
    from src.virtual_hand import PINCH_HOLD
    if binding is not None:
        get_action_registry().set_binding("vh_drag", *binding[:2], enabled=binding[2])
    rt = box_runtime(tmp_path)
    rt._step()
    opened = pinch_hand(rt)
    rt._step(); rt._step()
    time.sleep(PINCH_HOLD + .05)
    rt._step(); rt._step()
    return rt, opened


def test_the_held_pinch_drags_by_default_and_can_be_switched_off_or_given_another_command(tmp_path):
    rt, opened = _held_pinch(tmp_path / "a", None)
    assert rt.mouse.is_dragging                                             # untouched: it drags as always
    rt, opened = _held_pinch(tmp_path / "b", ("mouse_action", "drag_hold", False))
    assert not rt.mouse.is_dragging and "mouseDown" not in rt.mouse.event_log
    rt.tracker.hand[:] = opened
    rt._step(); rt._step()
    assert "left_click" not in rt.mouse.event_log                           # switched off: the held press is nothing
    rt, opened = _held_pinch(tmp_path / "c", ("mouse_action", "right_click", True))
    assert not rt.mouse.is_dragging and rt.mouse.event_log.count("right_click") == 1   # the other command, once
    for _ in range(5):
        time.sleep(1 / 60)
        rt._step()
    rt.tracker.hand[:] = opened
    rt._step(); rt._step()
    assert rt.mouse.event_log.count("right_click") == 1 and "left_click" not in rt.mouse.event_log
    # a quick pinch is still a click whatever the held move is connected to
    rt.tracker.hand[:] = opened
    for _ in range(3):
        rt._step()
    pinch_hand(rt)
    rt._step(); rt._step()
    rt.tracker.hand[:] = opened
    rt._step()
    assert rt.mouse.event_log.count("left_click") == 1


def test_a_pointing_dwell_connected_to_the_drag_takes_hold_and_letting_the_hand_go_drops(tmp_path):
    import dataclasses
    from src import default_moves
    from src.action_bindings import get_action_registry
    from tests.test_point_mode import gun
    assert default_moves.check("point_double", "mouse_action", "drag_hold") == ""
    assert default_moves.check("point_double", "mouse_action", "scroll_grab") != ""
    get_action_registry().set_binding("point_double", "mouse_action", "drag_hold")

    class Probe:                                             # a file under wherever the cursor is
        name, area_px, seen, error, asked, answered = "a.txt", 40, "", "", 0, 0
        box = None
        def ask(self, x, y): pass
        def state(self, x, y): return "file" if self.target(x, y) else "none"
        def answer(self, x, y): return self.target(x, y) is not None
        def target(self, x, y):
            if self.box is None:
                return None
            l, t, r, b = self.box
            return ("a.txt", self.box) if l - 40 <= x <= r + 40 and t - 40 <= y <= b + 40 else None

    rt = box_runtime(tmp_path)
    rt.ui = dataclasses.replace(rt.ui, stage="main", point_mode=True)
    probe = rt.point_probe = Probe()
    rt._step()
    hand = gun(middle="folded")
    rt.tracker.hand[:] = [type(rt.tracker.hand[0])(p.x, p.y, 0.0) for p in hand]
    for _ in range(14):
        time.sleep(1 / 60)
        rt._step()
    assert rt.point.active
    x, y = rt.mouse.last_screen_pos
    probe.box = (x - 30, y - 30, x + 30, y + 30)
    end = time.perf_counter() + 1.3                          # rests on the file for the dwell time
    while time.perf_counter() < end:
        time.sleep(1 / 60)
        rt._step()
    assert rt.mouse.is_dragging and rt._point_drag and "double_click" not in rt.mouse.event_log
    start = rt.mouse.last_screen_pos[0]
    for _ in range(8):                                       # the fingertip travels: what it holds comes along
        for p in rt.tracker.hand:
            p.x -= .01
        time.sleep(1 / 60)
        rt._step()
    assert rt.mouse.is_dragging and rt.mouse.last_screen_pos[0] != start
    assert "mouseUp" not in rt.mouse.event_log and rt.mouse.event_log.count("mouseDown") == 1
    rt.ui = dataclasses.replace(rt.ui, point_mode=False)     # the pointing hand is let go (here: the mode ends)
    rt._step(); rt._step()
    assert not rt.mouse.is_dragging and not rt._point_drag and "mouseUp" in rt.mouse.event_log
