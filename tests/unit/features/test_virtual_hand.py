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


# ------------------------------------------------------------------ the drawn hand and the click between its fingers
def test_router_passes_the_frame_offset_only_to_actions_that_take_it():
    from manux.actions.bindings import Binding
    from manux.actions.router import Router
    from manux.core.contracts import Intent
    router = Router({vh.PLACE: Binding("mouse.place", {"offset": (9.0, 9.0)}), vh.LEFT: Binding("mouse.left_click")})
    cmd = router.route(Intent(1.0, vh.ID, vh.PLACE, "hold", point=(.5, .5), offset=(.1, -.2))).command
    assert cmd.params["offset"] == (.1, -.2)
    assert "offset" not in router.route(Intent(1.0, vh.ID, vh.PLACE, "hold", point=(.5, .5))).command.params
    assert "offset" not in router.route(Intent(1.0, vh.ID, vh.LEFT, "tap", offset=(.1, .1))).command.params
    with pytest.raises(ValueError):
        Intent(1.0, vh.ID, vh.PLACE, "hold", point=(.5, .5), offset=(float("nan"), 0))


def test_mouse_place_offset_moves_the_cursor_between_the_drawn_fingers():
    from manux.core.contracts import ActionCommand
    from manux.output.windows import FakeBackend, WindowsOutputConfig, WindowsOutputSink
    from manux.platform.monitors import ScreenLayout
    sink = WindowsOutputSink(FakeBackend((10, 10)), ScreenLayout.single(1920, 1080),
                             WindowsOutputConfig(virtual_hand_px=100.0), threaded=False)
    sink.apply(ActionCommand(t=0.0, action="mouse.place", phase="hold", gesture=vh.PLACE, point=(.5, .5),
                             params={"offset": (-.3, -.6)}))
    palm = sink.virtual_palm
    assert sink.cursor.pos == (palm[0] - 30, palm[1] - 60)
    sink.apply(ActionCommand(t=0.0, action="mouse.place", phase="hold", gesture=vh.PLACE, point=(0.0, 0.0),
                             params={"offset": (-5.0, -5.0)}))
    assert sink.cursor.pos == (0, 0)                                  # never off the monitor


def test_the_cursor_is_the_clicking_point_and_the_drawing_is_anchored_on_it():
    """2026-11-10: no per-click offset any more (it made the cursor jump when the fingers met)."""
    f = vh.VirtualHandFeature()
    out, t = run(f, [OPEN] * 6 + [PINCH] * 4 + [OPEN] * 3)
    assert all(i.offset is None for i in out if i.gesture == vh.PLACE) and taps(out, vh.LEFT)
    view = f.last_view
    assert len(view["pts"]) == 42 and len(view["anchor"]) == 2 and view["aim"] and not view["lost"]
    f2 = vh.VirtualHandFeature()
    run(f2, [OPEN] * 6)
    run(f2, [PINCH] * 3, t0=2.0)
    frozen = list(f2.last_view["anchor"])
    run(f2, [PINCH] * 3, t0=2.2)
    assert f2.last_view["anchor"] == frozen and not f2.last_view["aim"]       # still while clicking


def test_box_edges_are_monitor_edges():
    def at(dx):
        moved = tuple((x + dx, y, z) for x, y, z in OPEN)
        out, _ = run(vh.VirtualHandFeature(), [moved] * 20)
        return [i.point for i in out if i.gesture == vh.PLACE][-1]
    cx, _ = shapes.palm_centre(OPEN)
    assert at(.8 - cx + .02)[0] == 1.0 and at(.2 - cx - .02)[0] == 0.0       # past the box edge = exactly the edge


def steps(points):
    import math
    return [math.dist(a, b) for a, b in zip(points, points[1:])]


def test_releasing_a_hold_eases_to_the_hand_instead_of_jumping():
    f = vh.VirtualHandFeature()
    still = [OPEN] * 10
    pinched_moving = [tuple((x + .006 * k, y, z) for x, y, z in PINCH) for k in range(10)]   # moves while held
    after = [tuple((x + .06, y, z) for x, y, z in OPEN)] * 15
    out, _ = run(f, still + pinched_moving + after)
    pts = [i.point for i in out if i.gesture == vh.PLACE]
    assert max(steps(pts[19:])) < .5 * (pts[-1][0] - pts[19][0])            # no single-frame landing
    assert abs(pts[-1][0] - pts[-2][0]) < 1e-3                               # and it arrives


