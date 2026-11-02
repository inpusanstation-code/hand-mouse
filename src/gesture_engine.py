"""
Gesture recognition engine and customizable configuration for Hand-Mouse.

Translates 21 MediaPipe hand landmarks into cursor movement and mouse actions:
- Thumb (#4) + Index (#8) pinch (with hysteresis): cursor movement
- Thumb (#4) + Index (#8) + Middle (#12) pinch: drag hold
- Thumb (#4) + Middle (#12) pinch: left click (with cooldown)
- Thumb (#4) + Ring (#16) pinch: right click (with cooldown)
- Thumb (#4) + Pinky (#20) pinch: drag toggle (with cooldown)
"""

from __future__ import annotations

import copy
import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "gestures.json"

VALID_ACTIONS = {
    "none",
    "move_cursor",
    "left_click",
    "right_click",
    "drag_hold",
    "drag_toggle",
}

VALID_MOVEMENT_MODES = {"absolute", "relative"}

DEFAULT_CONFIG: Dict[str, Any] = {
    "pinch_threshold": 0.055,
    "release_threshold": 0.075,
    "click_threshold": 0.052,
    "smoothing": 0.35,
    "active_margin": 0.15,
    "movement_mode": "absolute",
    "relative_sensitivity": 2.2,
    "gestures": {
        "thumb_index_pinch": {
            "action": "move_cursor",
            "enabled": True,
            "description": "엄지+검지 붙임: 마우스 커서 이동",
        },
        "thumb_middle_pinch": {
            "action": "left_click",
            "enabled": True,
            "cooldown": 0.35,
            "description": "엄지+중지 붙임: 좌클릭",
        },
        "thumb_ring_pinch": {
            "action": "right_click",
            "enabled": True,
            "cooldown": 0.45,
            "description": "엄지+약지 붙임: 우클릭",
        },
        "thumb_index_middle_pinch": {
            "action": "drag_hold",
            "enabled": True,
            "description": "엄지+검지+중지 함께 붙임: 드래그(누른 상태 유지)",
        },
        "thumb_pinky_pinch": {
            "action": "drag_toggle",
            "enabled": True,
            "cooldown": 0.6,
            "description": "엄지+약지/소지 붙임: 드래그 토글",
        },
    },
}


@dataclass
class Point3D:
    """Normalized 3D landmark point."""

    x: float
    y: float
    z: float = 0.0

    @classmethod
    def from_any(cls, item: Any) -> "Point3D":
        """Convert a MediaPipe landmark, object with .x/.y, tuple, or dict into Point3D."""
        if isinstance(item, Point3D):
            return item
        if hasattr(item, "x") and hasattr(item, "y"):
            return cls(
                x=float(item.x),
                y=float(item.y),
                z=float(getattr(item, "z", 0.0)),
            )
        if isinstance(item, dict):
            return cls(
                x=float(item["x"]),
                y=float(item["y"]),
                z=float(item.get("z", 0.0)),
            )
        if isinstance(item, (tuple, list)):
            return cls(
                x=float(item[0]),
                y=float(item[1]),
                z=float(item[2]) if len(item) > 2 else 0.0,
            )
        raise TypeError(f"Unsupported landmark type: {type(item)!r}")

    @classmethod
    def from_landmark(cls, landmark: Any) -> "Point3D":
        return cls.from_any(landmark)

    @classmethod
    def from_tuple(cls, coords: Sequence[float]) -> "Point3D":
        return cls.from_any(coords)


@dataclass
class GestureResult:
    """Output of a single frame's gesture evaluation."""

    active_gesture: str = "NONE"
    action: str = "none"
    cursor_point: Optional[Tuple[float, float]] = None
    pinch_distance: float = 1.0
    distances: Dict[str, float] = field(default_factory=dict)
    is_moving: bool = False


