"""Feature `virtual_hand` (ported from virtual-hand-20261110): hand shapes -> intents, on synthetic hands."""
from __future__ import annotations

import pytest

from manux.actions.bindings import resolve_bindings
from manux.core.contracts import Feature, FrameContext, FrameInfo, HandObservation, OutputTarget, Stage
from manux.features import virtual_hand as vh
from manux.features.virtual_hand import shapes

W, H = 640, 480


def hand(tips=None):
    """An open right hand, fingers up, thumb out to the side. tips: {landmark index: (x, y)} overrides."""
    pts = {0: (.50, .70), 1: (.47, .68), 2: (.44, .65), 3: (.42, .62), 4: (.40, .60)}
    for k, x in enumerate((.46, .49, .52, .55)):
        base = 5 + 4 * k
        pts.update({base: (x, .60), base + 1: (x, .55), base + 2: (x, .52), base + 3: (x, .49)})
    pts.update(tips or {})
    return tuple((pts[i][0], pts[i][1], 0.0) for i in range(21))


OPEN = hand()
PINCH = hand({4: (.462, .492)})                                          # thumb on the index tip
TRIPLE = hand({8: (.475, .49), 12: (.48, .49), 4: (.4775, .495)})        # thumb, index, middle together
FIST = hand({8: (.46, .63), 12: (.49, .63), 16: (.52, .63), 20: (.55, .63), 4: (.47, .64)})
SWITCH = hand({4: (.49, .61)})                                           # thumb folded onto the palm


def run(feature, frames, t0=1.0, fps=30, settings=None):
    out, t = [], t0
    for lm in frames:
        frame = FrameInfo(seq=int(t * 1000), t=t, width=W, height=H, mirrored=True)
        obs = HandObservation(frame=frame, landmarks=lm, handedness="Right", score=.99) if lm is not None else None
        ctx = FrameContext(frame, Stage.MAIN, OutputTarget.WINDOWS, vh.MODE, settings=dict(settings or {}))
        out.extend(feature.step(obs, ctx))
        t += 1 / fps
    return out, t


def taps(intents, gesture):
    return [i for i in intents if i.gesture == gesture and i.phase == "tap"]


def phases(intents, gesture):
    return [i.phase for i in intents if i.gesture == gesture]


def test_declarations_fit_the_contract():
    f = vh.VirtualHandFeature()
    assert isinstance(f, Feature) and f.modes == frozenset({"virtual_hand"})
    bindings, problems = resolve_bindings(vh.DEFAULT_BINDINGS, gesture_phases=vh.GESTURE_PHASES)
    assert not problems and set(bindings) == set(vh.GESTURES)
    assert all(k.startswith("virtual_hand.") for k in vh.SETTINGS)


def test_the_shapes_are_what_the_tests_say():
    assert shapes.is_fist(FIST) and not shapes.is_fist(OPEN)
    assert shapes.ShapeSwitch().shape(SWITCH, W, H) and not shapes.ShapeSwitch().shape(OPEN, W, H)
    p = shapes.ShapePinch()
    assert [p.step(PINCH, W, H) for _ in range(2)] == [None, "down"] and p.step(OPEN, W, H) == "up"


def test_the_palm_in_the_box_places_the_cursor_on_the_monitor():
    out, _ = run(vh.VirtualHandFeature(), [OPEN] * 3)
    places = [i for i in out if i.gesture == vh.PLACE]
    assert [i.phase for i in places] == ["hold"] * 3
    cx, cy = shapes.palm_centre(OPEN)
    assert places[0].point == pytest.approx(((cx - .2) / .6, (cy - .15) / .7))
    assert not [i for i in out if i.gesture != vh.PLACE]


def test_a_quick_thumb_index_close_is_one_left_click_and_the_point_holds_while_closed():
    f = vh.VirtualHandFeature()
    out, t = run(f, [OPEN] * 10 + [PINCH] * 4)
    held = [i.point for i in out if i.gesture == vh.PLACE][-2:]
    assert held[0] == held[1]                                    # aiming: the point does not follow the pinch tilt
    out2, _ = run(f, [OPEN] * 3, t0=t)
    assert len(taps(out + out2, vh.LEFT)) == 1 and not phases(out + out2, vh.DRAG)


def test_holding_the_close_is_a_drag_that_ends_when_the_fingers_open():
    f = vh.VirtualHandFeature()
    out, t = run(f, [OPEN] * 3 + [PINCH] * 25)                  # ~0.8 s closed
    out2, _ = run(f, [OPEN] * 3, t0=t)
    drag = phases(out + out2, vh.DRAG)
    assert drag[0] == "begin" and drag[-1] == "end" and drag.count("begin") == drag.count("end") == 1
    assert not taps(out + out2, vh.LEFT)