def test_finding_the_hand_again_eases_in():
    f = vh.VirtualHandFeature()
    out, t = run(f, [OPEN] * 10)
    far = tuple((x + .2, y, z) for x, y, z in OPEN)
    out2, _ = run(f, [None] * 6 + [far] * 12, t0=t)
    pts = [i.point for i in out2 if i.gesture == vh.PLACE]
    total = abs(pts[-1][0] - [i.point for i in out if i.gesture == vh.PLACE][-1][0])
    assert total > .2 and max(steps(pts)) < .5 * total


def test_aim_back_only_undoes_a_tilt_not_a_real_move():
    m = shapes.BoxMapper()
    box = (.2, .15, .8, .85)
    for k in range(10):                                                      # a fast real move just before the pinch
        m.target(tuple((x + .02 * k, y, z) for x, y, z in OPEN), box, now=k / 30)
    moving_to = m.pos
    held = m.target(tuple((x + .2, y, z) for x, y, z in OPEN), box, hold=True, now=10 / 30)
    assert held == moving_to                                                 # no jump back 0.15 s along the move


def test_the_runtime_hands_the_drawing_to_the_ui_only_in_this_mode():
    from types import SimpleNamespace
    from manux.app import schema
    from manux.core.contracts import OutputTarget
    from manux.desktop import build
    from manux.settings.store import Settings
    runtime = build(Settings(schema()), SimpleNamespace(close=lambda: None), windows=False)
    try:
        feature = next(x for x in runtime.engine.features if x.id == vh.ID)
        feature.last_view = {"pts": [0.0] * 42, "anchor": [0.0, 0.0], "aim": True, "grip": False, "lost": False}
        runtime.engine.sinks[OutputTarget.WINDOWS] = SimpleNamespace(virtual_palm=(800, 600), _display_scale=lambda: 1.5)
        snap = lambda mode, out=OutputTarget.WINDOWS: SimpleNamespace(mode=mode, output=out)
        view = runtime._virtual_hand_view(snap("virtual_hand"))
        assert view["palm"] == [800, 600] and view["scale"] == 1.5 and len(view["pts"]) == 42
        assert runtime._virtual_hand_view(snap("pinch")) is None
        assert runtime._virtual_hand_view(snap("virtual_hand", OutputTarget.PRACTICE)) is None
    finally:
        runtime.engine.sinks.pop(OutputTarget.WINDOWS, None)
        runtime.stop()


def test_turning_the_hand_toward_the_camera_does_not_blow_up_the_drawing():
    """2026-11-10 report: fingers turned toward the camera drew a huge hand (the 2D wrist -> knuckle length collapsed)."""
    world = tuple((x - .5, y - .7, 0.0) for x, y, _ in OPEN)                   # metres-ish, flat palm
    facing = OPEN
    turned = tuple((x, .70 + (y - .70) * .25, z) for x, y, z in OPEN)          # same hand, fingers pointing at the camera
    flat_size = shapes.hand_size_px(facing, W, H, world)
    assert shapes.hand_size_px(turned, W, H, world) == pytest.approx(flat_size, rel=.05)
    import math
    naive = lambda lm: math.dist((lm[0][0] * W, lm[0][1] * H), (lm[9][0] * W, lm[9][1] * H))
    assert naive(turned) < .3 * naive(facing)                                # what used to scale the drawing
    assert shapes.hand_size_px(turned, W, H) >= .7 * shapes.hand_size_px(facing, W, H)   # no world: palm width rescues


def test_the_drawn_size_follows_slowly_not_in_one_frame():
    f = vh.VirtualHandFeature()
    run(f, [OPEN] * 10)
    before = max(abs(v) for v in f.last_view["pts"])
    small = tuple((.5 + (x - .5) * .5, .6 + (y - .6) * .5, z) for x, y, z in OPEN)   # hand suddenly half the size
    run(f, [small], t0=2.0)
    assert max(abs(v) for v in f.last_view["pts"]) < 1.5 * before


def test_fist_browsing_speed_is_a_setting_and_slower_by_default():
    out, _ = run(vh.VirtualHandFeature(), [FIST] * 3)
    scrolls = [i for i in out if i.gesture == vh.SCROLL]
    assert scrolls and all(i.scale == .25 for i in scrolls)              # was 0.5 (2026-11-10: too fast)
    out, _ = run(vh.VirtualHandFeature(), [FIST] * 3, settings={"scroll_speed": .1})
    assert all(i.scale == .1 for i in out if i.gesture == vh.SCROLL)
    from manux.actions.bindings import Binding
    from manux.actions.router import Router
    cmd = Router({vh.SCROLL: Binding("mouse.scroll")}).route(scrolls[0]).command
    assert cmd.params["gain"] == .25                                      # what the sink scrolls with
