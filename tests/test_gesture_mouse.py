"""
Unit tests for GestureEngine (finger selection, pen-on-paper) and MouseController (`dry_run=True`).
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from src.gesture_engine import GestureEngine, GestureResult, Point3D
from src.mouse_controller import MouseController, OneEuroFilter2D


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    """Engines in tests use built-in defaults, not the user's saved config/gestures.json."""
    import src.gesture_engine as ge

    # The pen / range tests below were written for the pinch-to-move modes; thumb-mode
    # tests switch the mode themselves.
    cfg = tmp_path / "gestures.json"
    # Exact-geometry tests: raw landmarks (no smoothing) and finger-curl up/down unless a
    # test switches these itself.
    cfg.write_text('{"movement_mode": "relative", "landmark_filter": false, "vertical_source": "fingers"}',
                   encoding="utf-8")
    monkeypatch.setattr(ge, "DEFAULT_CONFIG_PATH", cfg)

# A right hand seen from above, fingers pointing to the top of the image. Palm ~0.23.
BASE_HAND: Dict[int, Tuple[float, float]] = {
    0: (0.50, 0.72),  # wrist
    1: (0.43, 0.66), 2: (0.38, 0.60), 3: (0.35, 0.55), 4: (0.33, 0.50),  # thumb
    5: (0.44, 0.50), 6: (0.44, 0.42), 7: (0.44, 0.36), 8: (0.44, 0.31),  # index
    9: (0.50, 0.49), 10: (0.50, 0.40), 11: (0.50, 0.33), 12: (0.50, 0.28),  # middle
    13: (0.56, 0.50), 14: (0.56, 0.42), 15: (0.56, 0.36), 16: (0.56, 0.31),  # ring
    17: (0.61, 0.53), 18: (0.62, 0.46), 19: (0.62, 0.41), 20: (0.62, 0.37),  # pinky
}
TIPS = {"index": 8, "middle": 12, "ring": 16, "pinky": 20}


def make_hand(
    touch: Optional[str] = None,
    gap: float = 0.005,
    shift: Tuple[float, float] = (0.0, 0.0),
    angle_deg: float = 0.0,
    scale: float = 1.0,
    overrides: Optional[Dict[int, Tuple[float, float]]] = None,
) -> List[Point3D]:
    """Build 21 landmarks. `touch` puts the thumb tip on that fingertip (or between
    index and middle for 'index_middle'); shift/angle/scale move the whole hand."""
    pts = dict(BASE_HAND)
    if overrides:
        pts.update(overrides)
    if touch == "index_middle":
        a, b = pts[8], pts[12]
        pts[4] = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + gap)
    elif touch is not None:
        tip = pts[TIPS[touch]]
        pts[4] = (tip[0], tip[1] + gap)
    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    out = []
    for i in range(21):
        x, y = pts[i]
        x, y = (x - 0.5) * scale, (y - 0.5) * scale
        x, y = x * cos_a - y * sin_a, x * sin_a + y * cos_a
        out.append(Point3D(0.5 + x + shift[0], 0.5 + y + shift[1], 0.0))
    return out


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        self.t += 1.0 / 30.0
        return self.t


def run(engine: GestureEngine, hand: List[Point3D], clock: Clock, frames: int = 1) -> List[GestureResult]:
    return [engine.process(hand, timestamp=clock()) for _ in range(frames)]


# ---------------------------------------------------------------- config


def test_config_file_has_required_fields():
    data = json.loads((PROJECT_ROOT / "config" / "gestures.json").read_text(encoding="utf-8"))
    assert data["movement_mode"] in ("thumb", "range", "relative")
    for key in (
        "pinch_threshold",
        "release_threshold",
        "click_threshold",
        "finger_separation",
        "click_confirm_frames",
        "pen_speed",
        "paper_depth_gain",
    ):
        assert key in data
    assert data["release_threshold"] > data["pinch_threshold"]
    g = data["gestures"]
    assert g["thumb_index_pinch"]["action"] == "move_cursor"
    assert g["thumb_middle_pinch"]["action"] == "left_click"
    assert g["thumb_ring_pinch"]["action"] == "right_click"
    assert g["thumb_index_middle_pinch"]["enabled"] is False
    assert g["thumb_pinky_pinch"]["enabled"] is False


# ------------------------------------------------------- finger selection


def test_open_hand_is_idle_and_index_pinch_moves_with_hysteresis():
    engine, clock = GestureEngine(), Clock()
    res = run(engine, make_hand(), clock)[0]
    assert res.action == "none" and res.is_moving is False

    res = run(engine, make_hand("index"), clock)[0]
    assert res.action == "move_cursor"
    assert res.is_moving is True
    assert engine.is_pinched

    # Slightly opened (between enter and release threshold) -> still pen down
    hand = make_hand("index")
    hand[4] = Point3D(hand[8].x - 0.075, hand[8].y, 0.0)  # thumb beside the tip, not along the finger
    res = run(engine, hand, clock)[0]
    assert 0.055 < res.distances["index"] < 0.080
    assert res.is_moving is True

    # Wide open -> pen up
    res = run(engine, make_hand(), clock)[0]
    assert res.is_moving is False
    assert not engine.is_pinched


def test_middle_pinch_left_clicks_once_per_pinch():
    engine, clock = GestureEngine(), Clock()
    results = run(engine, make_hand("middle"), clock, frames=5)
    # Needs 2 frames to confirm, then fires exactly once while held
    assert [r.action for r in results] == ["none", "left_click", "none", "none", "none"]
    assert results[0].pending_gesture == "thumb_middle_pinch"
    assert results[1].active_gesture == "thumb_middle_pinch"
    assert results[4].active_gesture == "thumb_middle_pinch"
    # Clicks never move the cursor
    assert not any(r.is_moving for r in results)

    run(engine, make_hand(), clock, frames=6)  # release (> cooldown 0.15s)
    actions = [r.action for r in run(engine, make_hand("middle"), clock, frames=4)]
    assert actions.count("left_click") == 1


def test_ring_pinch_right_clicks_even_when_middle_bends_along():
    engine, clock = GestureEngine(), Clock()
    # Middle tip pulled toward the thumb (sympathetic bend), but ring is the one touching.
    bent = {12: (0.54, 0.34), 11: (0.53, 0.37)}
    results = run(engine, make_hand("ring", overrides=bent), clock, frames=4)
    assert [r.action for r in results] == ["none", "right_click", "none", "none"]
    assert results[1].active_gesture == "thumb_ring_pinch"


def test_middle_pinch_wins_over_nearby_index():
    engine, clock = GestureEngine(), Clock()
    # Index tip curled close to the middle tip while the thumb touches the middle.
    near_index = {8: (0.47, 0.30), 7: (0.46, 0.34)}
    results = run(engine, make_hand("middle", overrides=near_index), clock, frames=2)
    assert results[-1].action == "left_click"
    assert not any(r.is_moving for r in results)


def test_ambiguous_thumb_between_two_fingers_does_nothing():
    engine, clock = GestureEngine(), Clock()
    results = run(engine, make_hand("index_middle", gap=0.0), clock, frames=4)
    assert all(r.action == "none" for r in results)
    assert not engine.is_pinched


def test_disabled_pinky_does_not_fire():
    engine, clock = GestureEngine(), Clock()
    results = run(engine, make_hand("pinky"), clock, frames=3)
    assert all(r.action == "none" for r in results)


def test_drag_hold_combo_when_enabled():
    engine, clock = GestureEngine(), Clock()
    engine.set_gesture_action("thumb_index_middle_pinch", "drag_hold", enabled=True)
    res = run(engine, make_hand("index_middle", gap=0.0), clock, frames=2)[-1]
    assert res.action == "drag_hold"
    assert res.is_moving is True


def test_custom_mapping_and_save(tmp_path: Path):
    cfg_path = tmp_path / "g.json"
    engine = GestureEngine(config_path=cfg_path)
    engine.set_movement_mode("relative")  # pinch clicks (thumb mode uses finger straightening)
    engine.set_gesture_action("thumb_pinky_pinch", "left_click", enabled=True)
    engine.save_config()
    reloaded = GestureEngine(config_path=cfg_path)
    clock = Clock()
    results = run(reloaded, make_hand("pinky"), clock, frames=2)
    assert results[-1].action == "left_click"
    with pytest.raises(ValueError):
        engine.set_gesture_action("thumb_pinky_pinch", "explode")


