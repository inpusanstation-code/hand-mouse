"""Motion mode with the other hand (2026-11-12, "모션모드는 왼손으로 하게 만들수 있나?"): src/other_hand_motion.py."""
import time

from src.gesture_engine import Point3D
from src.hand_tracker import HandDetection
from src.other_hand_motion import OtherHandMotion, other_hand
from tests.test_gesture_mouse import make_real_hand
from tests.test_qt_runtime import FakeTracker, runtime

OPEN = make_real_hand(curled=False)        # x .36-.56, y .4-.8


def det(dx, label, hand=OPEN, score=.95):
    return HandDetection(landmarks=[Point3D(p.x + dx, p.y, p.z) for p in hand], handedness=label, score=score)


def test_the_other_hand_is_the_opposite_side_and_apart_from_the_control_hand():
    control = det(.25, "Left")                                  # mirrored: "Left" = the physical right hand
    left = det(-.15, "Right")
    assert other_hand([control, left], control, "Right", True) is left
    # the control hand read twice, the second reading flipped: on top of it, so not another hand
    assert other_hand([control, det(.26, "Right")], control, "Right", True) is None
    # no control side set, or two candidates: none
    assert other_hand([control, left], control, "", True) is None
    assert other_hand([control, left, det(-.36, "Right")], control, "Right", True) is None
    # without a control hand in view the other hand still counts
    assert other_hand([left], None, "Right", True) is left


def test_a_second_hand_apart_is_the_other_hand_whatever_it_reads():
    """2026-11-12 logs: the left hand was dropped in 350 frames for a left/right reading under .75 and in 348 for reading as
    the same side as the control hand."""
    control = det(.25, "Left")
    assert other_hand([control, det(-.15, "Right", score=.6)], control, "Right", True) is not None   # unsure reading
    flipped = det(-.15, "Left")                                                                       # reads as the control side
    assert other_hand([control, flipped], control, "Right", True) is flipped
    # without the control hand: an unsure opposite reading counts, a flipped one only where the other hand just was
    assert other_hand([det(-.15, "Right", score=.6)], None, "Right", True) is not None
    from src.hand_selection import _center_and_size
    last = _center_and_size(det(-.14, "Right"))
    assert other_hand([flipped], None, "Right", True) is None
    assert other_hand([flipped], None, "Right", True, last=last) is flipped


def test_the_control_follower_does_not_take_the_other_hand():
    """2026-11-12: with the right hand out of view, the left hand was followed as the control hand (494 frames)."""
    from src.hand_selection import HandFollower, _center_and_size
    fol = HandFollower()
    right = det(.3, "Left")                               # the control hand
    left = det(-.3, "Right")
    assert fol.select([right, left], "Right", True, 0.0) is right
    avoid = _center_and_size(left)
    # the right hand gone: the left hand reading as the control side is not taken
    assert fol.select([det(-.3, "Left")], "Right", True, 0.1, avoid=avoid) is None
    assert fol.select([det(-.3, "Left")], "Right", True, 0.2) is not None           # (without `avoid` it was)
    assert fol.select([det(.32, "Left")], "Right", True, 0.3, avoid=avoid) is not None  # the right hand itself still is


def test_shown_open_it_arms_its_swipes_count_and_lowering_it_ends():
    om, t = OtherHandMotion(), 0.0
    events = []

    def feed(lm, n, dx_step=0.0):
        nonlocal t
        x = 0.0
        for _ in range(n):
            x += dx_step
            ev = om.step(t, None if lm is None else [Point3D(p.x + x, p.y, p.z) for p in lm])
            if ev is not None:
                events.append(ev)
            t += 1 / 30
        return x

    feed(OPEN, 6)                                               # .2 s: not yet
    assert not om.active and 0 < om.arming(t) < 1
    feed(OPEN, 6)
    assert om.active and events[-1].kind == "enter" and events[-1].info["how"] == "other_hand"
    feed(OPEN, 12, dx_step=-.03)                                # a fast stroke to the left
    swipes = [e for e in events if e.kind == "swipe"]
    assert len(swipes) == 1 and swipes[0].action == "tab_prev"          # the open hand to the left = the previous tab
    feed(None, 9)                                               # .3 s out of view: still on
    assert om.active
    feed(None, 9)
    assert not om.active and events[-1].kind == "exit" and events[-1].info["why"] == "lowered"