def test_a_second_close_soon_after_is_a_double_click_at_the_same_point():
    f = vh.VirtualHandFeature()
    out, _ = run(f, [OPEN] * 5 + [PINCH] * 3 + [OPEN] * 3 + [PINCH] * 2 + [OPEN] * 3)
    lefts = taps(out, vh.LEFT)
    assert len(lefts) == 2
    places = {i.t: i.point for i in out if i.gesture == vh.PLACE}
    assert places[lefts[0].t] == places[lefts[1].t]


def test_three_fingers_together_is_one_right_click_and_no_left_click():
    out, _ = run(vh.VirtualHandFeature(), [OPEN] * 3 + [TRIPLE] * 4 + [OPEN] * 12)
    assert len(taps(out, vh.RIGHT)) == 1 and not taps(out, vh.LEFT) and not phases(out, vh.DRAG)


def test_a_fist_scrolls_and_lets_go_after_the_grace():
    f = vh.VirtualHandFeature()
    out, t = run(f, [OPEN] * 2 + [FIST] * 6)
    scroll = phases(out, vh.SCROLL)
    assert scroll[0] == "begin" and set(scroll[1:]) == {"hold"}
    assert all(i.point is not None for i in out if i.gesture == vh.SCROLL)
    out2, _ = run(f, [OPEN] * 20, t0=t)                         # 0.4 s grace, then end once
    assert phases(out2, vh.SCROLL)[-1] == "end" and phases(out2, vh.SCROLL).count("end") == 1


def test_scroll_direction_setting_flips_the_page_way():
    def first_y(settings):
        out, _ = run(vh.VirtualHandFeature(), [FIST] * 2, settings=settings)
        return next(i.point[1] for i in out if i.gesture == vh.SCROLL)
    cx, _ = shapes.palm_centre(FIST)
    assert first_y({}) == pytest.approx(1 - cx) and first_y({"scroll_follows_page": True}) == pytest.approx(cx)


def test_the_switch_pose_held_still_opens_the_task_switcher_once():
    out, _ = run(vh.VirtualHandFeature(), [OPEN] * 2 + [SWITCH] * 30)
    assert len(taps(out, vh.SWITCH)) == 1


def test_losing_the_hand_ends_an_open_drag_or_scroll():
    f = vh.VirtualHandFeature()
    out, t = run(f, [PINCH] * 25)
    out2, _ = run(f, [None], t0=t)
    assert phases(out2, vh.DRAG) == ["end"]
    f = vh.VirtualHandFeature()
    out, t = run(f, [FIST] * 3)
    assert phases(run(f, [None], t0=t)[0], vh.SCROLL) == ["end"]


def test_a_bad_box_gives_nothing():
    out, _ = run(vh.VirtualHandFeature(), [OPEN] * 3, settings={"box_left": .7, "box_right": .75})
    assert out == []


def test_mouse_place_puts_the_cursor_on_the_monitor_point():
    from manux.core.contracts import ActionCommand
    from manux.output.windows import FakeBackend, WindowsOutputConfig, WindowsOutputSink
    from manux.platform.monitors import ScreenLayout
    sink = WindowsOutputSink(FakeBackend((10, 10)), ScreenLayout.single(1920, 1080), WindowsOutputConfig(), threaded=False)
    assert sink.apply(ActionCommand(t=0.0, action="mouse.place", phase="hold", gesture=vh.PLACE, point=(.5, 1.0))).accepted
    assert sink.cursor.pos == (960, 1079)
    assert not sink.apply(ActionCommand(t=0.0, action="mouse.place", phase="hold", gesture=vh.PLACE)).accepted


def test_the_composed_engine_routes_the_virtual_hand_to_mouse_actions():
    from manux.app import build_engine, schema
    from manux.settings.store import Settings
    engine = build_engine(Settings(schema()), "virtual_hand")
    try:
        results, t = [], 1.0
        for lm in [OPEN] * 3 + [PINCH] * 3 + [OPEN] * 3:
            frame = FrameInfo(int(t * 1000), t, W, H, True)
            snap = engine.step(frame, HandObservation(frame, lm, "Right", .99))
            assert snap.mode == "virtual_hand" and not snap.errors and not snap.unrouted
            results += snap.results
            t += 1 / 30
        assert ("mouse.place", "hold", "ok") in results and ("mouse.left_click", "tap", "ok") in results
    finally:
        engine.shutdown()