def test_aspect_ratio_is_undone_with_image_size():
    engine = GestureEngine()
    hand = make_hand("index", gap=0.0)
    hand[4] = Point3D(hand[8].x + 0.03, hand[8].y, 0.0)  # horizontal gap in normalized x
    square = engine.process(hand, timestamp=1.0).distances["index"]
    engine.reset()
    wide = engine.process(hand, timestamp=2.0, image_size=(1280, 720)).distances["index"]
    # Palm is mostly vertical, so a horizontal gap counts more once x is widened.
    assert wide > square


# ------------------------------------------------------------ pen on paper


def test_pen_draws_on_paper_and_lifting_keeps_position():
    engine, clock = GestureEngine(), Clock()
    engine.config["vertical_source"] = "hand"  # up/down from hand movement
    engine.config["paper_depth_gain"] = 1.0
    run(engine, make_hand(), clock, frames=3)

    p0 = run(engine, make_hand("index"), clock)[0].paper_point
    # Move right by 0.05 in the image (about 0.22 palm widths); left/right is inverted by default
    p1 = run(engine, make_hand("index", shift=(0.05, 0.0)), clock)[0].paper_point
    assert p0[0] - p1[0] == pytest.approx(0.05 / 0.23, rel=0.15)
    assert abs(p1[1] - p0[1]) < 1e-6

    # Move forward (= image up) -> paper y decreases (cursor goes up)
    p2 = run(engine, make_hand("index", shift=(0.05, -0.04)), clock)[0].paper_point
    assert p2[1] < p1[1]

    # Lift the pen and move back left: paper position must not change
    run(engine, make_hand(shift=(0.05, -0.04)), clock)
    lifted = run(engine, make_hand(shift=(-0.10, 0.0)), clock)[0]
    assert lifted.paper_point == pytest.approx(p2)
    assert lifted.is_moving is False

    # Put the pen down again elsewhere: no jump on the pen-down frame
    p3 = run(engine, make_hand("index", shift=(-0.10, 0.0)), clock)[0].paper_point
    assert p3 == pytest.approx(p2)


def test_paper_depth_gain_stretches_forward_motion():
    def forward_step(gain: float) -> float:
        engine, clock = GestureEngine(), Clock()
        engine.config["vertical_source"] = "hand"  # up/down from hand movement
        engine.config["paper_depth_gain"] = gain
        run(engine, make_hand(), clock, frames=3)
        a = run(engine, make_hand("index"), clock)[0].paper_point
        b = run(engine, make_hand("index", shift=(0.0, -0.04)), clock)[0].paper_point
        return a[1] - b[1]

    assert forward_step(1.5) == pytest.approx(forward_step(1.0) * 1.5, rel=1e-6)


def test_paper_motion_is_in_palm_units():
    def step(scale: float) -> float:
        engine, clock = GestureEngine(), Clock()
        run(engine, make_hand(scale=scale), clock, frames=30)  # settle palm size
        a = run(engine, make_hand("index", scale=scale), clock)[0].paper_point
        b = run(engine, make_hand("index", scale=scale, shift=(0.04 * scale, 0.0)), clock)[0].paper_point
        return b[0] - a[0]

    # A hand half as big (farther away) moving half as far = same move on the paper
    assert step(0.5) == pytest.approx(step(1.0), rel=0.05)


def test_auto_direction_snaps_to_hand_axis_and_calibration_locks_it():
    engine, clock = GestureEngine(), Clock()
    engine.config["vertical_source"] = "hand"  # up/down from hand movement
    # Fingers point to the image right (camera rotated 90 degrees)
    run(engine, make_hand(angle_deg=90), clock, frames=40)
    assert engine.forward_angle == pytest.approx(math.pi / 2)

    a = run(engine, make_hand("index", angle_deg=90), clock)[0].paper_point
    b = run(engine, make_hand("index", angle_deg=90, shift=(0.04, 0.0)), clock)[0].paper_point
    # Moving toward the fingertips = forward = cursor up
    assert b[1] < a[1]
    assert abs(b[0] - a[0]) < 1e-6

    # Lock a slanted direction
    run(engine, make_hand(angle_deg=30), clock, frames=2)
    assert engine.calibrate_neutral()
    assert engine.is_calibrated
    assert engine.forward_angle == pytest.approx(math.radians(30), abs=0.03)
    run(engine, make_hand(angle_deg=90), clock, frames=40)
    assert engine.forward_angle == pytest.approx(math.radians(30), abs=0.03)
    engine.clear_calibration()
    assert not engine.is_calibrated


def test_paper_to_image_inverts_paper_motion():
    engine, clock = GestureEngine(), Clock()
    run(engine, make_hand(angle_deg=90), clock, frames=40)
    ix, iy = engine.paper_to_image(0.0, -1.0)  # one palm forward on the paper
    # Forward is toward the fingertips = image right for this hand
    assert ix > 0 and abs(iy) < 1e-9


# ---------------------------------------------------------- mouse control


def _move(point: Tuple[float, float], paper: Tuple[float, float]) -> GestureResult:
    return GestureResult(
        active_gesture="thumb_index_pinch",
        action="move_cursor",
        cursor_point=point,
        paper_point=paper,
        is_moving=True,
    )


IDLE = GestureResult()


def test_mouse_pen_mode_moves_by_paper_steps_without_jumps():
    ctrl = MouseController(dry_run=True, screen_size=(1920, 1080))
    cfg = {"smoothing": 1.0, "movement_mode": "relative", "pen_speed": 0.8, "dpi_scale": 1.0}
    start = ctrl.last_screen_pos

    # Pen down: anchor only, no jump
    assert ctrl.apply(_move((0.3, 0.3), (2.0, 5.0)), cfg) == start
    # Half a palm right -> 0.5 * 1920 * 0.8 = 768 px; same scale on y
    pos = ctrl.apply(_move((0.3, 0.3), (2.5, 4.9)), cfg)
    assert pos[0] - start[0] == 768
    assert start[1] - pos[1] == pytest.approx(154, abs=1)

    # Pen up, then down at a totally different paper point -> no jump
    ctrl.apply(IDLE, cfg)
    assert ctrl.apply(_move((0.9, 0.9), (-7.0, 1.0)), cfg) == pos


def test_mouse_pen_mode_edge_has_no_dead_travel():
    ctrl = MouseController(dry_run=True, screen_size=(1000, 800))
    cfg = {"smoothing": 1.0, "movement_mode": "relative", "pen_speed": 1.0, "dpi_scale": 1.0}
    ctrl.apply(_move((0, 0), (0.0, 0.0)), cfg)
    assert ctrl.apply(_move((0, 0), (3.0, 0.0)), cfg)[0] == 999  # far past the right edge
    back = ctrl.apply(_move((0, 0), (2.9, 0.0)), cfg)
    assert back[0] == 899  # moves left immediately


def test_mouse_absolute_mode_and_drag_safety():
    ctrl = MouseController(dry_run=True, screen_size=(1920, 1080))
    cfg = {"smoothing": 1.0, "active_margin": 0.15, "movement_mode": "absolute", "dpi_scale": 1.0}
    pos = ctrl.apply(_move((0.5, 0.5), (0.0, 0.0)), cfg)
    assert abs(pos[0] - 960) <= 1 and abs(pos[1] - 540) <= 1

    drag = GestureResult(action="drag_hold", cursor_point=(0.6, 0.6), paper_point=(0.0, 0.0), is_moving=True)
    ctrl.apply(drag, cfg)
    assert ctrl.is_dragging is True
    ctrl.apply(_move((0.6, 0.6), (0.0, 0.0)), cfg)
    assert ctrl.is_dragging is False

    ctrl.apply(GestureResult(action="drag_toggle"), cfg)
    assert ctrl.is_dragging is True
    ctrl.release_all()
    assert ctrl.is_dragging is False