def test_a_hand_passing_through_does_not_arm():
    om, t = OtherHandMotion(), 0.0
    for i in range(30):                                         # open but moving across the view the whole time
        assert om.step(t, [Point3D(p.x + .02 * i, p.y, p.z) for p in OPEN]) is None
        t += 1 / 30
    assert not om.active
    fist = make_real_hand(curled=True)
    for _ in range(30):                                         # still, but not open
        assert om.step(t, fist) is None
        t += 1 / 30
    assert not om.active


def test_no_downward_stroke_when_the_hand_is_lowered():
    om, t = OtherHandMotion(), 0.0
    for _ in range(12):
        om.step(t, OPEN)
        t += 1 / 30
    assert om.active
    for i in range(10):                                         # dropped fast, still open
        ev = om.step(t, [Point3D(p.x, p.y + .04 * i, p.z) for p in OPEN])
        assert ev is None or ev.kind != "swipe" or ev.action != "window_down"
        t += 1 / 30


class TwoHands(FakeTracker):
    def __init__(self):
        super().__init__()
        self.dx = .25                                          # the control hand to the right
        self.left_dx = -.15
        self.left_present = True

    def detect(self, frame, roi=None):
        out = super().detect(frame, roi)
        if self.left_present:
            out.append(det(self.left_dx, "Right"))
        return out


def test_the_runtime_sends_the_other_hands_swipe_while_the_control_hand_keeps_the_cursor(tmp_path):
    rt = runtime(tmp_path)
    rt.tracker = TwoHands()
    rt.paused = False
    sent = []
    rt.mouse.send_motion_action = lambda action: sent.append(action) or True

    def run(seconds, left_step=0.0, right_step=0.0):
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            rt.tracker.left_dx += left_step
            rt.tracker.dx += right_step
            rt._step()
            time.sleep(1 / 60)

    run(.5)                                                     # the left hand shown open: armed
    assert rt.other_motion.active and not rt.motion.active
    assert rt._snap.motion[5][0] and rt._snap.motion[5][2] == "왼손"
    # the preview draws it too, in its own colour (2026-11-12): its joints and its state
    other = rt._snap.preview_hand["other"]
    assert other["state"] == "on" and len(other["lm"]) == 21
    start = rt.mouse.last_screen_pos
    run(.15, left_step=-.03, right_step=.004)                   # the left hand swipes left, the right hand moves on
    assert sent == ["tab_prev"]
    assert rt.mouse.last_screen_pos != start                    # the cursor was not held for the swipe
    rt.tracker.left_present = False
    run(.75)
    assert not rt.other_motion.active
    # switched off in the settings window: nothing arms
    import dataclasses
    rt.ui = dataclasses.replace(rt.ui, other_motion=False)
    rt.tracker.left_present = True
    run(.5)
    assert not rt.other_motion.active


def test_the_settings_button_switches_it_and_keeps_the_choice(tmp_path):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication
    from src.qt_dashboard import QtDashboard
    from tests.test_use_review import _ALIVE
    app = QApplication.instance() or QApplication([])
    QQuickStyle.setStyle("Basic")
    ui = QtDashboard(dry_run=True)
    _ALIVE.append(ui)
    ui.setOtherMotion(False)
    assert not ui.otherMotionOn and ui.ui_state().other_motion is False
    ui.setOtherMotion(True)
    assert ui.otherMotionOn and ui.ui_state().other_motion is True
    app.processEvents()


