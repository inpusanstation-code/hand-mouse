"""
OS Mouse Controller for Hand-Mouse.

Maps normalized hand coordinates from GestureEngine to screen pixel coordinates
using either:
- "absolute" mode (active camera margin box -> full screen with EMA smoothing)
- "relative" mode (touchpad-like delta movement with hand clutching when released)

Executes OS cursor movements, clicks, and drag states via PyAutoGUI, and supports
`dry_run=True` for headless unit testing or preview-only operation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pyautogui

try:
    from src.gesture_engine import GestureResult
except ImportError:
    from gesture_engine import GestureResult

# Configure PyAutoGUI for zero-latency real-time control
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0


class MouseController:
    """Controls the OS mouse cursor based on GestureResult and gesture configuration."""

    def __init__(
        self,
        dry_run: bool = False,
        screen_size: Optional[Tuple[int, int]] = None,
    ) -> None:
        pyautogui.FAILSAFE = False
        pyautogui.PAUSE = 0

        self.dry_run: bool = dry_run
        if screen_size is not None:
            self.screen_w, self.screen_h = int(screen_size[0]), int(screen_size[1])
        else:
            try:
                sz = pyautogui.size()
                self.screen_w, self.screen_h = int(sz[0]), int(sz[1])
            except Exception:
                self.screen_w, self.screen_h = 1920, 1080

        self.last_screen_pos: Tuple[int, int] = (self.screen_w // 2, self.screen_h // 2)
        self._smoothed_pos: Optional[Tuple[float, float]] = None

        self.is_dragging: bool = False
        self._hold_dragging: bool = False
        self._toggle_dragging: bool = False

        self.anchor_hand_pos: Optional[Tuple[float, float]] = None
        self.anchor_screen_pos: Optional[Tuple[float, float]] = None

        self.event_log: List[str] = []

    def map_to_screen_absolute(
        self,
        norm_x: float,
        norm_y: float,
        active_margin: float = 0.15,
    ) -> Tuple[float, float]:
        """
        Map normalized camera coordinates [active_margin, 1 - active_margin]
        to full screen coordinates [0, screen_w - 1] x [0, screen_h - 1].
        """
        margin = max(0.0, min(0.45, float(active_margin)))
        span = max(1e-6, 1.0 - 2.0 * margin)

        nx = (float(norm_x) - margin) / span
        ny = (float(norm_y) - margin) / span

        nx = max(0.0, min(1.0, nx))
        ny = max(0.0, min(1.0, ny))

        sx = nx * (self.screen_w - 1)
        sy = ny * (self.screen_h - 1)
        return sx, sy

    def _compute_target_screen_pos(
        self,
        hand_pt: Tuple[float, float],
        config: Dict[str, Any],
    ) -> Tuple[int, int]:
        mode = str(config.get("movement_mode", "absolute")).lower()
        smoothing = max(0.05, min(1.0, float(config.get("smoothing", 0.35))))
        active_margin = float(config.get("active_margin", 0.15))
        rel_sens = float(config.get("relative_sensitivity", 2.2))

        if mode == "relative":
            if self.anchor_hand_pos is None or self.anchor_screen_pos is None:
                self.anchor_hand_pos = (float(hand_pt[0]), float(hand_pt[1]))
                self.anchor_screen_pos = (
                    float(self.last_screen_pos[0]),
                    float(self.last_screen_pos[1]),
                )
                self._smoothed_pos = self.anchor_screen_pos

            dx = (float(hand_pt[0]) - self.anchor_hand_pos[0]) * self.screen_w * rel_sens
            dy = (float(hand_pt[1]) - self.anchor_hand_pos[1]) * self.screen_h * rel_sens

            raw_x = max(0.0, min(float(self.screen_w - 1), self.anchor_screen_pos[0] + dx))
            raw_y = max(0.0, min(float(self.screen_h - 1), self.anchor_screen_pos[1] + dy))
        else:
            raw_x, raw_y = self.map_to_screen_absolute(hand_pt[0], hand_pt[1], active_margin)

        if self._smoothed_pos is None:
            sm_x, sm_y = raw_x, raw_y
        else:
            sm_x = self._smoothed_pos[0] + smoothing * (raw_x - self._smoothed_pos[0])
            sm_y = self._smoothed_pos[1] + smoothing * (raw_y - self._smoothed_pos[1])

        self._smoothed_pos = (sm_x, sm_y)
        final_x = int(round(max(0.0, min(float(self.screen_w - 1), sm_x))))
        final_y = int(round(max(0.0, min(float(self.screen_h - 1), sm_y))))
        return final_x, final_y

    def _move_os_cursor(self, x: int, y: int) -> None:
        self.last_screen_pos = (x, y)
        if not self.dry_run:
            pyautogui.moveTo(x, y, _pause=False)

    def _mouse_down(self) -> None:
        if not self.is_dragging:
            self.is_dragging = True
            self.event_log.append("mouseDown")
            if not self.dry_run:
                pyautogui.mouseDown(button="left", _pause=False)

    def _mouse_up(self) -> None:
        if self.is_dragging:
            self.is_dragging = False
            self._hold_dragging = False
            self._toggle_dragging = False
            self.event_log.append("mouseUp")
            if not self.dry_run:
                pyautogui.mouseUp(button="left", _pause=False)

    def release_all(self) -> None:
        """Safely release any held mouse buttons and reset relative anchors."""
        self._mouse_up()
        self._hold_dragging = False
        self._toggle_dragging = False
        self.anchor_hand_pos = None
        self.anchor_screen_pos = None

    def apply(
        self,
        result: GestureResult,
        config: Optional[Dict[str, Any]] = None,
    ) -> Tuple[int, int]:
        """
        Execute the action described in `result` and return `(screen_x, screen_y)`.
        """
        cfg = config or {}
        action = result.action

        # If drag_hold was active in previous frame(s) and is no longer active, release mouse button
        if self._hold_dragging and action != "drag_hold":
            self._mouse_up()

        # When thumb+index pinch is released, clear relative clutch anchor
        if not result.is_moving:
            self.anchor_hand_pos = None
            self.anchor_screen_pos = None
            if str(cfg.get("movement_mode", "absolute")).lower() == "relative":
                self._smoothed_pos = None

        # Handle cursor movement (during move_cursor or drag_hold)
        if result.is_moving and result.cursor_point is not None:
            target_x, target_y = self._compute_target_screen_pos(result.cursor_point, cfg)
            if action == "drag_hold":
                self._hold_dragging = True
                self._mouse_down()
            self._move_os_cursor(target_x, target_y)

        # Handle discrete actions
        if action == "left_click":
            if self.is_dragging:
                self._mouse_up()
            self.event_log.append("left_click")
            if not self.dry_run:
                pyautogui.click(button="left", _pause=False)

        elif action == "right_click":
            self.event_log.append("right_click")
            if not self.dry_run:
                pyautogui.click(button="right", _pause=False)

        elif action == "drag_toggle":
            if self.is_dragging:
                self._mouse_up()
            else:
                self._toggle_dragging = True
                self._mouse_down()

        return self.last_screen_pos