def test_mouse_clicks_are_logged_once():
    ctrl = MouseController(dry_run=True, screen_size=(1920, 1080))
    ctrl.apply(GestureResult(action="left_click"), {})
    ctrl.apply(GestureResult(active_gesture="thumb_middle_pinch"), {})
    ctrl.apply(GestureResult(action="right_click"), {})
    assert ctrl.event_log == ["left_click", "right_click"]


def test_engine_to_mouse_end_to_end_pen_then_click():
    engine, clock = GestureEngine(), Clock()
    ctrl = MouseController(dry_run=True, screen_size=(1920, 1080))
    cfg = dict(engine.config, smoothing=1.0)
    start = ctrl.last_screen_pos
    for hand in (
        make_hand(),
        make_hand("index"),
        make_hand("index", shift=(0.05, 0.0)),
        make_hand(shift=(0.05, 0.0)),
        make_hand("middle", shift=(0.05, 0.0)),
        make_hand("middle", shift=(0.05, 0.0)),
        make_hand("middle", shift=(0.05, 0.0)),
    ):
        ctrl.apply(engine.process(hand, timestamp=clock()), cfg)
    assert ctrl.last_screen_pos[0] < start[0] - 100  # image right = cursor left (inverted)
    assert ctrl.last_screen_pos[1] == start[1]
    assert ctrl.event_log == ["left_click"]


def test_paper_invert_x_flips_only_left_right():
    def step(invert: bool, shift: tuple) -> tuple:
        engine, clock = GestureEngine(), Clock()
        engine.config["vertical_source"] = "hand"  # up/down from hand movement
        engine.config["paper_invert_x"] = invert
        run(engine, make_hand(), clock, frames=3)
        a = run(engine, make_hand("index"), clock)[0].paper_point
        b = run(engine, make_hand("index", shift=shift), clock)[0].paper_point
        return b[0] - a[0], b[1] - a[1]

    nx, ny = step(False, (0.04, -0.03))
    ix, iy = step(True, (0.04, -0.03))
    assert nx > 0 and ix == pytest.approx(-nx)
    assert iy == pytest.approx(ny) and iy < 0  # up/down unchanged


def _dist(index: float, middle: float, ring: float = 0.2, pinky: float = 0.3) -> dict:
    return {"index": index, "middle": middle, "ring": ring, "pinky": pinky}


def test_middle_takes_over_from_pen_when_index_stays_near():
    """The pen goes down while the thumb passes the index tip. At the middle tip the index
    is still inside its release distance and not much farther than the middle."""
    engine = GestureEngine()
    assert engine._update_pinch_state(_dist(0.03, 0.12), 1.0) is False
    assert engine.is_pinched
    fired = [engine._update_pinch_state(_dist(0.060, 0.048), 1.0 + k / 30) for k in range(1, 5)]
    assert fired.count(True) == 1
    assert engine.active_finger == "middle"


def test_held_click_is_not_stolen_by_neighbour_click_finger():
    """While the ring is held (right click), a middle finger drifting closer must not left-click."""
    engine = GestureEngine()
    fired = [engine._update_pinch_state(_dist(0.2, 0.06, ring=0.03), 1.0 + k / 30) for k in range(3)]
    assert fired.count(True) == 1 and engine.active_finger == "ring"
    fired = [engine._update_pinch_state(_dist(0.2, 0.04, ring=0.06), 2.0 + k / 30) for k in range(4)]
    assert not any(fired)
    assert engine.active_finger == "ring"


def test_loose_middle_pinch_still_clicks():
    engine = GestureEngine()
    # 0.07 was over the old click threshold (0.065); the middle is clearly closest
    fired = [engine._update_pinch_state(_dist(0.10, 0.07), 1.0 + k / 30) for k in range(4)]
    assert fired == [False, True, False, False]
    assert engine.active_finger == "middle"



def _arc_hand(theta_deg: float, pivot=(0.5, 1.4)) -> List[Point3D]:
    """Pen-down hand swung around an elbow below the image by theta degrees."""
    hand = make_hand("index")
    rad = math.radians(theta_deg)
    c, s_ = math.cos(rad), math.sin(rad)
    out = []
    for p in hand:
        x, y = p.x - pivot[0], p.y - pivot[1]
        out.append(Point3D(pivot[0] + x * c - y * s_, pivot[1] + x * s_ + y * c, 0.0))
    return out


@pytest.mark.parametrize("straighten", [True, False])
def test_elbow_arc_becomes_straight_line(straighten: bool):
    engine, clock = GestureEngine(), Clock()
    engine.config["vertical_source"] = "hand"  # up/down from hand movement
    engine.config["straighten_arcs"] = straighten
    run(engine, make_hand(), clock, frames=3)
    start = None
    for k in range(0, 31):
        res = engine.process(_arc_hand(k * 1.0), timestamp=clock())
        if start is None:
            start = res.paper_point
    du = res.paper_point[0] - start[0]
    dv = res.paper_point[1] - start[1]
    assert abs(du) > 1.5  # a long sideways stroke
    if straighten:
        assert abs(dv) < 0.06 * abs(du)
    else:
        assert abs(dv) > 0.15 * abs(du)  # plain x, y follows the curve


def test_one_euro_filter_jitter_suppression_and_responsiveness():
    """Verify OneEuroFilter2D heavily dampens stationary jitter while dynamically reducing lag at high speed."""
    import math

    # 1. Jitter suppression test at stationary hover
    f_jitter = OneEuroFilter2D(min_cutoff=1.0, beta=0.04, d_cutoff=1.0)
    raw_vals = []
    filtered_vals = []
    t = 10.0
    dt = 1.0 / 60.0

    for i in range(120):
        # Stationary signal (500.0) with synthetic high-frequency tremor (+/- 4px)
        raw_x = 500.0 + 4.0 * math.sin(i * 0.9)
        fx, _ = f_jitter.filter(raw_x, 300.0, timestamp=t)
        t += dt
        if i >= 30:  # Skip initial filter warmup transient
            raw_vals.append(raw_x)
            filtered_vals.append(fx)

    raw_var = sum((x - 500.0) ** 2 for x in raw_vals) / len(raw_vals)
    filtered_var = sum((x - 500.0) ** 2 for x in filtered_vals) / len(filtered_vals)

    # Filtered signal variance should be reduced by at least 60% compared to raw tremor
    assert filtered_var < 0.40 * raw_var

    # 2. Fast movement responsiveness test
    # Moving dynamically at high velocity: cutoff increases dynamically with beta * speed
    f_dynamic = OneEuroFilter2D(min_cutoff=1.0, beta=0.05, d_cutoff=1.0)
    f_static = OneEuroFilter2D(min_cutoff=1.0, beta=0.0, d_cutoff=1.0)  # static low-pass

    t = 20.0
    # Warm up filters at 100.0
    for _ in range(20):
        f_dynamic.filter(100.0, 100.0, timestamp=t)
        f_static.filter(100.0, 100.0, timestamp=t)
        t += dt

    # Rapid high-speed sweep: hand moves 600px across 3 frames (speed ~ 12,000 px/sec)
    sweep_target = 700.0
    dyn_x, _ = f_dynamic.filter(sweep_target, 100.0, timestamp=t)
    stat_x, _ = f_static.filter(sweep_target, 100.0, timestamp=t)

    # Dynamic beta adaptation should adapt cutoff and track target with much lower lag
    dyn_lag = abs(sweep_target - dyn_x)
    stat_lag = abs(sweep_target - stat_x)
    assert dyn_lag < stat_lag * 0.60

    # 3. Reset behavior
    f_dynamic.reset()
    assert f_dynamic._x_prev is None
    assert f_dynamic._t_prev is None
    # After reset, the first sample initializes directly without lag
    first_x, first_y = f_dynamic.filter(950.0, 420.0, timestamp=30.0)
    assert first_x == 950.0
    assert first_y == 420.0