def test_paused_it_only_tells_what_it_would_send(tmp_path):
    rt = runtime(tmp_path)
    rt.tracker = TwoHands()
    rt.paused = True
    sent = []
    rt.mouse.send_motion_action = lambda action: sent.append(action) or True
    end = time.perf_counter() + .5
    while time.perf_counter() < end:
        rt._step()
        time.sleep(1 / 60)
    end = time.perf_counter() + .15
    while time.perf_counter() < end:
        rt.tracker.left_dx -= .03
        rt._step()
        time.sleep(1 / 60)
    assert sent == [] and rt._motion_last.startswith("왼손: 시뮬레이션")


def test_the_other_hand_counts_smaller_slower_strokes_and_no_downward_ones():
    """2026-11-12: "왼손 움직임을 너무 크게 하지 않아도 작동하게"; the user's own "fist down = F5" fired as the left hand dropped."""
    from src.motion_mode import MotionMode

    def stroke(mm, t, n=8, dist=.12):               # .12 of the frame in .23 s: .5 widths/s ... under the control hand's limits
        events = []
        for i in range(12 + n):
            x = .6 - dist * max(0, i - 12) / (n - 1)
            ev = mm(t, [Point3D(p.x + x - .46, p.y, p.z) for p in OPEN])
            if ev is not None:
                events.append(ev)
            t += 1 / 30
        return [e for e in events if e.kind == "swipe"]

    om = OtherHandMotion()
    assert om.cfg("motion_custom_down") == 0 and om.cfg("motion_close_enabled") == 0
    assert stroke(lambda t, lm: om.step(t, lm), 0.0) and om.active
    main = MotionMode()
    main.update(0.0, None, request="on")
    assert not stroke(lambda t, lm: main.update(t, lm), 0.1)


def test_the_other_hand_is_drawn_on_the_screen_too(tmp_path):
    """2026-11-12: "왼쪽 스켈레톤도 모니터에 같이 뜨게"."""
    import dataclasses
    rt = runtime(tmp_path)
    rt.tracker = TwoHands()
    rt.paused = False
    rt.ui = dataclasses.replace(rt.ui, virtual_hand=True, use_index_pointer=False, virtual_box=(0.0, 0.0, 1.0, 1.0))
    end = time.perf_counter() + .5
    while time.perf_counter() < end:
        rt._step()
        time.sleep(1 / 60)
    view = rt._snap.other_hand
    assert view and len(view["pts"]) == 42 and view["state"] == "on" and not view["lost"]
    assert 0 <= view["pos"][0] < .45                              # where it is on the camera image: the left side
    rt.tracker.left_present = False
    rt._step()
    assert rt._snap.other_hand["lost"]                            # a dropout: drawn on, faded
    end = time.perf_counter() + .7
    while time.perf_counter() < end:
        rt._step()
        time.sleep(1 / 60)
    assert rt._snap.other_hand is None
    rt.ui = dataclasses.replace(rt.ui, virtual_hand=False)        # without the virtual hand: not drawn
    rt.tracker.left_present = True
    rt._step()
    assert rt._snap.other_hand is None


def test_the_screen_window_shows_it(tmp_path):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QObject
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication
    from src.qt_dashboard import QtDashboard
    from tests.test_use_review import _ALIVE
    app = QApplication.instance() or QApplication([])
    QQuickStyle.setStyle("Basic")
    ui = QtDashboard(dry_run=True)
    _ALIVE.append(ui)
    ui.virtual_hand_on = True
    ui.set_other_hand({"pts": [0.0] * 42, "pos": [.2, .5], "state": "on", "lost": False})
    app.processEvents()
    win = ui.window.findChild(QObject, "otherHandWindow") or ui.engine.rootObjects()[0].findChild(QObject, "otherHandWindow")
    assert win is not None and ui.otherHand["x"] > 0
    ui.set_other_hand(None)
    app.processEvents()
    assert ui.otherHand == {}


