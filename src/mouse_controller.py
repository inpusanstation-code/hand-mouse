"""
OS Mouse Controller for Hand-Mouse.

Maps normalized hand coordinates from GestureEngine to screen pixel coordinates
using either:
- "relative" mode (default): pen on paper - while the pen is down the cursor follows the
  pen's movement on the virtual desk paper (slow strokes are scaled down for fine control);
  lifting the pen leaves the cursor in place, minus the small drift of the fingers opening
- "range" mode: the calibrated hand range is the monitor (same hand pose = same spot)
- "absolute" mode (active camera margin box -> full screen)
Both use 1-Euro + adaptive EMA smoothing.

Executes OS cursor movements, clicks, and drag states via direct Win32 API (SetCursorPos)
on Windows for near-zero latency, falling back to PyAutoGUI, and supports `dry_run=True`
for headless unit testing or preview-only operation.
"""

from __future__ import annotations

import ctypes
import math
import sys
import time
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

import pyautogui

try:
    from src.gesture_engine import GestureResult
except ImportError:
    from gesture_engine import GestureResult

# Configure PyAutoGUI for zero-latency real-time control
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

_IS_WINDOWS = sys.platform.startswith("win")
_user32 = ctypes.windll.user32 if _IS_WINDOWS else None


class OneEuroFilter2D:
    """
    2D 1-Euro Filter (Casiez et al., CHI 2012) for low-latency, jitter-free cursor tracking.
    - When the hand moves slowly or hovers to click, a low cutoff frequency (`min_cutoff`)
      heavily filters out MediaPipe landmark jitter.
    - When the hand moves quickly across the screen, the cutoff frequency dynamically
      increases (`beta` * speed), eliminating lag.
    """

    def __init__(
        self,
        min_cutoff: float = 1.2,
        beta: float = 0.04,
        d_cutoff: float = 1.0,
    ) -> None:
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.d_cutoff = float(d_cutoff)
        self._x_prev: Optional[Tuple[float, float]] = None
        self._dx_prev: Tuple[float, float] = (0.0, 0.0)
        self._t_prev: Optional[float] = None

    def reset(self) -> None:
        self._x_prev = None
        self._dx_prev = (0.0, 0.0)
        self._t_prev = None

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2.0 * math.pi * max(1e-4, cutoff))
        return 1.0 / (1.0 + tau / max(1e-4, dt))

    def filter(
        self,
        x: float,
        y: float,
        timestamp: Optional[float] = None,
        min_cutoff: Optional[float] = None,
        beta: Optional[float] = None,
    ) -> Tuple[float, float]:
        now = float(timestamp) if timestamp is not None else time.perf_counter()
        if self._x_prev is None or self._t_prev is None:
            self._x_prev = (x, y)
            self._dx_prev = (0.0, 0.0)
            self._t_prev = now
            return x, y

        dt = now - self._t_prev
        if dt <= 1e-5 or dt > 0.5:
            dt = 1.0 / 30.0
        self._t_prev = now

        mc = float(min_cutoff) if min_cutoff is not None else self.min_cutoff
        b = float(beta) if beta is not None else self.beta

        # Estimate derivative (speed in normalized/pixel space per second)
        dx = (x - self._x_prev[0]) / dt
        dy = (y - self._x_prev[1]) / dt

        a_d = self._alpha(self.d_cutoff, dt)
        edx = a_d * dx + (1.0 - a_d) * self._dx_prev[0]
        edy = a_d * dy + (1.0 - a_d) * self._dx_prev[1]
        self._dx_prev = (edx, edy)

        speed = math.hypot(edx, edy)
        cutoff = mc + b * speed
        a = self._alpha(cutoff, dt)

        fx = self._x_prev[0] + a * (x - self._x_prev[0])
        fy = self._x_prev[1] + a * (y - self._x_prev[1])
        self._x_prev = (fx, fy)
        return fx, fy


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
        self._one_euro = OneEuroFilter2D()

        self.is_dragging: bool = False
        self._hold_dragging: bool = False
        self._toggle_dragging: bool = False

        self.anchor_hand_pos: Optional[Tuple[float, float]] = None
        self.anchor_screen_pos: Optional[Tuple[float, float]] = None

        # Pointer acceleration state (pen speed in palm widths per second)
        self._last_move_t: Optional[float] = None
        self._speed_ema: float = 0.0
        # Recent cursor positions while the pen is down, for rolling back the lift drift
        self._history: deque = deque()
        self._was_moving: bool = False

        # Still lock (pen mode): hold the cursor when the pinched hand nearly stops
        self._slow_since: Optional[float] = None
        self.locked: bool = False
        self._lock_travel: float = 0.0
        # Precision mode: slow cursor after the still lock, until a fast or long move
        self.precise: bool = False
        self._precise_travel: float = 0.0

        # Click freeze (pen mode): cursor held where it was aimed while a click forms
        self._freeze_pos: Optional[Tuple[int, int]] = None
        self._freeze_until: float = 0.0

        # Jitter meter: recent raw targets and output positions while the pen is down
        self._jit_raw: deque = deque(maxlen=20)
        self._jit_out: deque = deque(maxlen=20)
        self.jitter_raw_px: float = 0.0
        self.jitter_out_px: float = 0.0

        self.event_log: List[str] = []

    def map_to_screen_absolute(
        self,
        norm_x: float,
        norm_y: float,
        active_margin: float = 0.15,
        dpi_scale: float = 1.0,
    ) -> Tuple[float, float]:
        """
        Map normalized camera coordinates [active_margin, 1 - active_margin]
        to full screen coordinates [0, screen_w - 1] x [0, screen_h - 1].
        When `dpi_scale` > 1.0, the effective hand travel span shrinks by `1 / dpi_scale`,
        allowing small hand movements around the center to cover the entire monitor.
        """
        margin = max(0.0, min(0.45, float(active_margin)))
        dpi = max(0.25, min(10.0, float(dpi_scale)))
        base_span = max(1e-6, 1.0 - 2.0 * margin)
        effective_span = max(0.04, base_span / dpi)

        nx = 0.5 + (float(norm_x) - 0.5) / effective_span
        ny = 0.5 + (float(norm_y) - 0.5) / effective_span

        nx = max(0.0, min(1.0, nx))
        ny = max(0.0, min(1.0, ny))

        sx = nx * (self.screen_w - 1)
        sy = ny * (self.screen_h - 1)
        return sx, sy

    @staticmethod
    def accel_gain(speed: float, config: Dict[str, Any]) -> float:
        """Speed-dependent gain: slow strokes are scaled down for fine control,
        fast strokes keep (or exceed) the full pen speed."""
        lo = float(config.get("accel_low_speed", 0.15))
        hi = max(lo + 1e-3, float(config.get("accel_high_speed", 1.5)))
        g_min = float(config.get("accel_min_gain", 0.2))
        g_max = float(config.get("accel_max_gain", 1.8))
        x = max(0.0, min(1.0, (speed - lo) / (hi - lo)))
        x = x * x * (3.0 - 2.0 * x)  # smoothstep
        return g_min + (g_max - g_min) * x

    def _compute_target_screen_pos(
        self,
        hand_pt: Tuple[float, float],
        config: Dict[str, Any],
        now: Optional[float] = None,
        mode: Optional[str] = None,
    ) -> Tuple[int, int]:
        mode = (mode or str(config.get("movement_mode", "relative"))).lower()
        smoothing = max(0.05, min(1.0, float(config.get("smoothing", 0.35))))
        active_margin = float(config.get("active_margin", 0.15))
        dpi_scale = float(config.get("dpi_scale", 1.0))
        deadzone_px = float(config.get("deadzone_px", 1.5))

        if mode == "relative":
            # Pen on paper: hand_pt is the accumulated paper position (palm units).
            # The cursor moves by the pen's step each frame, like a mouse on a desk;
            # pushing past a screen edge does not create dead travel on the way back.
            if self.anchor_hand_pos is None or self.anchor_screen_pos is None:
                self.anchor_hand_pos = (float(hand_pt[0]), float(hand_pt[1]))
                self.anchor_screen_pos = (
                    float(self.last_screen_pos[0]),
                    float(self.last_screen_pos[1]),
                )
                self._smoothed_pos = self.anchor_screen_pos
                self._last_move_t = now
                self._speed_ema = 0.0
                self._slow_since = None
                self.locked = False
                self.precise = False
                self._jit_raw.clear()
                self._jit_out.clear()
                self._one_euro.reset()
                self._one_euro.filter(self.anchor_screen_pos[0], self.anchor_screen_pos[1], timestamp=now)
                return int(round(self.anchor_screen_pos[0])), int(round(self.anchor_screen_pos[1]))

            du = float(hand_pt[0]) - self.anchor_hand_pos[0]
            dv = float(hand_pt[1]) - self.anchor_hand_pos[1]
            self.anchor_hand_pos = (float(hand_pt[0]), float(hand_pt[1]))

            # Pointer acceleration: slow strokes move the cursor less (fine control),
            # fast strokes move it more (cross the screen without many re-grips).
            t = now if now is not None else time.perf_counter()
            dt = (t - self._last_move_t) if self._last_move_t is not None else 1.0 / 30.0
            dt = max(1.0 / 240.0, min(0.2, dt))
            self._last_move_t = t
            step = math.hypot(du, dv)
            self._speed_ema = 0.5 * self._speed_ema + 0.5 * step / dt
            if bool(config.get("pointer_acceleration", False)):
                accel = self.accel_gain(self._speed_ema, config)
            else:
                accel = 1.0

            # Precision mode: once the hand has stopped over a target, move slowly until it
            # clearly leaves (fast or far).
            if self.precise:
                self._precise_travel += step
                if self._speed_ema > float(config.get("precision_exit_speed", 0.8)) or (
                    self._precise_travel > float(config.get("precision_exit_dist", 0.6))
                ):
                    self.precise = False
                else:
                    accel = min(accel, float(config.get("precision_gain", 0.2)))

            # Still lock: a nearly stopped hand holds the cursor; a clear move lets go.
            if bool(config.get("still_lock", False)):
                if self.locked:
                    self._lock_travel += step
                    if self._lock_travel >= float(config.get("still_unlock_dist", 0.05)):
                        self.locked = False
                        self._slow_since = None
                    else:
                        du = dv = 0.0
                elif self._speed_ema < float(config.get("still_lock_speed", 0.08)):
                    if self._slow_since is None:
                        self._slow_since = t
                    elif t - self._slow_since >= float(config.get("still_lock_time_s", 0.2)):
                        self.locked = True
                        self._lock_travel = 0.0
                        du = dv = 0.0
                        if bool(config.get("precision_mode", False)):
                            self.precise = True
                            self._precise_travel = 0.0
                else:
                    self._slow_since = None

            # Same scale on both axes (paper units are isotropic).
            px_per_unit = self.screen_w * float(config.get("pen_speed", 1.2)) * dpi_scale * accel
            raw_x = max(0.0, min(float(self.screen_w - 1), self.anchor_screen_pos[0] + du * px_per_unit))
            raw_y = max(0.0, min(float(self.screen_h - 1), self.anchor_screen_pos[1] + dv * px_per_unit))
            self.anchor_screen_pos = (raw_x, raw_y)
        elif mode == "range":
            # Hand range = monitor: hand_pt is already the screen position (0..1).
            raw_x = max(0.0, min(1.0, float(hand_pt[0]))) * (self.screen_w - 1)
            raw_y = max(0.0, min(1.0, float(hand_pt[1]))) * (self.screen_h - 1)
        else:
            raw_x, raw_y = self.map_to_screen_absolute(
                hand_pt[0], hand_pt[1], active_margin, dpi_scale=dpi_scale
            )

        self._jit_raw.append((raw_x, raw_y))

        # When smoothing == 1.0 (e.g. deterministic unit tests), bypass filter & deadzone
        if smoothing >= 0.999:
            self._smoothed_pos = (raw_x, raw_y)
            final_x = int(round(max(0.0, min(float(self.screen_w - 1), raw_x))))
            final_y = int(round(max(0.0, min(float(self.screen_h - 1), raw_y))))
            return final_x, final_y

        # Adaptive 1-Euro Filter blended with responsive EMA
        min_cutoff = float(config.get("one_euro_min_cutoff", 0.8 + 1.8 * smoothing))
        # In pixel coordinates, normalize beta by screen diagonal so speed scaling is resolution-independent
        diag = math.hypot(self.screen_w, self.screen_h)
        beta = float(config.get("one_euro_beta", 0.04)) / max(100.0, diag * 0.25)

        euro_x, euro_y = self._one_euro.filter(raw_x, raw_y, timestamp=now, min_cutoff=min_cutoff, beta=beta)

        if self._smoothed_pos is None:
            sm_x, sm_y = euro_x, euro_y
        else:
            # Velocity-boosted EMA: small tremors use low alpha, large deliberate moves snap faster
            dist_px = math.hypot(euro_x - self._smoothed_pos[0], euro_y - self._smoothed_pos[1])
            if dist_px < deadzone_px:
                # Sub-pixel deadzone prevents stationary cursor vibration
                sm_x, sm_y = self._smoothed_pos
            else:
                speed_boost = min(1.0, dist_px / 90.0)
                adaptive_alpha = min(0.92, smoothing + (1.0 - smoothing) * 0.55 * speed_boost)
                sm_x = self._smoothed_pos[0] + adaptive_alpha * (euro_x - self._smoothed_pos[0])
                sm_y = self._smoothed_pos[1] + adaptive_alpha * (euro_y - self._smoothed_pos[1])

        self._smoothed_pos = (sm_x, sm_y)
        final_x = int(round(max(0.0, min(float(self.screen_w - 1), sm_x))))
        final_y = int(round(max(0.0, min(float(self.screen_h - 1), sm_y))))
        return final_x, final_y

    @staticmethod
    def _spread(points) -> float:
        """Shake in pixels: RMS distance from a straight-line fit through the recent points,
        so steady motion is not counted, only the wobble around it."""
        n = len(points)
        if n < 5:
            return 0.0
        idx = list(range(n))
        mi = (n - 1) / 2.0
        var_i = sum((i - mi) ** 2 for i in idx)
        total = 0.0
        for axis in (0, 1):
            vals = [p[axis] for p in points]
            mv = sum(vals) / n
            slope = sum((i - mi) * (v - mv) for i, v in zip(idx, vals)) / var_i
            total += sum((v - (mv + slope * (i - mi))) ** 2 for i, v in zip(idx, vals))
        return math.sqrt(total / n)

    def _update_jitter(self) -> None:
        """Jitter meter: before (raw) and after (output) smoothing, while the pen is down."""
        self.jitter_raw_px = self._spread(self._jit_raw)
        self.jitter_out_px = self._spread(self._jit_out)

    def _position_before(self, now: float, lookback: float) -> Tuple[int, int]:
        """Cursor position `lookback` seconds ago (while the pen was down), else the current one."""
        target = self.last_screen_pos
        for t, pos in self._history:
            if t <= now - lookback:
                target = pos
            else:
                break
        if target == self.last_screen_pos and self._history and self._history[0][0] > now - lookback:
            target = self._history[0][1]
        return int(target[0]), int(target[1])

    def _rollback_on_lift(self, config: Dict[str, Any]) -> None:
        """Move the cursor back to where it was `lift_rollback_s` before the pen was lifted,
        unless the hand was moving fast then (a deliberate swipe is kept as is)."""
        window = float(config.get("lift_rollback_s", 0.12))
        max_px = float(config.get("lift_rollback_max_px", 60.0))
        if window <= 0 or len(self._history) < 2:
            return
        t_end, last = self._history[-1]
        target = self._history[0][1]
        for t, pos in self._history:
            if t <= t_end - window:
                target = pos
            else:
                break
        if target != last and math.hypot(target[0] - last[0], target[1] - last[1]) <= max_px:
            self._move_os_cursor(int(target[0]), int(target[1]))
            self.event_log.append("rollback")

    def _move_os_cursor(self, x: int, y: int) -> None:
        if (x, y) == self.last_screen_pos and self._smoothed_pos is not None:
            return
        self.last_screen_pos = (x, y)
        if not self.dry_run:
            if _IS_WINDOWS and _user32 is not None:
                # Direct Win32 API call avoids PyAutoGUI wrapper overhead (~0.01ms vs ~2-5ms)
                _user32.SetCursorPos(int(x), int(y))
            else:
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

    def center_cursor(self) -> Tuple[int, int]:
        """Put the cursor at the middle of the screen and start the next stroke fresh."""
        self.reset_anchors()
        self._history.clear()
        self._was_moving = False
        self._move_os_cursor(self.screen_w // 2, self.screen_h // 2)
        return self.last_screen_pos

    def place_cursor(self, nx: float, ny: float) -> Tuple[int, int]:
        """Put the cursor at a screen fraction (used to show which corner is being set)."""
        self.reset_anchors()
        self._history.clear()
        self._was_moving = False
        self._move_os_cursor(int(nx * (self.screen_w - 1)), int(ny * (self.screen_h - 1)))
        return self.last_screen_pos

    def release_all(self) -> None:
        """Safely release any held mouse buttons and reset relative anchors."""
        self._mouse_up()
        self._hold_dragging = False
        self._toggle_dragging = False
        self.anchor_hand_pos = None
        self.anchor_screen_pos = None
        self._one_euro.reset()

    def reset_anchors(self) -> None:
        """Clear relative clutch anchors and smoothing state so the next frame starts fresh
        (used after neutral re-calibration so the cursor does not glide from the old baseline)."""
        self.anchor_hand_pos = None
        self.anchor_screen_pos = None
        self._smoothed_pos = None
        self._one_euro.reset()

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
        now = result.timestamp if result.timestamp is not None else time.perf_counter()
        mode = str(cfg.get("movement_mode", "relative")).lower()
        if mode == "thumb":
            mode = "range"  # thumb mode: screen_point is already the target, like range mode
        if mode == "range" and result.screen_point is None:
            mode = "relative"  # not calibrated yet: fall back to the pen

        # Thumb mode click: put the cursor exactly where it was aimed and keep it there.
        if result.hold_point is not None:
            hx = int(round(max(0.0, min(1.0, result.hold_point[0])) * (self.screen_w - 1)))
            hy = int(round(max(0.0, min(1.0, result.hold_point[1])) * (self.screen_h - 1)))
            if (hx, hy) != self.last_screen_pos:
                self._smoothed_pos = None
                self._move_os_cursor(hx, hy)
            self._smoothed_pos = (float(hx), float(hy))
            self._one_euro.reset()
            self._was_moving = False
            self._history.clear()

        # Pen mode click: go back to where the cursor was just before the thumb headed for
        # the click finger, and stay there until the click is let go.
        frozen = False
        if mode == "relative" and bool(cfg.get("click_freeze", False)):
            if result.click_forming:
                if self._freeze_pos is None:
                    self._freeze_pos = self._position_before(
                        now, float(cfg.get("click_freeze_lookback_s", 0.25)))
                    self._move_os_cursor(*self._freeze_pos)
                self._freeze_until = float("inf")
            elif self._freeze_pos is not None:
                if self._freeze_until == float("inf"):
                    self._freeze_until = now + float(cfg.get("click_release_hold_s", 0.35))
                elif now >= self._freeze_until:
                    self._freeze_pos = None
            frozen = self._freeze_pos is not None
            if frozen:
                # Keep the cursor still; the pen starts afresh from here afterwards.
                self.anchor_hand_pos = None
                self.anchor_screen_pos = None
                self._smoothed_pos = None
                self._history.clear()
                self._was_moving = False
                self._move_os_cursor(*self._freeze_pos)

        # Pen lifted: undo the small drift caused by the fingers opening (before a drag
        # is released, so the drop lands where it was aimed).
        if self._was_moving and not result.is_moving and not frozen:
            self._rollback_on_lift(cfg)
        self._was_moving = result.is_moving
        if not result.is_moving:
            self._history.clear()

        # If drag_hold was active in previous frame(s) and is no longer active, release mouse button
        if self._hold_dragging and action != "drag_hold":
            self._mouse_up()

        # When thumb+index pinch is released, clear relative clutch anchor
        if not result.is_moving:
            self.anchor_hand_pos = None
            self.anchor_screen_pos = None
            self._one_euro.reset()
            if mode == "relative":
                self._smoothed_pos = None

        # Handle cursor movement (during move_cursor or drag_hold)
        hand_pt = {"relative": result.paper_point, "range": result.screen_point}.get(mode, result.cursor_point)
        if result.is_moving and hand_pt is not None and not frozen:
            target_x, target_y = self._compute_target_screen_pos(hand_pt, cfg, now, mode)
            if action == "drag_hold":
                self._hold_dragging = True
                self._mouse_down()
            self._move_os_cursor(target_x, target_y)
            self._jit_out.append(self.last_screen_pos)
            self._update_jitter()
            self._history.append((now, self.last_screen_pos))
            while self._history and now - self._history[0][0] > 1.0:
                self._history.popleft()

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