def test_mouse_controller_deadzone_px():
    """Verify deadzone_px prevents sub-pixel jitter from jittering OS cursor while allowing deliberate moves."""
    import time

    ctrl = MouseController(dry_run=True, screen_size=(1920, 1080))
    cfg = {
        "smoothing": 0.35,
        "deadzone_px": 2.5,
        "active_margin": 0.15,
        "movement_mode": "absolute",
    }

    # Initial anchor position at frame center
    pos0 = ctrl.apply(
        GestureResult(
            active_gesture="thumb_index_pinch",
            action="move_cursor",
            cursor_point=(0.50, 0.50),
            pinch_distance=0.02,
            is_moving=True,
        ),
        cfg,
    )

    # Advance time by 1 frame (30 FPS)
    ctrl._one_euro._t_prev = time.perf_counter() - 0.033
    # Apply micro-jitter (delta 0.0003 corresponds to < 0.6 px on screen, well below deadzone_px 2.5)
    pos1 = ctrl.apply(
        GestureResult(
            active_gesture="thumb_index_pinch",
            action="move_cursor",
            cursor_point=(0.5003, 0.5002),
            pinch_distance=0.02,
            is_moving=True,
        ),
        cfg,
    )
    # Cursor position must remain stationary
    assert pos1 == pos0

    # Advance time by 1 frame (30 FPS)
    ctrl._one_euro._t_prev = time.perf_counter() - 0.033
    # Deliberate movement (delta 0.06 corresponds to > 100 px, far exceeding deadzone)
    pos2 = ctrl.apply(
        GestureResult(
            active_gesture="thumb_index_pinch",
            action="move_cursor",
            cursor_point=(0.56, 0.56),
            pinch_distance=0.02,
            is_moving=True,
        ),
        cfg,
    )
    assert pos2 != pos0
    assert pos2[0] > pos0[0]
    assert pos2[1] > pos0[1]



# ------------------------------------------------------------ fine control


def _pen(paper: Tuple[float, float], t: float) -> GestureResult:
    return GestureResult(action="move_cursor", paper_point=paper, is_moving=True, timestamp=t)


def _stroke(ctrl: MouseController, cfg: dict, speed: float, seconds: float = 0.5, fps: int = 30) -> int:
    """Move the pen right at `speed` palm widths per second; return cursor travel in px."""
    t, u = 10.0, 0.0
    start = ctrl.apply(_pen((u, 0.0), t), cfg)[0]
    for _ in range(int(seconds * fps)):
        t += 1.0 / fps
        u += speed / fps
        ctrl.apply(_pen((u, 0.0), t), cfg)
    return abs(ctrl.last_screen_pos[0] - start)


def test_accel_gain_curve():
    cfg = {"accel_min_gain": 0.25, "accel_max_gain": 1.2, "accel_low_speed": 0.15, "accel_high_speed": 1.5}
    assert MouseController.accel_gain(0.0, cfg) == pytest.approx(0.25)
    assert MouseController.accel_gain(0.15, cfg) == pytest.approx(0.25)
    assert MouseController.accel_gain(5.0, cfg) == pytest.approx(1.2)
    mid = MouseController.accel_gain(0.8, cfg)
    assert 0.25 < mid < 1.2


def test_slow_strokes_move_less_per_hand_distance():
    cfg = {"smoothing": 1.0, "movement_mode": "relative", "pen_speed": 0.8, "pointer_acceleration": True}
    slow = _stroke(MouseController(dry_run=True, screen_size=(1920, 1080)), cfg, speed=0.1, seconds=2.0)
    fast = _stroke(MouseController(dry_run=True, screen_size=(1920, 1080)), cfg, speed=2.0, seconds=0.1)
    # Same hand distance (0.2 palm widths): the slow stroke moves the cursor ~4x less
    assert slow < fast * 0.35
    assert slow == pytest.approx(0.2 * 1920 * 0.8 * 0.2, rel=0.15)  # min gain 0.2


def test_lift_rolls_back_small_drift_but_keeps_fast_swipe():
    cfg = {"smoothing": 1.0, "movement_mode": "relative", "pen_speed": 1.0, "lift_rollback_s": 0.1}
    ctrl = MouseController(dry_run=True, screen_size=(1920, 1080))
    t = 10.0
    ctrl.apply(_pen((0.0, 0.0), t), cfg)
    for k in range(1, 11):  # aim: 10 slow steps
        t += 1 / 30
        ctrl.apply(_pen((k * 0.002, 0.0), t), cfg)
    aimed = ctrl.last_screen_pos
    for k in range(1, 4):  # fingers opening: small drift in the last 0.1 s
        t += 1 / 30
        ctrl.apply(_pen((0.02 + k * 0.006, 0.0), t), cfg)
    assert ctrl.last_screen_pos != aimed
    ctrl.apply(GestureResult(timestamp=t + 1 / 30), cfg)
    assert abs(ctrl.last_screen_pos[0] - aimed[0]) <= 1
    assert "rollback" in ctrl.event_log

    # A fast swipe right before lifting is kept
    ctrl2 = MouseController(dry_run=True, screen_size=(1920, 1080))
    t = 10.0
    ctrl2.apply(_pen((0.0, 0.0), t), cfg)
    for k in range(1, 4):
        t += 1 / 30
        ctrl2.apply(_pen((k * 0.1, 0.0), t), cfg)
    swiped = ctrl2.last_screen_pos
    ctrl2.apply(GestureResult(timestamp=t + 1 / 30), cfg)
    assert ctrl2.last_screen_pos == swiped
    assert "rollback" not in ctrl2.event_log


def test_default_filter_holds_still_cursor_and_follows_fast_moves():
    from src.gesture_engine import DEFAULT_CONFIG

    cfg = dict(DEFAULT_CONFIG, pointer_acceleration=False, movement_mode="absolute", dpi_scale=1.0)
    ctrl = MouseController(dry_run=True, screen_size=(1920, 1080))
    t = 10.0
    positions = []
    for k in range(60):  # hand still, landmark jitter of +/- 0.002 (about 5 px)
        t += 1 / 30
        jitter = 0.002 * (1 if k % 2 else -1)
        res = GestureResult(action="move_cursor", cursor_point=(0.5 + jitter, 0.5), is_moving=True, timestamp=t)
        positions.append(ctrl.apply(res, cfg)[0])
    assert max(positions[20:]) - min(positions[20:]) <= 3

    # Fast move: within 10 frames the cursor covers most of the jump
    for k in range(10):
        t += 1 / 30
        res = GestureResult(action="move_cursor", cursor_point=(0.7, 0.5), is_moving=True, timestamp=t)
        x = ctrl.apply(res, cfg)[0]
    target = ctrl.map_to_screen_absolute(0.7, 0.5, 0.15)[0]
    assert x > 960 + 0.8 * (target - 960)


# ------------------------------------------------------- paper rotation / tilt


def _paper_step(rotation: float, tilt: float, shift: Tuple[float, float]) -> Tuple[float, float]:
    engine, clock = GestureEngine(), Clock()
    engine.config["vertical_source"] = "hand"  # up/down from hand movement
    engine.config.update(paper_rotation_deg=rotation, paper_tilt_deg=tilt, paper_invert_x=False)
    run(engine, make_hand(), clock, frames=3)
    a = run(engine, make_hand("index"), clock)[0].paper_point
    b = run(engine, make_hand("index", shift=shift), clock)[0].paper_point
    return b[0] - a[0], b[1] - a[1]


def test_paper_tilt_stretches_forward_strokes_by_one_over_cos():
    _, flat = _paper_step(0.0, 0.0, (0.0, -0.04))
    _, tilted = _paper_step(0.0, 45.0, (0.0, -0.04))
    assert tilted == pytest.approx(flat / math.cos(math.radians(45)), rel=1e-6)
    # Sideways strokes are not stretched
    assert _paper_step(0.0, 45.0, (0.04, 0.0))[0] == pytest.approx(_paper_step(0.0, 0.0, (0.04, 0.0))[0])


def test_paper_rotation_turns_a_diagonal_stroke_into_a_straight_line():
    c = math.cos(math.radians(30))
    s_ = math.sin(math.radians(30))
    diagonal = (0.05 * c, 0.05 * s_)  # stroke 30 degrees off the image x axis
    du, dv = _paper_step(30.0, 0.0, diagonal)
    assert du > 0.15
    assert abs(dv) < 1e-6 * max(1.0, du)
    # Without the rotation the same stroke drifts diagonally
    assert abs(_paper_step(0.0, 0.0, diagonal)[1]) > 0.05