def test_a_registered_youtube_motion_is_read_and_sends_only_in_youtube(tmp_path, monkeypatch):
    from src import action_bindings
    from src.action_bindings import ActionBindingRegistry
    from src.motion_mode import MotionMode
    from tests.test_motion_mode import hand, run, entered
    reg = ActionBindingRegistry(path=tmp_path / "b.json")
    reg.register_motion_gesture("motion_yt_slower", "유튜브 배속 느리게", "fist", "left", "none", "none", min_distance=0.12,
                                app_overrides=[{"app_match": "YouTube", "action_type": "youtube_key", "action_value": "yt_speed_down"}])
    monkeypatch.setattr(action_bindings, "get_action_registry", lambda: reg)
    mm, t = entered()
    fist = dict(fingers="folded", thumb="tucked")
    ev, t = run(mm, [hand(cx=0.7, **fist)] * 10 + [hand(cx=0.7 - 0.3 * i / 9, **fist) for i in range(10)], t0=t)
    assert [e.action for e in ev if e.kind == "swipe"] == ["motion_yt_slower"]
    yt = reg.resolve_effective_action("motion_yt_slower", {"process": "chrome.exe", "title_full": "영상 - YouTube - Chrome"})
    other = reg.resolve_effective_action("motion_yt_slower", {"process": "notepad.exe", "title_full": "메모"})
    assert (yt["action_type"], yt["action_value"]) == ("youtube_key", "yt_speed_down")
    assert other["action_type"] == "none"


def test_a_v_swiped_left_or_right_turns_the_shorts_in_youtube(tmp_path, monkeypatch):
    """2026-11-12 (user's choice "2번"): V left = the previous short (↑), V right = the next one (↓); arms the other hand too."""
    from src import action_bindings
    from src.action_bindings import ActionBindingRegistry
    from tests.test_motion_mode import hand, run, entered
    reg = ActionBindingRegistry(path=tmp_path / "b.json")
    for key, direction, yt in (("motion_yt_prev_short", "left", "yt_vol_up"), ("motion_yt_next_short", "right", "yt_vol_down")):
        reg.register_motion_gesture(key, key, "v_sign", direction, "none", "none", min_distance=0.12,
                                    app_overrides=[{"app_match": "YouTube", "action_type": "youtube_key", "action_value": yt}])
    monkeypatch.setattr(action_bindings, "get_action_registry", lambda: reg)
    v = dict(bent=(13, 17))
    mm, t = entered()
    ev, t = run(mm, [hand(cx=0.7, **v)] * 10 + [hand(cx=0.7 - 0.3 * i / 9, **v) for i in range(10)], t0=t)
    assert [e.action for e in ev if e.kind == "swipe"] == ["motion_yt_prev_short"]
    ev, t = run(mm, [hand(cx=0.4, **v)] * 40 + [hand(cx=0.4 + 0.3 * i / 9, **v) for i in range(10)], t0=t)
    assert [e.action for e in ev if e.kind == "swipe"] == ["motion_yt_next_short"]
    yt = reg.resolve_effective_action("motion_yt_next_short", {"process": "chrome.exe", "title_full": "#shorts - YouTube"})
    assert yt["action_value"] == "yt_vol_down"
    om = OtherHandMotion()                                   # a V held up arms the other hand
    for i in range(12):
        om.step(i / 30, hand(cx=0.3, **v))
    assert om.active


