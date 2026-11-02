"""
Unit tests for GestureEngine and MouseController (`dry_run=True`).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from src.gesture_engine import GestureEngine, GestureResult, Point3D
from src.mouse_controller import MouseController


def make_hand(
    thumb: tuple[float, float] = (0.50, 0.50),
    index: tuple[float, float] = (0.65, 0.50),
    middle: tuple[float, float] = (0.70, 0.50),
    ring: tuple[float, float] = (0.75, 0.50),
    pinky: tuple[float, float] = (0.80, 0.50),
) -> List[Point3D]:
    """Create 21 normalized hand landmarks with configurable fingertip positions."""
    pts = [Point3D(0.5, 0.7, 0.0) for _ in range(21)]
    pts[4] = Point3D(thumb[0], thumb[1], 0.0)
    pts[8] = Point3D(index[0], index[1], 0.0)
    pts[12] = Point3D(middle[0], middle[1], 0.0)
    pts[16] = Point3D(ring[0], ring[1], 0.0)
    pts[20] = Point3D(pinky[0], pinky[1], 0.0)
    return pts


def test_config_file_has_required_fields():
    cfg_path = PROJECT_ROOT / "config" / "gestures.json"
    assert cfg_path.exists()
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert data["pinch_threshold"] == pytest.approx(0.055)
    assert data["release_threshold"] == pytest.approx(0.075)
    assert data["click_threshold"] == pytest.approx(0.052)
    assert data["smoothing"] == pytest.approx(0.35)
    assert data["active_margin"] == pytest.approx(0.15)
    assert data["movement_mode"] == "absolute"
    assert data["relative_sensitivity"] == pytest.approx(2.2)

    gestures = data["gestures"]
    assert gestures["thumb_index_pinch"]["action"] == "move_cursor"
    assert gestures["thumb_middle_pinch"]["action"] == "left_click"
    assert gestures["thumb_ring_pinch"]["action"] == "right_click"
    assert gestures["thumb_index_middle_pinch"]["action"] == "drag_hold"
    assert gestures["thumb_pinky_pinch"]["action"] == "drag_toggle"


def test_thumb_index_pinch_hysteresis():
    engine = GestureEngine()

    # Open hand: distance 0.15 > pinch_threshold (0.055) -> NONE
    res0 = engine.process(make_hand(thumb=(0.50, 0.50), index=(0.65, 0.50)), timestamp=1.0)
    assert res0.active_gesture == "NONE"
    assert res0.action == "none"
    assert res0.is_moving is False

    # Enter pinch: distance 0.03 <= 0.055 -> move_cursor
    res1 = engine.process(make_hand(thumb=(0.50, 0.50), index=(0.53, 0.50)), timestamp=1.1)
    assert res1.active_gesture == "thumb_index_pinch"
    assert res1.action == "move_cursor"
    assert res1.is_moving is True
    assert res1.cursor_point == pytest.approx((0.515, 0.50))

    # Hysteresis zone: distance 0.068 is > pinch_threshold (0.055) but <= release_threshold (0.075)
    # Must remain locked in move_cursor state!
    res2 = engine.process(make_hand(thumb=(0.50, 0.50), index=(0.568, 0.50)), timestamp=1.2)
    assert res2.active_gesture == "thumb_index_pinch"
    assert res2.action == "move_cursor"
    assert res2.is_moving is True

    # Release: distance 0.09 > release_threshold (0.075) -> exits pinch
    res3 = engine.process(make_hand(thumb=(0.50, 0.50), index=(0.59, 0.50)), timestamp=1.3)
    assert res3.active_gesture == "NONE"
    assert res3.action == "none"
    assert res3.is_moving is False


def test_drag_hold_priority_and_click_cooldowns():
    engine = GestureEngine()

    # Thumb + Index + Middle all pinched -> drag_hold takes priority over move_cursor
    res_drag = engine.process(
        make_hand(thumb=(0.50, 0.50), index=(0.52, 0.50), middle=(0.52, 0.51)),
        timestamp=2.0,
    )
    assert res_drag.active_gesture == "thumb_index_middle_pinch"
    assert res_drag.action == "drag_hold"
    assert res_drag.is_moving is True

    # Release index and middle, then pinch thumb + middle only -> left_click with cooldown
    engine.process(make_hand(thumb=(0.50, 0.50), index=(0.70, 0.50), middle=(0.70, 0.50)), timestamp=2.5)
    click1 = engine.process(
        make_hand(thumb=(0.50, 0.50), index=(0.70, 0.50), middle=(0.52, 0.50)),
        timestamp=3.0,
    )
    assert click1.active_gesture == "thumb_middle_pinch"
    assert click1.action == "left_click"
    assert click1.is_moving is False

    # Immediate next frame within 0.35s cooldown -> debounced to NONE
    click_debounced = engine.process(
        make_hand(thumb=(0.50, 0.50), index=(0.70, 0.50), middle=(0.52, 0.50)),
        timestamp=3.1,
    )
    assert click_debounced.action == "none"

    # After cooldown (3.0 + 0.40 = 3.40s) -> fires again
    click2 = engine.process(
        make_hand(thumb=(0.50, 0.50), index=(0.70, 0.50), middle=(0.52, 0.50)),
        timestamp=3.40,
    )
    assert click2.action == "left_click"


def test_right_click_and_drag_toggle_and_customization(tmp_path: Path):
    cfg_file = tmp_path / "custom_gestures.json"
    engine = GestureEngine(config_path=cfg_file)

    # Right click via thumb + ring pinch
    rc = engine.process(
        make_hand(thumb=(0.50, 0.50), index=(0.70, 0.50), ring=(0.52, 0.50)),
        timestamp=5.0,
    )
    assert rc.active_gesture == "thumb_ring_pinch"
    assert rc.action == "right_click"

    # Drag toggle via thumb + pinky pinch
    dt = engine.process(
        make_hand(thumb=(0.50, 0.50), index=(0.70, 0.50), pinky=(0.52, 0.50)),
        timestamp=6.0,
    )
    assert dt.active_gesture == "thumb_pinky_pinch"
    assert dt.action == "drag_toggle"

    # Customize gesture mapping & movement mode and persist
    engine.set_gesture_action("thumb_ring_pinch", "left_click", enabled=True)
    engine.set_movement_mode("relative")
    engine.save_config()

    reloaded = GestureEngine(config_path=cfg_file)
    assert reloaded.config["movement_mode"] == "relative"
    assert reloaded.config["gestures"]["thumb_ring_pinch"]["action"] == "left_click"


def test_mouse_controller_absolute_and_relative_and_drag_safety():
    ctrl = MouseController(dry_run=True, screen_size=(1920, 1080))
    cfg = {
        "smoothing": 1.0,  # full step for exact deterministic assertion
        "active_margin": 0.15,
        "movement_mode": "absolute",
        "relative_sensitivity": 2.0,
    }

    # Center of frame (0.5, 0.5) -> center of screen (~960, ~540)
    move_res = GestureResult(
        active_gesture="thumb_index_pinch",
        action="move_cursor",
        cursor_point=(0.5, 0.5),
        pinch_distance=0.02,
        distances={"index": 0.02},
        is_moving=True,
    )
    pos = ctrl.apply(move_res, cfg)
    assert abs(pos[0] - 960) <= 1
    assert abs(pos[1] - 540) <= 1

    # Drag hold engages mouseDown and releases automatically when gesture changes
    drag_res = GestureResult(
        active_gesture="thumb_index_middle_pinch",
        action="drag_hold",
        cursor_point=(0.6, 0.6),
        pinch_distance=0.02,
        distances={"index": 0.02, "middle": 0.02},
        is_moving=True,
    )
    ctrl.apply(drag_res, cfg)
    assert ctrl.is_dragging is True

    # Switching back to move_cursor releases drag_hold automatically
    ctrl.apply(move_res, cfg)
    assert ctrl.is_dragging is False

    # Relative mode: clutching behavior
    cfg["movement_mode"] = "relative"
    ctrl.apply(
        GestureResult(active_gesture="NONE", action="none", cursor_point=None, is_moving=False),
        cfg,
    )
    assert ctrl.anchor_hand_pos is None

    # First pinch sets anchor at current screen pos
    start_pos = ctrl.last_screen_pos
    ctrl.apply(
        GestureResult(
            active_gesture="thumb_index_pinch",
            action="move_cursor",
            cursor_point=(0.30, 0.30),
            pinch_distance=0.02,
            is_moving=True,
        ),
        cfg,
    )
    assert ctrl.anchor_hand_pos == pytest.approx((0.30, 0.30))
    assert ctrl.last_screen_pos == start_pos

    # Moving hand +0.05 right while pinched moves cursor positively
    new_pos = ctrl.apply(
        GestureResult(
            active_gesture="thumb_index_pinch",
            action="move_cursor",
            cursor_point=(0.35, 0.30),
            pinch_distance=0.02,
            is_moving=True,
        ),
        cfg,
    )
    assert new_pos[0] > start_pos[0]

    # Drag toggle + release_all safety check
    ctrl.apply(
        GestureResult(
            active_gesture="thumb_pinky_pinch",
            action="drag_toggle",
            cursor_point=(0.35, 0.30),
            is_moving=False,
        ),
        cfg,
    )
    assert ctrl.is_dragging is True
    ctrl.release_all()
    assert ctrl.is_dragging is False
    assert ctrl.anchor_hand_pos is None