def test_paper_angle_adjustment_is_clamped():
    engine = GestureEngine()
    for _ in range(30):
        engine.adjust_paper_rotation(5)
        engine.adjust_paper_tilt(5)
    assert engine.config["paper_rotation_deg"] == 90.0
    assert engine.config["paper_tilt_deg"] == 75.0
    for _ in range(30):
        engine.adjust_paper_tilt(-5)
    assert engine.config["paper_tilt_deg"] == 0.0


# ------------------------------------------- calibration and finger-curl up/down

CURL_JOINTS = {"middle": (9, 10, 11, 12), "ring": (13, 14, 15, 16), "pinky": (17, 18, 19, 20)}


def curl_overrides(amount: float) -> Dict[int, Tuple[float, float]]:
    """Fold middle+ring+pinky toward the palm: 0 = open, 1 = curled into the palm."""
    out: Dict[int, Tuple[float, float]] = {}
    for mcp, pip, dip, tip in CURL_JOINTS.values():
        base = BASE_HAND[mcp]
        palm_spot = (base[0], base[1] + 0.06)  # just below the knuckle, inside the palm
        for idx, keep in ((pip, 0.6), (dip, 0.3), (tip, 0.0)):
            x, y = BASE_HAND[idx]
            tx = palm_spot[0] + (base[0] - palm_spot[0]) * keep
            ty = palm_spot[1] + (base[1] - palm_spot[1]) * keep
            out[idx] = (x + (tx - x) * amount, y + (ty - y) * amount)
    return out


def _sweep(engine, clock, ang: float, length: float, start: float, steps: int = 10) -> float:
    """One pen-down sweep along `ang` from `start` (signed distance along the axis); returns the end."""
    end = start
    for k in range(steps + 1):
        end = start + length * k / steps
        run(engine, make_hand("index", shift=(end * math.cos(ang), end * math.sin(ang))), clock)
    return end


def test_back_and_forth_calibration_uses_densest_bundle():
    engine, clock = GestureEngine(), Clock()
    engine.config["paper_invert_x"] = True  # calibration decides left/right itself
    engine.start_calibration(phases=("x",))
    run(engine, make_hand(), clock, frames=3)
    ang = math.radians(20)  # the user's "horizontal" goes 20 degrees down-right in the camera

    # A stray, nearly vertical stroke first (should be ignored)
    for k in range(12):
        run(engine, make_hand("index", shift=(0.0, -0.015 * k)), clock)
    run(engine, make_hand(shift=(0.0, -0.18)), clock)
    assert engine.calibrating

    # Back-and-forth sweeps, starting to the right, all within one pinch
    for _ in range(12):
        run(engine, make_hand("index", shift=(0.0, 0.0)), clock)
        x = 0.0
        for leg in range(6):
            x = _sweep(engine, clock, ang, 0.2 if leg % 2 == 0 else -0.2, x)
            if engine.calib_progress >= 1.0:
                break
        res = run(engine, make_hand(shift=(x * math.cos(ang), x * math.sin(ang))), clock)[0]
        if not engine.calibrating:
            break
    assert engine.calibrating is False
    assert engine.pop_calibration_done() is True
    assert engine.config["paper_x_angle_deg"] == pytest.approx(20.0, abs=2.0)
    assert engine.config["paper_invert_x"] is False

    # The same diagonal stroke now moves the cursor straight right
    run(engine, make_hand(), clock, frames=3)
    a = run(engine, make_hand("index"), clock)[0].paper_point
    b = run(engine, make_hand("index", shift=(0.05 * math.cos(ang), 0.05 * math.sin(ang))), clock)[0].paper_point
    assert b[0] - a[0] > 0.15
    assert abs(b[1] - a[1]) < 1e-6


def test_calibration_needs_enough_sweeping():
    engine, clock = GestureEngine(), Clock()
    engine.start_calibration(phases=("x",))
    run(engine, make_hand(), clock, frames=2)
    _sweep(engine, clock, 0.0, 0.15, 0.0)
    run(engine, make_hand(shift=(0.15, 0.0)), clock)
    assert engine.calibrating and engine.calib_state == "more"
    assert 0.0 < engine.calib_progress < 1.0
    assert engine.calib_estimate == pytest.approx(0.0, abs=0.05)


def test_calibration_first_sweep_left_flips_the_axis():
    engine, clock = GestureEngine(), Clock()
    engine.config["calib_target_length"] = 1.0
    engine.start_calibration(phases=("x",))
    run(engine, make_hand(), clock, frames=2)
    x = _sweep(engine, clock, 0.0, -0.3, 0.0)  # first move to the image left
    x = _sweep(engine, clock, 0.0, 0.3, x)
    run(engine, make_hand(shift=(x, 0.0)), clock)
    assert not engine.calibrating
    assert abs(engine.config["paper_x_angle_deg"]) == pytest.approx(180.0, abs=2.0)


def test_debug_dump_writes_csv(tmp_path: Path):
    engine, clock = GestureEngine(), Clock()
    run(engine, make_hand("ring"), clock, frames=3)
    path = engine.dump_debug(tmp_path / "logs" / "p.csv")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("t,d_index,d_middle,d_ring,d_pinky")
    assert len(lines) == 4


def test_ring_pinch_with_pinky_curling_along_still_right_clicks():
    """Pinky (no action) right next to the thumb must not block the ring."""
    engine = GestureEngine()
    d = {"index": 0.2, "middle": 0.12, "ring": 0.03, "pinky": 0.035}
    fired = [engine._update_pinch_state(d, 1.0 + k / 30) for k in range(3)]
    assert fired.count(True) == 1 and engine.active_finger == "ring"


def test_curling_three_fingers_moves_cursor_down_and_opening_moves_up():
    engine, clock = GestureEngine(), Clock()
    run(engine, make_hand(), clock, frames=3)
    a = run(engine, make_hand("index"), clock, frames=2)[-1].paper_point
    for k in range(1, 9):
        res = run(engine, make_hand("index", overrides=curl_overrides(k / 8)), clock)[0]
        assert res.action == "move_cursor"  # curling never turns into a click
    b = res.paper_point
    assert b[1] - a[1] > 0.1  # down
    assert abs(b[0] - a[0]) < 0.02  # hardly any sideways drift
    for k in range(7, -1, -1):
        res = run(engine, make_hand("index", overrides=curl_overrides(k / 8)), clock)[0]
    assert res.paper_point[1] < b[1] - 0.1  # back up


def test_curling_while_pen_up_does_not_move():
    engine, clock = GestureEngine(), Clock()
    run(engine, make_hand(), clock, frames=3)
    p0 = run(engine, make_hand(), clock)[0].paper_point
    for k in range(1, 9):
        res = run(engine, make_hand(overrides=curl_overrides(k / 8)), clock)[0]
    assert res.paper_point == pytest.approx(p0)


def test_pen_does_not_hand_over_to_click_after_takeover_window():
    engine = GestureEngine()
    engine._update_pinch_state(_dist(0.03, 0.2), 1.0)
    assert engine.is_pinched
    # 0.5 s later the middle comes near the thumb while curling: no click
    fired = [engine._update_pinch_state(_dist(0.06, 0.045), 1.5 + k / 30) for k in range(5)]
    assert not any(fired)
    assert engine.active_finger == "index"


def _curl_cycles(engine, clock, cycles: int, depth: float = 1.0, steps: int = 6) -> None:
    """Pen down, curl middle+ring+pinky in and out `cycles` times, pen up."""
    run(engine, make_hand("index"), clock, frames=2)
    for _ in range(cycles):
        for k in list(range(1, steps + 1)) + list(range(steps - 1, -1, -1)):
            run(engine, make_hand("index", overrides=curl_overrides(depth * k / steps)), clock)
    run(engine, make_hand(), clock)


CORNER_POSES = {"tl": (-25.0, 0.0), "tr": (25.0, 0.0), "br": (25.0, 1.0), "bl": (-25.0, 1.0)}


def _pose(turn: float, curl: float, pinch: bool = True, shift=(0.0, 0.0), scale: float = 1.0):
    """Hand turned by `turn` degrees (wrist turn), three fingers curled by `curl` (0..1)."""
    return make_hand("index" if pinch else None, angle_deg=turn, shift=shift, scale=scale,
                     overrides=curl_overrides(curl))