def test_shorts_turn_by_the_wheel_at_the_window_middle_not_by_arrow_keys(monkeypatch):
    """2026-11-12: "처음에 한번만 되고 그다음은 왼쪽 사이드바가 신호를 뺐어간다" - ↑/↓ went to the focused left menu."""
    from types import SimpleNamespace
    from src import action_bindings
    from src.action_bindings import ActionBindingRegistry, YOUTUBE_KEY_PRESETS
    turns, keys = [], []
    monkeypatch.setattr(action_bindings, "wheel_at_window_middle", lambda n: turns.append(n) or True)
    monkeypatch.setattr(action_bindings.pyautogui, "press", lambda *a, **k: keys.append(a))
    monkeypatch.setattr(action_bindings.pyautogui, "hotkey", lambda *a, **k: keys.append(a))
    log = SimpleNamespace(event_log=[])
    reg = ActionBindingRegistry.__new__(ActionBindingRegistry)
    for value, notch in (("yt_short_next", -1), ("yt_short_prev", 1)):
        ok, badge = reg.execute_resolved_action({"action_type": "youtube_key", "action_value": value}, dry_run=False,
                                                mouse_controller=log)
        assert ok and turns[-1] == notch and "쇼츠" in badge
    assert keys == [] and log.event_log == ["youtube:yt_short_next", "youtube:yt_short_prev"]
    assert YOUTUBE_KEY_PRESETS["yt_short_next"]["badge"] == "YT 다음 쇼츠"




def test_the_other_hand_has_a_box_of_its_own(tmp_path):
    """2026-11-12: through the control hand's box the left hand was stuck in the monitor's left corner ("벗어나기가
    힘들다") -> its own box, the whole camera image until one is drawn."""
    import dataclasses
    from src.virtual_hand import palm_centre
    rt = runtime(tmp_path)
    rt.ui = dataclasses.replace(rt.ui, stage="main", virtual_hand=True, other_motion=True, use_index_pointer=False,
                                virtual_box=(.5, .15, .9, .85))
    hand = det(-.2, "Right")                                         # left of the control hand's box
    rt._other_hand = hand
    cx, cy = palm_centre(hand.landmarks)
    rt._other_draw(0.0, rt.ui, 1280, 720)
    assert abs(rt._other_view["pos"][0] - cx) < 1e-3 and rt._other_view["pos"][0] > 0   # not stuck at the edge
    box = (0.0, .1, .5, .9)
    rt.ui = dataclasses.replace(rt.ui, other_box=box)
    rt._other_draw(.03, rt.ui, 1280, 720)
    assert abs(rt._other_view["pos"][0] - (cx - box[0]) / (box[2] - box[0])) < 1e-3
    assert abs(rt._other_view["pos"][1] - (cy - box[1]) / (box[3] - box[1])) < 1e-3


def test_the_other_box_is_drawn_on_the_preview(tmp_path):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QObject
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication
    from src.qt_dashboard import OTHER_BOX_DEFAULT, QtDashboard
    from tests.test_use_review import _ALIVE
    app = QApplication.instance() or QApplication([])
    QQuickStyle.setStyle("Basic")
    ui = QtDashboard(dry_run=True)
    _ALIVE.append(ui)
    ui.resetOtherBox()
    main = tuple(ui.virtual_box)
    assert tuple(ui.other_box) == OTHER_BOX_DEFAULT and not ui.otherBoxDrawn
    ui.setOtherBoxEditing(True)
    assert ui.boxEditing and ui.boxEditingOther
    assert ui.setVirtualBox(.4, .8, .05, .2)                         # the drag draws the other hand's box
    assert tuple(ui.other_box) == (.05, .2, .4, .8) and tuple(ui.virtual_box) == main and ui.otherBoxDrawn
    assert not ui.boxEditing
    assert ui.ui_state().other_box == (.05, .2, .4, .8)
    ui.setBoxEditing(True)
    assert ui.setVirtualBox(.3, .2, .9, .8) and tuple(ui.other_box) == (.05, .2, .4, .8)   # the control box as before
    ui.resetOtherBox()
    assert not ui.otherBoxDrawn
    app.processEvents()
    root = ui.engine.rootObjects()[0]
    assert root.findChild(QObject, "otherBoxButton") is not None and root.findChild(QObject, "otherBoxFrame") is not None