class GestureEngine:
    """
    Processes 21 hand landmarks to detect pinch gestures with hysteresis
    and customizable gesture-to-action mappings.
    """

    THUMB_TIP = 4
    INDEX_TIP = 8
    MIDDLE_TIP = 12
    RING_TIP = 16
    PINKY_TIP = 20

    def __init__(self, config_path: Optional[str | Path] = None) -> None:
        if config_path is None:
            self.config_path = DEFAULT_CONFIG_PATH
        else:
            candidate = Path(config_path)
            if not candidate.is_absolute() and not candidate.exists():
                alt = DEFAULT_CONFIG_PATH.parent.parent / candidate
                self.config_path = alt if alt.exists() else candidate
            else:
                self.config_path = candidate

        self.config: Dict[str, Any] = self.load_config(self.config_path)
        self._index_pinched: bool = False
        self._middle_hold_pinched: bool = False
        self._last_trigger_times: Dict[str, float] = {}

    @property
    def is_pinched(self) -> bool:
        """Whether the primary thumb+index pinch state is currently locked."""
        return self._index_pinched

    def load_config(self, path: Optional[str | Path] = None) -> Dict[str, Any]:
        """Load configuration from JSON file and merge with defaults."""
        target = Path(path) if path is not None else self.config_path
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        if target.exists():
            try:
                with open(target, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                self._deep_merge(cfg, loaded)
            except (OSError, json.JSONDecodeError):
                pass
        self.config = cfg
        return cfg

    def save_config(self, path: Optional[str | Path] = None) -> Path:
        """Persist current configuration to `config/gestures.json` (or custom path)."""
        target = Path(path) if path is not None else self.config_path
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)
        return target

    @staticmethod
    def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> None:
        for k, v in override.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                GestureEngine._deep_merge(base[k], v)
            else:
                base[k] = copy.deepcopy(v)

    def set_gesture_action(
        self,
        gesture_id: str,
        action: str,
        enabled: bool = True,
    ) -> None:
        """Customize the action mapped to a gesture ID."""
        if action not in VALID_ACTIONS:
            raise ValueError(f"Unsupported action '{action}'. Must be one of {sorted(VALID_ACTIONS)}")
        gestures = self.config.setdefault("gestures", {})
        if gesture_id not in gestures:
            gestures[gesture_id] = {
                "action": action,
                "enabled": bool(enabled),
                "description": f"사용자 지정 제스처 ({gesture_id})",
            }
        else:
            gestures[gesture_id]["action"] = action
            gestures[gesture_id]["enabled"] = bool(enabled)

    def set_movement_mode(self, mode: str) -> None:
        """Switch cursor movement mode between 'absolute' and 'relative'."""
        mode_norm = mode.strip().lower()
        if mode_norm not in VALID_MOVEMENT_MODES:
            raise ValueError(f"Invalid movement_mode '{mode}'. Choose from {sorted(VALID_MOVEMENT_MODES)}")
        self.config["movement_mode"] = mode_norm

    def reset(self) -> None:
        """Reset hysteresis and cooldown states (e.g., when hand leaves frame)."""
        self._index_pinched = False
        self._middle_hold_pinched = False

    @staticmethod
    def _dist_2d(a: Point3D, b: Point3D) -> float:
        return math.hypot(a.x - b.x, a.y - b.y)

    def _gesture_cfg(self, gesture_id: str) -> Dict[str, Any]:
        return self.config.get("gestures", {}).get(gesture_id, {})

    def _is_enabled(self, gesture_id: str) -> bool:
        cfg = self._gesture_cfg(gesture_id)
        return bool(cfg.get("enabled", False)) and cfg.get("action", "none") != "none"

    def _can_trigger(self, gesture_id: str, now: float) -> bool:
        cfg = self._gesture_cfg(gesture_id)
        cooldown = float(cfg.get("cooldown", 0.35))
        last_time = self._last_trigger_times.get(gesture_id, -1e9)
        if (now - last_time) >= cooldown:
            self._last_trigger_times[gesture_id] = now
            return True
        return False

    def process(
        self,
        landmarks: Optional[Sequence[Any]],
        timestamp: Optional[float] = None,
    ) -> GestureResult:
        """
        Evaluate a sequence of 21 hand landmarks and return GestureResult.
        """
        if not landmarks or len(landmarks) < 21:
            self.reset()
            return GestureResult(
                active_gesture="NONE",
                action="none",
                cursor_point=None,
                pinch_distance=1.0,
                distances={},
                is_moving=False,
            )

        now = float(timestamp) if timestamp is not None else time.perf_counter()

        pts = [Point3D.from_any(lm) for lm in landmarks[:21]]
        thumb = pts[self.THUMB_TIP]
        index = pts[self.INDEX_TIP]
        middle = pts[self.MIDDLE_TIP]
        ring = pts[self.RING_TIP]
        pinky = pts[self.PINKY_TIP]

        d_index = self._dist_2d(thumb, index)
        d_middle = self._dist_2d(thumb, middle)
        d_ring = self._dist_2d(thumb, ring)
        d_pinky = self._dist_2d(thumb, pinky)

        distances = {
            "index": d_index,
            "middle": d_middle,
            "ring": d_ring,
            "pinky": d_pinky,
        }

        pinch_threshold = float(self.config.get("pinch_threshold", 0.055))
        release_threshold = float(self.config.get("release_threshold", 0.075))
        click_threshold = float(self.config.get("click_threshold", 0.052))

        # Hysteresis for primary thumb + index pinch (#4 and #8)
        if not self._index_pinched:
            if d_index <= pinch_threshold:
                self._index_pinched = True
        else:
            if d_index > release_threshold:
                self._index_pinched = False

        # Hysteresis for middle finger when combined with thumb+index for drag_hold
        if not self._middle_hold_pinched:
            if self._index_pinched and d_middle <= max(pinch_threshold, click_threshold):
                self._middle_hold_pinched = True
        else:
            if not self._index_pinched or d_middle > release_threshold:
                self._middle_hold_pinched = False

        cursor_point: Tuple[float, float] = (
            (thumb.x + index.x) * 0.5,
            (thumb.y + index.y) * 0.5,
        )

        # 1. Priority: Thumb + Index + Middle pinch -> drag_hold (or custom mapped action)
        if self._index_pinched and self._middle_hold_pinched and self._is_enabled("thumb_index_middle_pinch"):
            action = str(self._gesture_cfg("thumb_index_middle_pinch").get("action", "drag_hold"))
            return GestureResult(
                active_gesture="thumb_index_middle_pinch",
                action=action,
                cursor_point=cursor_point,
                pinch_distance=d_index,
                distances=distances,
                is_moving=True,
            )

        # 2. Thumb + Index pinch -> move_cursor (or custom mapped action)
        if self._index_pinched and self._is_enabled("thumb_index_pinch"):
            action = str(self._gesture_cfg("thumb_index_pinch").get("action", "move_cursor"))
            is_moving = action in ("move_cursor", "drag_hold")
            return GestureResult(
                active_gesture="thumb_index_pinch",
                action=action,
                cursor_point=cursor_point,
                pinch_distance=d_index,
                distances=distances,
                is_moving=is_moving,
            )

        # 3. Discrete secondary finger pinches (when index is NOT pinched)
        if not self._index_pinched:
            if d_middle <= click_threshold and self._is_enabled("thumb_middle_pinch"):
                if self._can_trigger("thumb_middle_pinch", now):
                    action = str(self._gesture_cfg("thumb_middle_pinch").get("action", "left_click"))
                    return GestureResult(
                        active_gesture="thumb_middle_pinch",
                        action=action,
                        cursor_point=cursor_point,
                        pinch_distance=d_index,
                        distances=distances,
                        is_moving=False,
                    )

            if d_ring <= click_threshold and self._is_enabled("thumb_ring_pinch"):
                if self._can_trigger("thumb_ring_pinch", now):
                    action = str(self._gesture_cfg("thumb_ring_pinch").get("action", "right_click"))
                    return GestureResult(
                        active_gesture="thumb_ring_pinch",
                        action=action,
                        cursor_point=cursor_point,
                        pinch_distance=d_index,
                        distances=distances,
                        is_moving=False,
                    )

            if d_pinky <= click_threshold and self._is_enabled("thumb_pinky_pinch"):
                if self._can_trigger("thumb_pinky_pinch", now):
                    action = str(self._gesture_cfg("thumb_pinky_pinch").get("action", "drag_toggle"))
                    return GestureResult(
                        active_gesture="thumb_pinky_pinch",
                        action=action,
                        cursor_point=cursor_point,
                        pinch_distance=d_index,
                        distances=distances,
                        is_moving=False,
                    )

        return GestureResult(
            active_gesture="NONE",
            action="none",
            cursor_point=cursor_point if self._index_pinched else None,
            pinch_distance=d_index,
            distances=distances,
            is_moving=False,
        )

    # Alias for backward compatibility
    def evaluate(
        self,
        landmarks: Optional[Sequence[Any]],
        timestamp: Optional[float] = None,
    ) -> GestureResult:
        return self.process(landmarks, timestamp=timestamp)