def _corner(engine, clock, name: str, frames: int = 25) -> None:
    """Hold the pinch in the pose for one corner, then release."""
    turn, curl = CORNER_POSES[name]
    run(engine, _pose(turn, curl), clock, frames=frames)
    run(engine, _pose(turn, curl, pinch=False), clock)


def _calibrate_corners(engine, clock) -> None:
    engine.start_calibration(("corners",))
    run(engine, make_hand(), clock, frames=2)
    for name in ("tl", "tr", "br", "bl"):
        _corner(engine, clock, name)


def test_corner_calibration_maps_hand_range_to_the_whole_monitor():
    engine, clock = GestureEngine(), Clock()
    engine.config["paper_invert_x"] = True  # the corners decide left/right themselves
    engine.start_calibration(("corners",))
    assert engine.calib_phase == "corners"
    run(engine, make_hand(), clock, frames=2)
    for k, name in enumerate(("tl", "tr", "br", "bl")):
        assert engine.corner_target[0] == name
        _corner(engine, clock, name)
        assert engine.calib_progress == pytest.approx((k + 1) / 4)
    assert not engine.calibrating and engine.pop_calibration_done()
    assert engine.config["movement_mode"] == "range"
    assert engine.range_ready
    assert engine.config["range_right_deg"] - engine.config["range_left_deg"] == pytest.approx(50.0, abs=3.0)

    def point(turn: float, curl: float, **kw):
        return run(engine, _pose(turn, curl, **kw), clock, frames=8)[-1].screen_point  # smoothed

    assert point(-25, 0.0) == pytest.approx((0.0, 0.0), abs=0.06)
    assert point(25, 1.0) == pytest.approx((1.0, 1.0), abs=0.06)
    mid = point(0, 0.5)
    assert mid[0] == pytest.approx(0.5, abs=0.05)
    assert 0.2 < mid[1] < 0.8
    assert point(-60, 0.0)[0] == 0.0  # turned past the range: stays on the edge


def test_range_mapping_follows_the_hand_skeleton_not_its_place_in_the_camera():
    engine, clock = GestureEngine(), Clock()
    _calibrate_corners(engine, clock)
    base = run(engine, _pose(10, 0.3), clock, frames=8)[-1].screen_point
    moved = run(engine, _pose(10, 0.3, shift=(0.15, 0.08)), clock, frames=8)[-1].screen_point
    farther = run(engine, _pose(10, 0.3, scale=0.7), clock, frames=8)[-1].screen_point
    assert moved == pytest.approx(base, abs=0.01)
    assert farther == pytest.approx(base, abs=0.02)
    # Curling the fingers does not change left/right
    curled = run(engine, _pose(10, 0.9), clock, frames=8)[-1].screen_point
    assert curled[0] == pytest.approx(base[0], abs=0.02)
    assert curled[1] > base[1] + 0.3


def test_corner_needs_a_short_hold():
    engine, clock = GestureEngine(), Clock()
    engine.start_calibration(("corners",))
    run(engine, make_hand(), clock, frames=2)
    _corner(engine, clock, "tl", frames=4)  # released too soon
    assert engine.calib_state == "short" and engine.corner_index == 0


def test_corner_calibration_restarts_when_range_is_too_small():
    engine, clock = GestureEngine(), Clock()
    engine.start_calibration(("corners",))
    run(engine, make_hand(), clock, frames=2)
    for name in ("tl", "tr", "br", "bl"):
        turn, curl = CORNER_POSES[name]
        run(engine, _pose(turn * 0.1, curl), clock, frames=25)
        run(engine, _pose(turn * 0.1, curl, pinch=False), clock)
    assert engine.calibrating and engine.calib_state == "narrow_x" and engine.corner_index == 0


def test_mouse_range_mode_follows_screen_point_and_falls_back_to_pen():
    ctrl = MouseController(dry_run=True, screen_size=(1001, 801))
    cfg = {"smoothing": 1.0, "movement_mode": "range"}
    res = GestureResult(action="move_cursor", is_moving=True, screen_point=(0.25, 0.75), paper_point=(0.0, 0.0))
    assert ctrl.apply(res, cfg) == (250, 600)
    # Not calibrated (no screen point): behaves like the pen (no jump on pen down)
    ctrl.apply(GestureResult(), cfg)
    pen = GestureResult(action="move_cursor", is_moving=True, paper_point=(5.0, 5.0))
    assert ctrl.apply(pen, cfg) == (250, 600)


def test_full_curl_moves_curl_gain_after_calibration():
    engine, clock = GestureEngine(), Clock()
    engine.config.update(curl_open=1.8, curl_closed=1.2, curl_gain=0.6)
    run(engine, make_hand(), clock, frames=3)
    run(engine, make_hand("index"), clock, frames=2)
    a = engine._paper[1]
    engine._advance_paper(0.0, 0.0, 0.0, curl_step=-0.6)  # one full curl in
    assert engine._paper[1] - a == pytest.approx(0.6)


def test_calibration_runs_direction_then_corners():
    engine, clock = GestureEngine(), Clock()
    engine.config["calib_target_length"] = 1.0
    engine.start_calibration(("x", "corners"))
    assert (engine.calib_phase, engine.calib_step_no, engine.calib_step_count) == ("x", 1, 2)
    run(engine, make_hand(), clock, frames=2)
    x = _sweep(engine, clock, 0.0, 0.3, 0.0)
    x = _sweep(engine, clock, 0.0, -0.3, x)
    run(engine, make_hand(shift=(x, 0.0)), clock)
    assert engine.calibrating and engine.calib_phase == "corners" and engine.calib_step_no == 2
    assert engine.pop_calibration_done() is False
    for name in ("tl", "tr", "br", "bl"):
        _corner(engine, clock, name)
    assert not engine.calibrating
    assert engine.pop_calibration_done() is True
    assert engine.config["paper_x_angle_deg"] is not None and engine.range_ready


def test_cancel_stops_all_steps():
    engine = GestureEngine()
    engine.start_calibration()
    engine.cancel_calibration()
    assert not engine.calibrating and engine.pop_calibration_done() is False


def test_corners_done_by_moving_the_hand_use_hand_position():
    """Left/right corners reached by moving the whole hand (no wrist turn)."""
    engine, clock = GestureEngine(), Clock()
    engine.config["paper_x_angle_deg"] = 0.0
    engine.start_calibration(("corners",))
    run(engine, make_hand(), clock, frames=2)
    for name, dx, curl in (("tl", -0.12, 0.0), ("tr", 0.12, 0.0), ("br", 0.12, 1.0), ("bl", -0.12, 1.0)):
        run(engine, _pose(0, curl, shift=(dx, 0.0)), clock, frames=25)
        run(engine, _pose(0, curl, pinch=False, shift=(dx, 0.0)), clock)
    assert not engine.calibrating
    assert engine.config["range_x_source"] == "move"
    left = run(engine, _pose(0, 0.0, shift=(-0.12, 0.0)), clock, frames=8)[-1].screen_point
    right = run(engine, _pose(0, 1.0, shift=(0.12, 0.0)), clock, frames=8)[-1].screen_point
    assert left == pytest.approx((0.0, 0.0), abs=0.06)
    assert right == pytest.approx((1.0, 1.0), abs=0.06)


def test_narrow_corners_after_sweep_use_the_sweep_range_instead_of_looping():
    engine, clock = GestureEngine(), Clock()
    engine.config["calib_target_length"] = 1.0
    engine.start_calibration()  # default: step 1 sweep, then corners
    assert engine.calib_phase == "x"
    run(engine, make_hand(), clock, frames=2)
    x = _sweep(engine, clock, 0.0, 0.15, 0.0)
    x = _sweep(engine, clock, 0.0, -0.3, x)
    x = _sweep(engine, clock, 0.0, 0.3, x)
    run(engine, make_hand(shift=(x, 0.0)), clock)
    assert engine.calib_phase == "corners"
    for name in ("tl", "tr", "br", "bl"):  # left/right corners hardly differ
        _, curl = CORNER_POSES[name]
        run(engine, _pose(0, curl), clock, frames=25)
        run(engine, _pose(0, curl, pinch=False), clock)
    assert not engine.calibrating and engine.pop_calibration_done()
    assert engine.config["range_x_source"] == "move"
    assert engine.config["range_right_pos"] - engine.config["range_left_pos"] > 0.8


# ------------------------------------------------------------------ thumb mode

THUMB_SPOTS = {"tl": (0.38, 0.46), "tr": (0.50, 0.46), "br": (0.50, 0.58), "bl": (0.38, 0.58)}


def _thumb_hand(pos: Tuple[float, float], **kw) -> List[Point3D]:
    return make_hand(overrides={4: pos}, **kw)


def _thumb_engine() -> Tuple[GestureEngine, Clock]:
    engine, clock = GestureEngine(), Clock()
    engine.config["movement_mode"] = "thumb"
    return engine, clock


def _calibrate_thumb(engine, clock) -> None:
    engine.start_calibration(("thumb",))
    for name in ("tl", "tr", "br", "bl"):
        run(engine, _thumb_hand(THUMB_SPOTS[name]), clock, frames=30)


def test_thumb_point_is_measured_inside_the_hand():
    engine, clock = _thumb_engine()
    base = run(engine, _thumb_hand((0.42, 0.50)), clock, frames=6)[-1].thumb_point
    moved = run(engine, _thumb_hand((0.42, 0.50), shift=(0.15, 0.1)), clock, frames=6)[-1].thumb_point
    turned = run(engine, _thumb_hand((0.42, 0.50), angle_deg=35), clock, frames=6)[-1].thumb_point
    farther = run(engine, _thumb_hand((0.42, 0.50), scale=0.6), clock, frames=6)[-1].thumb_point
    for other in (moved, turned, farther):
        assert other == pytest.approx(base, abs=0.01)


def test_thumb_calibration_maps_thumb_spots_to_monitor_corners():
    engine, clock = _thumb_engine()
    _calibrate_thumb(engine, clock)
    assert not engine.calibrating and engine.pop_calibration_done()
    assert engine.thumb_ready and engine.config["movement_mode"] == "thumb"

    def screen(pos, **kw):
        return run(engine, _thumb_hand(pos, **kw), clock, frames=6)[-1].screen_point

    assert screen(THUMB_SPOTS["tl"]) == pytest.approx((0.0, 0.0), abs=0.05)
    assert screen(THUMB_SPOTS["br"]) == pytest.approx((1.0, 1.0), abs=0.05)
    assert screen((0.44, 0.52)) == pytest.approx((0.5, 0.5), abs=0.05)
    # Moving the whole hand keeps the thumb's screen point
    assert screen((0.44, 0.52), shift=(0.1, -0.05)) == pytest.approx((0.5, 0.5), abs=0.05)


def test_thumb_corner_needs_the_thumb_to_move_on_before_the_next_corner():
    engine, clock = _thumb_engine()
    engine.start_calibration(("thumb",))
    run(engine, _thumb_hand(THUMB_SPOTS["tl"]), clock, frames=60)  # stays put
    assert engine.corner_index == 1 and engine.calib_state == "move_on"


def test_thumb_calibration_rejects_corners_on_one_spot():
    engine, clock = _thumb_engine()
    engine.start_calibration(("thumb",))
    for k in range(4):
        run(engine, _thumb_hand((0.44 + 0.013 * (k % 2), 0.52)), clock, frames=30)
    assert engine.calibrating


def test_thumb_on_index_is_not_a_pinch_and_cursor_keeps_moving():
    engine, clock = _thumb_engine()
    _calibrate_thumb(engine, clock)
    res = run(engine, _thumb_hand((0.44, 0.315)), clock, frames=4)[-1]
    assert res.action == "move_cursor" and res.is_moving
    assert engine.active_finger is None


FIST_JOINTS = {"index": (5, 6, 7, 8), "middle": (9, 10, 11, 12), "ring": (13, 14, 15, 16), "pinky": (17, 18, 19, 20)}


def curl_these(amounts: Dict[str, float]) -> Dict[int, Tuple[float, float]]:
    """Fold the named fingers toward the palm (0 = straight, 1 = curled in)."""
    out: Dict[int, Tuple[float, float]] = {}
    for name, amount in amounts.items():
        mcp, pip, dip, tip = FIST_JOINTS[name]
        base = BASE_HAND[mcp]
        palm_spot = (base[0], base[1] + 0.06)
        for idx, keep in ((pip, 0.6), (dip, 0.3), (tip, 0.0)):
            x, y = BASE_HAND[idx]
            tx = palm_spot[0] + (base[0] - palm_spot[0]) * keep
            ty = palm_spot[1] + (base[1] - palm_spot[1]) * keep
            out[idx] = (x + (tx - x) * amount, y + (ty - y) * amount)
    return out


def _fist_hand(thumb: Tuple[float, float], index: float = 1.0, middle: float = 1.0) -> List[Point3D]:
    """Loose fist (ring/pinky curled) with the thumb at `thumb`; index/middle curl amounts."""
    overrides = curl_these({"index": index, "middle": middle, "ring": 1.0, "pinky": 1.0})
    overrides[4] = thumb
    return make_hand(overrides=overrides)


def test_index_out_left_clicks_and_index_middle_out_right_clicks():
    engine, clock = _thumb_engine()
    _calibrate_thumb(engine, clock)
    rest = (0.44, 0.52)
    run(engine, _fist_hand(rest), clock, frames=4)  # neutral fist arms the clicks
    res = run(engine, _fist_hand(rest, index=0.0), clock, frames=8)
    assert [r.action for r in res].count("left_click") == 1
    run(engine, _fist_hand(rest), clock, frames=4)
    res = run(engine, _fist_hand(rest, index=0.0, middle=0.0), clock, frames=8)
    assert [r.action for r in res].count("right_click") == 1
    assert "left_click" not in [r.action for r in res]


def test_right_click_with_index_slightly_first_does_not_left_click():
    engine, clock = _thumb_engine()
    _calibrate_thumb(engine, clock)
    rest = (0.44, 0.52)
    run(engine, _fist_hand(rest), clock, frames=4)
    actions = [r.action for r in run(engine, _fist_hand(rest, index=0.0), clock, frames=2)]  # < 0.15 s
    actions += [r.action for r in run(engine, _fist_hand(rest, index=0.0, middle=0.0), clock, frames=8)]
    assert actions.count("right_click") == 1 and "left_click" not in actions


def test_extension_click_needs_a_curl_before_the_next_one():
    engine, clock = _thumb_engine()
    _calibrate_thumb(engine, clock)
    rest = (0.44, 0.52)
    # Open hand from the start: nothing fires until the fingers have been curled once
    assert all(r.action != "left_click" for r in run(engine, _fist_hand(rest, index=0.0, middle=0.0), clock, frames=10))
    run(engine, _fist_hand(rest), clock, frames=4)
    held = [r.action for r in run(engine, _fist_hand(rest, index=0.0), clock, frames=30)]
    assert held.count("left_click") == 1
    # index+middle -> index only without curling: no new click
    more = [r.action for r in run(engine, _fist_hand(rest, index=0.0, middle=0.0), clock, frames=10)]
    assert "right_click" not in more


def test_thumb_pinch_on_middle_does_not_click_in_thumb_mode():
    engine, clock = _thumb_engine()
    _calibrate_thumb(engine, clock)
    res = run(engine, _thumb_hand((0.50, 0.285)), clock, frames=6)
    assert all(r.action in ("move_cursor", "none") for r in res)


def test_thumb_click_holds_cursor_where_it_was_before_reaching_for_the_finger():
    engine, clock = _thumb_engine()
    _calibrate_thumb(engine, clock)
    ctrl = MouseController(dry_run=True, screen_size=(1000, 800))
    cfg = dict(engine.config, smoothing=1.0)
    rest = (0.44, 0.52)
    for res in run(engine, _fist_hand(rest), clock, frames=10):
        ctrl.apply(res, cfg)
    aimed = ctrl.last_screen_pos
    actions, holds = [], []
    for k in range(1, 11):
        # The thumb drifts a little while the index straightens
        drift = (rest[0] + 0.004 * k, rest[1] - 0.003 * k)
        res = engine.process(_fist_hand(drift, index=max(0.0, 1.0 - k / 3)), timestamp=clock())
        ctrl.apply(res, cfg)
        actions.append(res.action)
        holds.append(res.hold_point)
    assert actions.count("left_click") == 1
    assert any(h is not None for h in holds)
    assert ctrl.event_log.count("left_click") == 1
    assert abs(ctrl.last_screen_pos[0] - aimed[0]) <= 25 and abs(ctrl.last_screen_pos[1] - aimed[1]) <= 25



# --------------------------------------------- landmark smoothing / still lock / jitter


def test_landmark_filter_steadies_a_still_hand_but_follows_a_move():
    engine, clock = GestureEngine(), Clock()
    engine.config["landmark_filter"] = True
    xs = []
    for k in range(40):  # still hand with +/- 0.004 camera jitter
        j = 0.004 if k % 2 else -0.004
        run(engine, make_hand("index", shift=(j, j)), clock)
        xs.append(engine.last_pen_image[0])
    assert max(xs[10:]) - min(xs[10:]) < 0.004  # well under the raw 0.008 swing
    for _ in range(10):  # then a real move of 0.1
        run(engine, make_hand("index", shift=(0.1, 0.0)), clock)
    assert engine.last_pen_image[0] - xs[-1] > 0.08


def test_still_lock_holds_cursor_and_lets_go_on_a_clear_move():
    ctrl = MouseController(dry_run=True, screen_size=(1920, 1080))
    cfg = {"smoothing": 1.0, "movement_mode": "relative", "pen_speed": 1.0, "still_lock": True}
    t, u = 10.0, 0.0
    ctrl.apply(_pen((u, 0.0), t), cfg)
    for k in range(12):  # nearly still: tiny drift 0.001 palm per frame
        t += 1 / 30
        u += 0.001 * (1 if k % 2 else -1) + 0.0005
        ctrl.apply(_pen((u, 0.0), t), cfg)
    assert ctrl.locked
    held = ctrl.last_screen_pos
    for _ in range(3):
        t += 1 / 30
        u += 0.004
        ctrl.apply(_pen((u, 0.0), t), cfg)
    assert ctrl.last_screen_pos == held  # small wobble while locked: no move
    for _ in range(4):
        t += 1 / 30
        u += 0.03
        ctrl.apply(_pen((u, 0.0), t), cfg)
    assert not ctrl.locked and ctrl.last_screen_pos[0] > held[0] + 30


def test_jitter_meter_reports_shake_while_still():
    ctrl = MouseController(dry_run=True, screen_size=(1920, 1080))
    cfg = {"smoothing": 1.0, "movement_mode": "relative", "pen_speed": 1.0}
    t = 10.0
    ctrl.apply(_pen((0.0, 0.0), t), cfg)
    for k in range(20):
        t += 1 / 30
        ctrl.apply(_pen((0.003 * (1 if k % 2 else -1), 0.0), t), cfg)
    assert ctrl.jitter_raw_px > 2.0


def test_hand_forward_back_moves_cursor_up_down_by_default():
    engine, clock = GestureEngine(), Clock()
    engine.config["vertical_source"] = "hand"
    engine.config["paper_x_angle_deg"] = 0.0
    run(engine, make_hand(), clock, frames=3)
    a = run(engine, make_hand("index"), clock)[0].paper_point
    b = run(engine, make_hand("index", shift=(0.0, -0.04)), clock)[0].paper_point  # away = up
    assert b[1] < a[1] and abs(b[0] - a[0]) < 1e-6
    # Curling the three fingers no longer moves up/down
    c = run(engine, make_hand("index", shift=(0.0, -0.04), overrides=curl_overrides(1.0)), clock)[0].paper_point
    assert c[1] == pytest.approx(b[1])


def test_hand_vertical_lets_click_finger_take_over_from_a_resting_pen():
    """Up/down from hand movement: the thumb may rest on the index a while, then a
    clearly closer middle (left) or ring (right) still clicks."""
    engine = GestureEngine()
    engine.config["vertical_source"] = "hand"
    engine._update_pinch_state(_dist(0.03, 0.2), 1.0)
    assert engine.is_pinched
    fired = [engine._update_pinch_state(_dist(0.06, 0.045), 1.5 + k / 30) for k in range(5)]
    assert fired.count(True) == 1
    assert engine.active_finger == "middle"
    engine._update_pinch_state(_dist(0.2, 0.2), 3.0)
    engine._update_pinch_state(_dist(0.03, 0.2), 4.0)
    fired = [engine._update_pinch_state(_dist(0.06, 0.2, ring=0.045), 4.6 + k / 30) for k in range(5)]
    assert fired.count(True) == 1
    assert engine.active_finger == "ring"


def test_flip_x_reverses_left_right_and_survives_calibration():
    engine = GestureEngine()
    engine.config["paper_x_angle_deg"] = 0.0
    engine.config["paper_invert_x"] = False
    engine._paper = (0.0, 0.0)
    engine._advance_paper(0.05, 0.0)
    normal = engine._paper[0]
    engine.config["flip_x"] = True
    engine._paper = (0.0, 0.0)
    engine._advance_paper(0.05, 0.0)
    assert normal > 0 and engine._paper[0] == pytest.approx(-normal)
    engine.calib_estimate = 0.0
    engine._calib_points_all = []
    engine._finish_calibration()
    assert engine.config["flip_x"] is True


def test_pen_follows_palm_centre_not_the_thumb():
    """Moving only the thumb (still pinched) does not move the pen."""
    engine = GestureEngine()
    clock = Clock()
    run(engine, make_hand("index", gap=0.002), clock, frames=3)
    before = engine._paper
    run(engine, make_hand("index", gap=0.02), clock, frames=3)
    assert engine.is_pinched
    assert engine._paper == pytest.approx(before, abs=1e-6)


def test_precision_mode_after_stop_then_leaves_on_a_fast_move():
    ctrl = MouseController(dry_run=True, screen_size=(1920, 1080))
    cfg = {"smoothing": 1.0, "movement_mode": "relative", "pen_speed": 1.0, "still_lock": True,
           "precision_mode": True, "precision_gain": 0.2}
    t, u = 10.0, 0.0
    ctrl.apply(_pen((u, 0.0), t), cfg)
    for _ in range(10):  # stop over a target
        t += 1 / 30
        ctrl.apply(_pen((u, 0.0), t), cfg)
    assert ctrl.locked and ctrl.precise
    start = ctrl.last_screen_pos
    for _ in range(10):  # leave the lock, then move slowly: 0.2x
        t += 1 / 30
        u += 0.01
        ctrl.apply(_pen((u, 0.0), t), cfg)
    assert ctrl.precise
    slow = ctrl.last_screen_pos[0] - start[0]
    assert 0 < slow <= 0.2 * 1920 * 0.1 + 2
    for _ in range(4):  # fast move: back to normal speed
        t += 1 / 30
        u += 0.08
        ctrl.apply(_pen((u, 0.0), t), cfg)
    assert not ctrl.precise


def test_click_freeze_puts_cursor_back_and_holds_it_during_the_click():
    ctrl = MouseController(dry_run=True, screen_size=(1920, 1080))
    cfg = {"smoothing": 1.0, "movement_mode": "relative", "pen_speed": 1.0, "click_freeze": True,
           "click_freeze_lookback_s": 0.25, "click_release_hold_s": 0.35}
    t, u = 10.0, 0.0
    trail = []
    for _ in range(20):
        t += 1 / 30
        u += 0.02
        trail.append((t, ctrl.apply(_pen((u, 0.0), t), cfg)))
    aimed = [p for tt, p in trail if tt <= t + 1 / 30 - 0.25][-1]  # 0.25 s before the click starts
    for k in range(5):  # thumb slides to the middle finger; the hand drifts on
        t += 1 / 30
        u += 0.02
        res = _pen((u, 0.0), t)
        res.click_forming = True
        if k == 3:
            res.action = "left_click"
        assert ctrl.apply(res, cfg) == aimed
    assert ctrl.event_log == ["left_click"]
    for _ in range(5):  # let go: still held a moment, then moves again from there
        t += 1 / 30
        u += 0.02
        pos = ctrl.apply(_pen((u, 0.0), t), cfg)
    assert pos == aimed
    for _ in range(10):
        t += 1 / 30
        u += 0.02
        pos = ctrl.apply(_pen((u, 0.0), t), cfg)
    assert pos[0] > aimed[0] + 50
