"""
Gesture recognition engine and customizable configuration for Hand-Mouse.

Optional "thumb" mode (M key): the thumb tip steers the cursor. Its position is measured inside
the hand itself (origin = wrist, axes = the hand's own up/side directions, unit = palm
size), so moving, turning or bringing the whole hand closer does not move the cursor -
only the thumb does. Calibration: the user puts the thumb tip where each monitor corner
should be and holds it still; those four spots span the whole monitor. Clicks in thumb
mode come from straightening fingers out of a loose fist: index out = left click,
index + middle out = right click (curl them back in before the next click). While a
click is forming the cursor is put back where it was just before and held there.

Default pinch modes - the camera looks down at a hand moving over a desk:
A virtual "paper" lies flat on the desk and stands for the monitor.

- Thumb (#4) + Index (#8) pinch  = pen down. While the pen is down:
    * left/right = moving the hand sideways (along the calibrated horizontal line)
    * up/down    = curling the middle, ring and pinky fingers into the palm (cursor down)
                   or opening them (cursor up). All three are used together so this is
                   never confused with a single thumb+middle / thumb+ring pinch.
  Releasing = pen up (cursor stays; like lifting and placing a mouse).
- Calibration (once at first start, and again whenever the user asks), two steps:
    1. direction: with the pen down, sweep left and right several times, starting to the
       right. Stray strokes are ignored: the densest bundle of stroke directions is
       averaged and becomes the screen's horizontal axis.
    2. corners: for each monitor corner the user makes the hand pose that should reach it
       (hand at its comfortable left/right end, three fingers open = top / curled = bottom),
       pinches and holds briefly. The user's own hand range then spans the whole monitor
       ("range" mode). Up/down is the fingers' curl ratio. Left/right uses whichever the
       user actually did: turning the wrist (hand angle) or moving the hand (position along
       the step-1 line, in palm widths). If the corners' left/right difference is too small,
       the range swept in step 1 is used, so the calibration never loops.
- Thumb + Middle (#12) pinch     = left click  (fires once per pinch)
- Thumb + Ring (#16) pinch       = right click (fires once per pinch)
- Thumb + Index + Middle         = drag hold  (optional, off by default)
- Thumb + Pinky (#20) pinch      = drag toggle (optional, off by default)

The paper is 2D: only the x, y image coordinates of the hand are used (no depth).
A stroke that curves because the arm swings around the elbow is straightened by
measuring the movement in the hand's own frame, so the cursor moves in a line.

Finger selection: every frame the thumb's distance to each fingertip is measured
(x, y only, aspect-corrected, palm-size normalized). The closest finger
wins only when it is under its threshold AND clearly closer than the runner-up,
and a click must hold for a few frames before it fires. Neighbouring fingers that
bend along no longer steal or block each other's pinches.
"""

from __future__ import annotations

import copy
import json
import math
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "gestures.json"

VALID_ACTIONS = {
    "none",
    "move_cursor",
    "left_click",
    "right_click",
    "drag_hold",
    "drag_toggle",
}

# Actions that stay active (and move the cursor) for as long as the pinch is held.
CONTINUOUS_ACTIONS = {"move_cursor", "drag_hold"}

# "range" = the calibrated hand range is the monitor (same pose = same spot),
# "relative" = pen on paper (lift and place), "absolute" = camera area mapped to the screen.
VALID_MOVEMENT_MODES = {"thumb", "range", "relative", "absolute"}

# Monitor corners captured by the calibration: (name, screen x, screen y)
CORNERS: Tuple[Tuple[str, float, float], ...] = (
    ("tl", 0.0, 0.0),
    ("tr", 1.0, 0.0),
    ("br", 1.0, 1.0),
    ("bl", 0.0, 1.0),
)

DEFAULT_CONFIG: Dict[str, Any] = {
    # Thresholds are thumb-to-fingertip distances expressed in reference-palm units
    # (distance / palm size * reference_palm_size).
    "pinch_threshold": 0.055,
    "release_threshold": 0.080,
    "click_threshold": 0.075,
    "finger_separation": 0.75,
    "click_confirm_frames": 2,
    # A click finger must be this much closer to the thumb than the next enabled finger.
    "click_separation": 0.8,
    "reference_palm_size": 0.22,
    "smoothing": 0.35,
    "active_margin": 0.15,
    "movement_mode": "relative",
    # Pen mode: screen widths the cursor travels when the hand moves one palm width.
    "pen_speed": 2.0,
    "dpi_scale": 1.0,
    # A hand resting on a desk curls toward the palm, so the paper it "draws" on is not
    # square to the camera. Both angles are user-adjustable (J/L and I/K keys):
    # - paper_rotation_deg: paper turned on the desk relative to the hand direction; a stroke
    #   that looks diagonal in the camera comes out as a straight cursor line.
    # - paper_tilt_deg: paper leaning like a slanted easel; forward/back strokes look shorter
    #   from above by cos(tilt), so they are stretched back by 1 / cos(tilt).
    "paper_rotation_deg": 0.0,
    "paper_tilt_deg": 45.0,
    # Horizontal axis measured by the "draw a horizontal line" calibration (None = not yet).
    "paper_x_angle_deg": None,
    # Calibration: total sweep length (palm widths) inside the main direction bundle needed.
    "calib_target_length": 6.0,
    # Strokes within this many degrees of the densest direction count toward the bundle.
    "calib_bundle_deg": 20.0,
    # Up/down source: "fingers" (curl middle+ring+pinky) or "hand" (move the hand).
    "vertical_source": "hand",
    # Fingers mode: paper units the cursor moves for one full curl (open -> closed).
    "curl_gain": 0.45,
    # Measured by the up/down calibration: openness with fingers fully open / fully curled
    # (None = not measured; a typical range of 0.9 is assumed).
    "curl_open": None,
    "curl_closed": None,
    # Range mode (set by the corner calibration), all from the hand skeleton: hand turn angle
    # (wrist -> knuckles, degrees) at the left/right screen edge, and three-finger openness
    # at the top/bottom edge. None = not calibrated yet.
    "range_left_deg": None,
    "range_right_deg": None,
    # Which left/right measure range mode uses: "turn" (wrist angle, the *_deg values) or
    # "move" (hand position along the horizontal line in palm widths, the *_pos values).
    "range_x_source": "turn",
    "range_left_pos": None,
    "range_right_pos": None,
    "range_top": None,
    "range_bottom": None,
    # Stretch so the corners are reached without straining (fraction of the range).
    "range_margin": 0.04,
    # Corner capture: hold the pinch this long (seconds); the first part is skipped.
    "corner_hold_s": 0.6,
    "corner_settle_s": 0.15,
    # Smallest accepted left/right range: wrist turn (degrees) or hand move (palm widths),
    # and the smallest openness difference for up/down.
    "range_min_turn_deg": 12.0,
    "range_min_move": 0.6,
    "curl_min_range": 0.25,
    # Thumb mode: thumb-tip spots (hand coordinates, palm units) for the corners
    # [top-left, top-right, bottom-right, bottom-left]; None = not calibrated yet.
    "thumb_corners": None,
    # Thumb corner capture: hold the thumb still this long, within this distance (palm units),
    # and move it at least this far before the next corner can be captured.
    "thumb_hold_s": 0.7,
    "thumb_still_tol": 0.04,
    "thumb_rearm_dist": 0.12,
    # Smallest accepted thumb area (palm units squared).
    "thumb_min_area": 0.004,
    # Thumb mode clicks by straightening fingers: a finger counts as straight when its
    # fingertip-to-wrist distance is this many times its knuckle-to-wrist distance (on),
    # and as curled again below the off value. The pose must hold for extend_confirm_s.
    "extend_on_ratio": 1.55,
    "extend_off_ratio": 1.35,
    "extend_confirm_s": 0.15,
    # Thumb mode clicks: when the thumb starts heading for a click finger, put the cursor back
    # where it was this long before, and keep it there until this long after the click.
    "click_freeze_lookback_s": 0.25,
    "click_release_hold_s": 0.35,
    # Run the calibration every time the app starts (otherwise only when never done).
    "calibrate_on_start": True,
    # The pen may hand over to a click finger only this soon after pen down (the thumb
    # sliding past the index); later, curling fingers for up/down never clicks.
    "pen_takeover_window_s": 0.25,
    # Extra gain for forward/back strokes on top of the tilt correction.
    "paper_depth_gain": 1.0,
    # Turn arcs (arm swinging around the elbow) into straight cursor lines.
    "straighten_arcs": True,
    # Mirror left/right on the paper (F key toggles it).
    "paper_invert_x": True,
    # The user's own left/right flip (F key). Calibration never resets it.
    "flip_x": False,
    # Share of the pinch point in the pen point (rest is the knuckles, which stay put
    # while fingers open/close so the cursor does not twitch on pen up/down).
    "pen_finger_weight": 0.0,
    # Speed-dependent gain: below accel_low_speed (palm widths/s) the cursor moves at
    # accel_min_gain x, above accel_high_speed at accel_max_gain x.
    "pointer_acceleration": True,
    "accel_min_gain": 0.25,
    "accel_max_gain": 1.8,
    "accel_low_speed": 0.15,
    "accel_high_speed": 1.5,
    # On pen lift, undo the last moment of movement (fingers opening) if it was small.
    "lift_rollback_s": 0.12,
    "lift_rollback_max_px": 60,
    # Jitter filter: low cutoff while (nearly) still, opens up with speed (beta).
    # Hand landmarks are smoothed before anything is measured (1-Euro filter per point):
    # low cutoff = steady when still, beta opens it up when the hand moves fast.
    "landmark_filter": True,
    "landmark_min_cutoff": 1.5,
    "landmark_beta": 8.0,
    # Pen mode: when the pinched hand nearly stops for a moment the cursor is held still;
    # it lets go once the hand clearly moves again (speed in palm widths per second,
    # distance in palm widths).
    "still_lock": True,
    "still_lock_speed": 0.08,
    "still_lock_time_s": 0.2,
    "still_unlock_dist": 0.05,
    # Precision mode (pen mode): after the still lock, the cursor moves at precision_gain
    # until the hand moves fast (palm widths per second) or far (palm widths) again.
    "precision_mode": True,
    "precision_gain": 0.2,
    "precision_exit_speed": 0.8,
    "precision_exit_dist": 0.6,
    # Pen mode clicks: while a click forms the cursor goes back to where it was this long
    # before and stays there until the click is let go (+ click_release_hold_s).
    "click_freeze": True,
    "one_euro_min_cutoff": 0.8,
    "one_euro_beta": 1.5,
    "deadzone_px": 2.5,
    "gestures": {
        "thumb_index_pinch": {
            "action": "move_cursor",
            "enabled": True,
            "description": "엄지+검지 붙임: 펜 내림(도화지 위에서 커서 이동)",
        },
        "thumb_middle_pinch": {
            "action": "left_click",
            "enabled": True,
            "cooldown": 0.15,
            "description": "엄지+중지 붙임: 좌클릭(붙일 때마다 한 번)",
        },
        "thumb_ring_pinch": {
            "action": "right_click",
            "enabled": True,
            "cooldown": 0.25,
            "description": "엄지+약지 붙임: 우클릭(붙일 때마다 한 번)",
        },
        "thumb_index_middle_pinch": {
            "action": "drag_hold",
            "enabled": False,
            "description": "엄지+검지+중지 함께 붙임: 누른 채 끌기(기본 꺼짐)",
        },
        "thumb_pinky_pinch": {
            "action": "drag_toggle",
            "enabled": False,
            "cooldown": 0.6,
            "description": "엄지+소지 붙임: 끌기 켜기/끄기(기본 꺼짐)",
        },
        "index_extend": {
            "action": "left_click",
            "enabled": True,
            "cooldown": 0.15,
            "description": "엄지 모드: 검지 펴기 = 좌클릭 (다시 말았다 펴면 다음 클릭)",
        },
        "index_middle_extend": {
            "action": "right_click",
            "enabled": True,
            "cooldown": 0.25,
            "description": "엄지 모드: 검지+중지 펴기 = 우클릭",
        },
    },
}

FINGERS: Tuple[str, ...] = ("index", "middle", "ring", "pinky")


def _point_segment_distance(p: Tuple[float, float], a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """Distance from point p to the segment a-b."""
    abx, aby = b[0] - a[0], b[1] - a[1]
    denom = abx * abx + aby * aby
    t = 0.0 if denom <= 1e-12 else max(0.0, min(1.0, ((p[0] - a[0]) * abx + (p[1] - a[1]) * aby) / denom))
    return math.hypot(p[0] - (a[0] + t * abx), p[1] - (a[1] + t * aby))


def _homography(src: Sequence[Tuple[float, float]], dst: Sequence[Tuple[float, float]]) -> Optional[list]:
    """3x3 projective map taking the 4 src points onto the 4 dst points (None if degenerate)."""
    rows, rhs = [], []
    for (x, y), (u, v) in zip(src, dst):
        rows.append([x, y, 1.0, 0.0, 0.0, 0.0, -u * x, -u * y])
        rhs.append(u)
        rows.append([0.0, 0.0, 0.0, x, y, 1.0, -v * x, -v * y])
        rhs.append(v)
    # Gaussian elimination with partial pivoting on the 8x8 system
    n = 8
    a = [rows[i] + [rhs[i]] for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) < 1e-12:
            return None
        a[col], a[piv] = a[piv], a[col]
        for r in range(n):
            if r != col:
                f = a[r][col] / a[col][col]
                for c in range(col, n + 1):
                    a[r][c] -= f * a[col][c]
    h = [a[i][n] / a[i][i] for i in range(n)] + [1.0]
    return h


def _apply_homography(h: Sequence[float], p: Tuple[float, float]) -> Tuple[float, float]:
    x, y = p
    w = h[6] * x + h[7] * y + h[8]
    if abs(w) < 1e-12:
        w = 1e-12
    return (h[0] * x + h[1] * y + h[2]) / w, (h[3] * x + h[4] * y + h[5]) / w


def _is_convex(quad: Sequence[Tuple[float, float]]) -> bool:
    signs = []
    for i in range(4):
        (x0, y0), (x1, y1), (x2, y2) = quad[i], quad[(i + 1) % 4], quad[(i + 2) % 4]
        signs.append((x1 - x0) * (y2 - y1) - (y1 - y0) * (x2 - x1))
    return all(v > 0 for v in signs) or all(v < 0 for v in signs)


def _wrap(angle: float) -> float:
    """Wrap an angle to [-pi, pi]."""
    return math.atan2(math.sin(angle), math.cos(angle))

FINGER_TIPS = {"index": 8, "middle": 12, "ring": 16, "pinky": 20}
FINGER_DIPS = {"index": 7, "middle": 11, "ring": 15, "pinky": 19}
FINGER_GESTURES = {
    "index": "thumb_index_pinch",
    "middle": "thumb_middle_pinch",
    "ring": "thumb_ring_pinch",
    "pinky": "thumb_pinky_pinch",
}
DRAG_COMBO = "index_middle"
DRAG_GESTURE = "thumb_index_middle_pinch"


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
    # Pen point in normalized image coordinates (used by absolute mode and the HUD).
    cursor_point: Optional[Tuple[float, float]] = None
    # Accumulated pen position on the paper, in palm-width units (used by pen mode).
    paper_point: Optional[Tuple[float, float]] = None
    pinch_distance: float = 1.0
    distances: Dict[str, float] = field(default_factory=dict)
    is_moving: bool = False
    # Pinch being confirmed (not yet fired), for HUD feedback.
    pending_gesture: Optional[str] = None
    # Frame time (seconds), used for pointer acceleration and lift rollback.
    timestamp: Optional[float] = None
    # Thumb mode: straightness of index / middle (fingertip-to-wrist / knuckle-to-wrist)
    extension: Dict[str, float] = field(default_factory=dict)
    # Openness of middle+ring+pinky (fingertip-to-wrist / palm; smaller = curled)
    curl: Optional[float] = None
    # Range / thumb mode: where the current hand pose points on the screen (0..1, 0..1)
    screen_point: Optional[Tuple[float, float]] = None
    # Thumb mode: keep the cursor exactly here (screen 0..1) while a click is happening
    hold_point: Optional[Tuple[float, float]] = None
    # Thumb tip in hand coordinates (palm units: x = across the hand, y = along it)
    thumb_point: Optional[Tuple[float, float]] = None
    # True while the horizontal-line calibration is running (no cursor moves or clicks).
    calibrating: bool = False
    # True while a click finger (middle / ring) is about to click or is held.
    click_forming: bool = False


class _OneEuro:
    """Scalar 1-Euro filter (Casiez et al. 2012) for one landmark coordinate."""

    __slots__ = ("x", "dx", "t")

    def __init__(self) -> None:
        self.x: Optional[float] = None
        self.dx = 0.0
        self.t = 0.0

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2.0 * math.pi * max(1e-4, cutoff))
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x: float, t: float, min_cutoff: float, beta: float) -> float:
        if self.x is None:
            self.x, self.t = x, t
            return x
        dt = t - self.t
        if dt <= 1e-5 or dt > 0.5:
            dt = 1.0 / 30.0
        self.t = t
        a_d = self._alpha(1.0, dt)
        self.dx = a_d * (x - self.x) / dt + (1.0 - a_d) * self.dx
        a = self._alpha(min_cutoff + beta * abs(self.dx), dt)
        self.x = self.x + a * (x - self.x)
        return self.x


class GestureEngine:
    """
    Processes 21 hand landmarks into pen-on-paper cursor movement and click gestures.
    """

    WRIST = 0
    THUMB_TIP = 4
    INDEX_MCP = 5
    MIDDLE_MCP = 9
    RING_MCP = 13
    PINKY_MCP = 17

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
        self._last_trigger_times: Dict[str, float] = {}

        # Pinch state
        self._active: Optional[str] = None
        self._candidate: Optional[str] = None
        self._candidate_frames: int = 0

        # Paper (pen) state
        self._paper: Tuple[float, float] = (0.0, 0.0)
        self._last_pen: Optional[Tuple[float, float]] = None
        self.palm_size: float = float(self.config.get("reference_palm_size", 0.22))
        self.aspect: float = 1.0
        self.last_pen_image: Optional[Tuple[float, float]] = None

        # Paper "up" direction in the image (0 rad = image up). Auto-snapped to 90 degree
        # steps from the hand direction until the user locks it with calibrate_neutral().
        self.forward_angle: float = 0.0
        self._user_calibrated: bool = False
        self._hand_dir: Optional[Tuple[float, float]] = None
        self._last_hand_angle: Optional[float] = None
        # Hand rotation since pen down (for straightening arcs)
        self._stroke_ref_angle: Optional[float] = None
        self._stroke_angle: float = 0.0
        self._pen_down_t: Optional[float] = None

        # Middle+ring+pinky openness (smoothed) for up/down control
        self._curl: Optional[float] = None
        # Hand turn angle from the skeleton (wrist -> mean of the four knuckles), smoothed
        self._yaw: Optional[float] = None
        # Thumb mode: thumb tip in hand coordinates (smoothed), the hand frame of this frame,
        # recent screen points (for the click freeze), and the frozen point.
        self._thumb: Optional[Tuple[float, float]] = None
        self._hand_frame: Optional[Tuple[Tuple[float, float], Tuple[float, float], Tuple[float, float], float]] = None
        self._thumb_hist: deque = deque()
        self._freeze_point: Optional[Tuple[float, float]] = None
        self._freeze_until: float = float("inf")
        self._thumb_still: list = []
        # Thumb mode extension clicks
        self._extended: Dict[str, bool] = {"index": False, "middle": False}
        self._extension: Dict[str, float] = {}
        self._click_armed: bool = False  # a curled (neutral) hand has been seen
        self._click_candidate: Optional[str] = None  # "index_extend" / "index_middle_extend"
        self._click_t0: float = 0.0
        self._click_latched: Optional[str] = None
        self._thumb_armed: bool = True
        self._homography: Optional[list] = None
        self._homography_src: Optional[list] = None
        self._last_curl: Optional[float] = None

        # Horizontal-line calibration
        self.calibrating: bool = False
        self.calib_state: str = "idle"  # idle | wait | drawing | short
        self.calib_segments: list = []  # drawn segments, normalized image coords (for the HUD)
        self.calib_session: int = 0  # bumps on every start, so the HUD can clear its canvas
        self.calib_progress: float = 0.0  # 0..1, bundle length / target
        self.calib_estimate: Optional[float] = None  # current axis estimate (radians, aspect units)
        self.calib_center: Optional[Tuple[float, float]] = None  # bundle centre, normalized image
        self._calib_stroke: list = []  # pen points of the stroke being drawn (aspect units)
        self._calib_data: list = []  # committed (dx, dy) steps (aspect units)
        self._calib_points_all: list = []  # committed pen points (aspect units)
        self._calib_first_moves: list = []  # first clear move of each stroke (unit vectors)
        self._calib_move_seen: bool = False
        self._calib_done: bool = False
        self.calib_phase: str = "x"  # "x" = direction sweep, "corners" = monitor corners
        self.calib_step_no: int = 1
        self.calib_step_count: int = 1
        self._calib_queue: list = []
        self.corner_index: int = 0
        self.corner_values: Dict[str, Tuple[float, float]] = {}  # name -> (turn angle, openness)
        self._corner_samples: list = []
        self._corner_t0: Optional[float] = None
        self.corner_hold: float = 0.0  # 0..1 how long the current corner has been held
        self._sweep_move_range: Optional[Tuple[float, float]] = None  # step-1 left/right reach

        # Recent per-frame pinch data for the D (debug dump) key
        self.debug_log: deque = deque(maxlen=180)

    # ------------------------------------------------------------------ config

    @property
    def is_pinched(self) -> bool:
        """Whether the pen is down (thumb+index, or the drag combo) right now."""
        return self._active in ("index", DRAG_COMBO)

    @property
    def active_finger(self) -> Optional[str]:
        return self._active

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
        """Switch cursor movement mode: 'range' (hand range = monitor), 'relative' (pen), 'absolute'."""
        mode_norm = mode.strip().lower()
        if mode_norm not in VALID_MOVEMENT_MODES:
            raise ValueError(f"Invalid movement_mode '{mode}'. Choose from {sorted(VALID_MOVEMENT_MODES)}")
        self.config["movement_mode"] = mode_norm

    def set_dpi_scale(self, dpi_scale: float) -> float:
        """Set cursor speed multiplier (clamped between 0.2 and 10.0)."""
        val = round(max(0.2, min(10.0, float(dpi_scale))), 2)
        self.config["dpi_scale"] = val
        return val

    # ------------------------------------------------------- paper direction

    @property
    def is_calibrated(self) -> bool:
        """Whether the paper's up direction was locked by the user."""
        return self._user_calibrated

    def calibrate_neutral(self) -> bool:
        """
        Lock the current hand direction (wrist -> knuckles) as the paper's "up"
        (= screen up). Use it when the camera looks at the desk from an odd angle.
        Returns False when no hand has been seen yet.
        """
        if self._last_hand_angle is None:
            return False
        self.forward_angle = self._last_hand_angle
        self._user_calibrated = True
        return True

    def clear_calibration(self) -> None:
        """Go back to automatic (90-degree snapped) paper direction."""
        self._user_calibrated = False
        self._hand_dir = None

    def _update_auto_direction(self, angle: float) -> None:
        """Track the idle hand direction and snap the paper to the nearest 90 degrees."""
        ux, uy = math.sin(angle), -math.cos(angle)
        if self._hand_dir is None:
            self._hand_dir = (ux, uy)
        else:
            hx = 0.9 * self._hand_dir[0] + 0.1 * ux
            hy = 0.9 * self._hand_dir[1] + 0.1 * uy
            self._hand_dir = (hx, hy)
        smoothed = math.atan2(self._hand_dir[0], -self._hand_dir[1])
        diff = math.atan2(math.sin(smoothed - self.forward_angle), math.cos(smoothed - self.forward_angle))
        # Hysteresis: only re-snap when the hand clearly points into another quadrant.
        if abs(diff) > math.radians(60):
            self.forward_angle = round(smoothed / (math.pi / 2)) * (math.pi / 2)

    # ------------------------------------------------------------------ state

    def reset(self) -> None:
        """Reset transient pinch state (e.g., when the hand leaves the frame)."""
        self._lm_filters = []
        self._active = None
        self._candidate = None
        self._candidate_frames = 0
        self._last_pen = None
        self.last_pen_image = None

    def _smooth_landmarks(self, pts: List[Point3D], now: float) -> List[Point3D]:
        """Steady the 21 landmarks themselves, so the cursor and the pinch distances
        both see less camera jitter."""
        if not bool(self.config.get("landmark_filter", True)):
            return pts
        if len(getattr(self, "_lm_filters", [])) != len(pts):
            self._lm_filters = [(_OneEuro(), _OneEuro()) for _ in pts]
        mc = float(self.config.get("landmark_min_cutoff", 1.5))
        beta = float(self.config.get("landmark_beta", 8.0))
        out = []
        for p, (fx, fy) in zip(pts, self._lm_filters):
            out.append(Point3D(fx(p.x, now, mc, beta), fy(p.y, now, mc, beta), p.z))
        return out

    def _gesture_cfg(self, gesture_id: str) -> Dict[str, Any]:
        return self.config.get("gestures", {}).get(gesture_id, {})

    def _is_enabled(self, gesture_id: str) -> bool:
        cfg = self._gesture_cfg(gesture_id)
        return bool(cfg.get("enabled", False)) and cfg.get("action", "none") != "none"

    def _action_of(self, key: str) -> str:
        gesture_id = DRAG_GESTURE if key == DRAG_COMBO else FINGER_GESTURES[key]
        return str(self._gesture_cfg(gesture_id).get("action", "none"))

    def _can_trigger(self, gesture_id: str, now: float) -> bool:
        cfg = self._gesture_cfg(gesture_id)
        cooldown = float(cfg.get("cooldown", 0.15))
        last_time = self._last_trigger_times.get(gesture_id, -1e9)
        if (now - last_time) >= cooldown:
            self._last_trigger_times[gesture_id] = now
            return True
        return False

    def _enter_threshold(self, key: str) -> float:
        if key == "index" or self._action_of(key) in CONTINUOUS_ACTIONS:
            return float(self.config.get("pinch_threshold", 0.055))
        return float(self.config.get("click_threshold", 0.075))

    def enter_thresholds(self) -> Dict[str, float]:
        """Pinch distance each finger must reach (for the on-screen distance labels)."""
        return {name: self._enter_threshold(name) for name in FINGERS}

    def _release_threshold(self, key: str) -> float:
        rel = float(self.config.get("release_threshold", 0.080))
        return max(rel, self._enter_threshold(key) + 0.015)

    def _confirm_frames(self, key: str) -> int:
        if key == "index" or self._action_of(key) in CONTINUOUS_ACTIONS:
            return 1
        return max(1, int(self.config.get("click_confirm_frames", 2)))

    # ---------------------------------------------------------------- process

    def process(
        self,
        landmarks: Optional[Sequence[Any]],
        timestamp: Optional[float] = None,
        image_size: Optional[Tuple[int, int]] = None,
    ) -> GestureResult:
        """
        Evaluate 21 hand landmarks and return a GestureResult.
        `image_size` = (width, height) of the camera frame, used to undo the
        non-square normalization of MediaPipe x/y coordinates.
        """
        if not landmarks or len(landmarks) < 21:
            self.reset()
            return GestureResult()

        now = float(timestamp) if timestamp is not None else time.perf_counter()
        if image_size and image_size[1] > 0:
            self.aspect = float(image_size[0]) / float(image_size[1])
        else:
            self.aspect = 1.0
        a = self.aspect

        raw = self._smooth_landmarks([Point3D.from_any(lm) for lm in landmarks[:21]], now)
        # 2D isotropic coordinates in units of image height (depth is not used).
        pts = [(p.x * a, p.y) for p in raw]

        def d2(i: int, j: int) -> float:
            return math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1])

        def dist(p: Tuple[float, float], q: Tuple[float, float]) -> float:
            return math.hypot(p[0] - q[0], p[1] - q[1])

        ref_palm = float(self.config.get("reference_palm_size", 0.22))
        palm_raw = max(
            d2(self.WRIST, self.MIDDLE_MCP),
            d2(self.WRIST, self.INDEX_MCP),
            d2(self.INDEX_MCP, self.PINKY_MCP),
        )
        real_palm = palm_raw > 0.04
        palm = palm_raw if real_palm else ref_palm
        if real_palm:
            self.palm_size = 0.8 * self.palm_size + 0.2 * palm_raw

        # Thumb-to-finger distance: closest of tip and finger pad (between DIP and tip).
        thumb = pts[self.THUMB_TIP]
        distances: Dict[str, float] = {}
        for name in FINGERS:
            tip = pts[FINGER_TIPS[name]]
            d = dist(thumb, tip)
            if real_palm:
                # The thumb touches the finger pad: distance to the last segment (DIP -> tip).
                d = min(d, _point_segment_distance(thumb, pts[FINGER_DIPS[name]], tip))
            distances[name] = d / palm * ref_palm

        if self.thumb_mode:
            # Thumb mode: the thumb roams over the hand, so touching fingers is not a click.
            self._active = None
            self._candidate = None
            fired = False
        else:
            fired = self._update_pinch_state(distances, now)
        self.debug_log.append(
            {
                "t": round(now, 3),
                **{f"d_{k}": round(v, 4) for k, v in distances.items()},
                "palm": round(palm_raw, 4),
                "active": self._active or "",
                "candidate": self._candidate or "",
                "fired": int(fired),
            }
        )

        # Openness of middle+ring+pinky: fingertip-to-wrist distance over palm size.
        if real_palm:
            wrist = pts[self.WRIST]
            openness = sum(dist(pts[FINGER_TIPS[f]], wrist) for f in ("middle", "ring", "pinky")) / (3.0 * palm)
            self._curl = openness if self._curl is None else 0.5 * self._curl + 0.5 * openness
            # Turn of the hand: direction from the wrist to the middle of all four knuckles.
            # Knuckles stay put while fingers curl or pinch, so up/down does not leak into it.
            kx = sum(pts[i][0] for i in (5, 9, 13, 17)) / 4.0 - wrist[0]
            ky = sum(pts[i][1] for i in (5, 9, 13, 17)) / 4.0 - wrist[1]
            yaw = math.atan2(kx, -ky)
            self._yaw = yaw if self._yaw is None else self._yaw + 0.5 * _wrap(yaw - self._yaw)
            # Thumb tip inside the hand: origin wrist, "up" = wrist -> middle knuckle, unit = palm.
            ux, uy = pts[self.MIDDLE_MCP][0] - wrist[0], pts[self.MIDDLE_MCP][1] - wrist[1]
            n = math.hypot(ux, uy) or 1.0
            ux, uy = ux / n, uy / n
            rx, ry = -uy, ux  # perpendicular, across the hand
            dx, dy = thumb[0] - wrist[0], thumb[1] - wrist[1]
            tp = ((dx * rx + dy * ry) / palm, (dx * ux + dy * uy) / palm)
            if self._thumb is None:
                self._thumb = tp
            else:
                self._thumb = (0.5 * self._thumb[0] + 0.5 * tp[0], 0.5 * self._thumb[1] + 0.5 * tp[1])
            self._hand_frame = (wrist, (rx, ry), (ux, uy), palm)
            # How straight index and middle are (independent of hand size and place).
            on = float(self.config.get("extend_on_ratio", 1.55))
            off = float(self.config.get("extend_off_ratio", 1.35))
            for name, mcp in (("index", self.INDEX_MCP), ("middle", self.MIDDLE_MCP)):
                ratio = dist(pts[FINGER_TIPS[name]], wrist) / max(1e-6, dist(pts[mcp], wrist))
                self._extension[name] = ratio
                if self._extended[name] and ratio < off:
                    self._extended[name] = False
                elif not self._extended[name] and ratio > on:
                    self._extended[name] = True

        # Hand direction (wrist -> knuckles) for the paper's up axis.
        knuckle = (
            0.4 * pts[self.INDEX_MCP][0] + 0.4 * pts[self.MIDDLE_MCP][0] + 0.2 * pts[self.PINKY_MCP][0],
            0.4 * pts[self.INDEX_MCP][1] + 0.4 * pts[self.MIDDLE_MCP][1] + 0.2 * pts[self.PINKY_MCP][1],
        )
        if real_palm:
            vx = knuckle[0] - pts[self.WRIST][0]
            vy = knuckle[1] - pts[self.WRIST][1]
            self._last_hand_angle = math.atan2(vx, -vy)
            if not self._user_calibrated and self._active is None:
                self._update_auto_direction(self._last_hand_angle)

        # Pen point: the palm centre (wrist + four knuckles). These joints are tracked far
        # more steadily than fingertips and do not move when the thumb pinches or clicks.
        # pen_finger_weight mixes in some of the pinch point.
        pinch_mid = ((thumb[0] + pts[8][0]) * 0.5, (thumb[1] + pts[8][1]) * 0.5)
        if real_palm:
            centre = (
                sum(pts[i][0] for i in (0, 5, 9, 13, 17)) / 5.0,
                sum(pts[i][1] for i in (0, 5, 9, 13, 17)) / 5.0,
            )
            w_f = max(0.0, min(1.0, float(self.config.get("pen_finger_weight", 0.0))))
            pen = (
                (1.0 - w_f) * centre[0] + w_f * pinch_mid[0],
                (1.0 - w_f) * centre[1] + w_f * pinch_mid[1],
            )
        else:
            pen = pinch_mid
        self.last_pen_image = (pen[0] / a, pen[1])

        moving = self._active is not None and self._action_of(self._active) in CONTINUOUS_ACTIONS
        if self.calibrating:
            self._calibration_step(pen, moving and self._active == "index", now)
            moving = False
            fired = False
        curl_step = 0.0
        if self._curl is not None and self._last_curl is not None:
            curl_step = self._curl - self._last_curl
        self._last_curl = self._curl
        if moving:
            hand_angle = self._last_hand_angle if real_palm else None
            if self._last_pen is None:
                self._stroke_ref_angle = hand_angle
                self._stroke_angle = hand_angle or 0.0
            else:
                turn = 0.0
                if hand_angle is not None and self._stroke_ref_angle is not None:
                    step = _wrap(hand_angle - self._stroke_angle)
                    self._stroke_angle += 0.5 * step  # light smoothing against landmark jitter
                    if bool(self.config.get("straighten_arcs", True)):
                        turn = _wrap(self._stroke_angle - self._stroke_ref_angle)
                self._advance_paper(pen[0] - self._last_pen[0], pen[1] - self._last_pen[1], turn, curl_step)
            self._last_pen = pen
        else:
            self._last_pen = None
            self._stroke_ref_angle = None

        result = GestureResult(
            timestamp=now,
            cursor_point=self.last_pen_image,
            paper_point=self._paper,
            pinch_distance=distances["index"],
            distances=distances,
            curl=self._curl,
            calibrating=self.calibrating,
            screen_point=(
                self.screen_point_for(self._yaw, self.hand_move(pen), self._curl)
                if self._curl is not None and self._yaw is not None
                else None
            ),
            pending_gesture=(
                self._gesture_id(self._candidate) if self._candidate and self._candidate_frames > 0 else None
            ),
        )
        result.thumb_point = self._thumb
        result.extension = dict(self._extension)
        result.click_forming = not self.calibrating and any(
            k is not None and k in FINGERS and self._action_of(k) not in CONTINUOUS_ACTIONS
            for k in (self._candidate, self._active)
        )
        if self.thumb_mode and not self.calibrating:
            fired_click = self._extend_click(real_palm, now)
            self._thumb_cursor(result, now)
            if self._click_candidate:
                result.pending_gesture = self._click_candidate
            if self._click_latched:
                result.active_gesture = self._click_latched
            if fired_click:
                result.action = self._action_of_gesture(fired_click)
            return result
        if self._active is None or self.calibrating:
            return result

        gesture_id = self._gesture_id(self._active)
        action = self._action_of(self._active)
        result.active_gesture = gesture_id
        if action in CONTINUOUS_ACTIONS:
            result.action = action
            result.is_moving = True
        elif fired:
            result.action = action
        return result

    @staticmethod
    def _gesture_id(key: str) -> str:
        return DRAG_GESTURE if key == DRAG_COMBO else FINGER_GESTURES[key]

    def _update_pinch_state(self, dist: Dict[str, float], now: float) -> bool:
        """Advance the pinch state machine. Returns True when a discrete action fires this frame."""
        sep = float(self.config.get("finger_separation", 0.75))
        drag_on = self._is_enabled(DRAG_GESTURE)

        def combo_dist() -> float:
            return max(dist["index"], dist["middle"])

        # 1. Keep or drop the current pinch (hysteresis).
        if self._active is not None:
            cur = combo_dist() if self._active == DRAG_COMBO else dist[self._active]
            if cur > self._release_threshold(self._active):
                self._active = None

        # 2. Find the finger that is clearly the one touching the thumb.
        best: Optional[str] = None
        if drag_on and dist["index"] <= self._release_threshold("index") and dist["middle"] <= self._enter_threshold(
            DRAG_COMBO
        ) * 1.2:
            best = DRAG_COMBO
        else:
            # The closest finger must be clearly closer than the next finger that has an
            # action: a pinky curling along with the ring (pinky gesture off) must not block
            # a ring pinch. A disabled finger that is itself the closest still wins (no click).
            first = min(FINGERS, key=lambda f: dist[f])
            # Thumb mode: the thumb moves freely over the hand; touching the index is not a pinch.
            index_off = self.thumb_mode and first == "index"
            others = [dist[f] for f in FINGERS if f != first and self._is_enabled(FINGER_GESTURES[f])]
            second_dist = min(others) if others else float("inf")
            if self._action_of(first) not in CONTINUOUS_ACTIONS:
                sep = float(self.config.get("click_separation", 0.8))
            clearly_closest = dist[first] <= sep * second_dist
            # The thumb slides past the index tip on its way to the middle/ring tip, so the
            # pen often goes down first. Once another finger is closer than the active one,
            # let it take over even if the active finger is still near.
            window = float(self.config.get("pen_takeover_window_s", 0.25))
            takes_over = (
                self._active is not None
                and first != self._active
                and self._action_of(self._active) in CONTINUOUS_ACTIONS
                and self._action_of(first) not in CONTINUOUS_ACTIONS
                and dist[first] < 0.9 * dist[self._active]
                and self._pen_down_t is not None
                and now - self._pen_down_t <= window
            )
            # Up/down from the hand moving (not finger curl): fingers do not curl while the
            # pen is down, so a click finger that is clearly closer than the index always
            # takes over, however long the thumb rested on the index first.
            if (
                not takes_over
                and str(self.config.get("vertical_source", "fingers")).lower() != "fingers"
                and self._active is not None
                and self._action_of(self._active) in CONTINUOUS_ACTIONS
                and self._action_of(first) not in CONTINUOUS_ACTIONS
                and clearly_closest
            ):
                takes_over = True
            # While the pen is down (past the slide-by window) fingers curl for up/down;
            # a click needs the pen lifted first.
            pen_locked = (
                self._active is not None
                and self._action_of(self._active) in CONTINUOUS_ACTIONS
                and self._action_of(first) not in CONTINUOUS_ACTIONS
                and not takes_over
            )
            if (
                not index_off
                and dist[first] <= self._enter_threshold(first)
                and (clearly_closest or takes_over)
                and not pen_locked
                and self._is_enabled(FINGER_GESTURES[first])
            ):
                best = first

        # A held click is never handed to another click finger (neighbours bend along);
        # the thumb has to let go first.
        if (
            best is not None
            and self._active is not None
            and self._action_of(self._active) not in CONTINUOUS_ACTIONS
            and self._action_of(best) not in CONTINUOUS_ACTIONS
        ):
            best = self._active

        if best is None or best == self._active:
            self._candidate = None
            self._candidate_frames = 0
            return False

        # 3. A new pinch must hold for a few frames before it takes over.
        if best == self._candidate:
            self._candidate_frames += 1
        else:
            self._candidate = best
            self._candidate_frames = 1
        if self._candidate_frames < self._confirm_frames(best):
            return False

        self._active = best
        self._candidate = None
        self._candidate_frames = 0
        if self._action_of(best) in CONTINUOUS_ACTIONS:
            self._pen_down_t = now
            return False
        return self._can_trigger(self._gesture_id(best), now)

    # ------------------------------------------------- horizontal calibration

    @property
    def x_axis_angle(self) -> Optional[float]:
        """Calibrated horizontal axis in the image (radians, aspect-corrected), or None."""
        deg = self.config.get("paper_x_angle_deg")
        if deg is None:
            return None
        return math.radians(float(deg) + float(self.config.get("paper_rotation_deg", 0.0)))

    def start_calibration(self, phases: Sequence[str] = ("x", "corners")) -> None:
        """Start the calibration: "x" = sweep left/right, "corners" = the four monitor corners."""
        self._calib_queue = [ph for ph in phases if ph in ("x", "corners", "thumb")] or ["x"]
        self._sweep_move_range = None
        self.calib_step_count = len(self._calib_queue)
        self.calib_step_no = 0
        self.calibrating = True
        self._calib_done = False
        self._next_calib_phase()

    def _next_calib_phase(self) -> None:
        """Begin the next queued step, or finish when none is left."""
        if not self._calib_queue:
            self.calibrating = False
            self.calib_state = "idle"
            self._calib_done = True
            return
        self.calib_phase = self._calib_queue.pop(0)
        self.calib_step_no += 1
        self.calib_state = "wait"
        self.calib_session += 1
        self.calib_segments = []
        self.calib_progress = 0.0
        self.calib_estimate = None
        self.calib_center = None
        self._calib_stroke = []
        self._calib_data = []
        self._calib_points_all = []
        self._calib_first_moves = []
        self._calib_move_seen = False
        self.corner_index = 0
        self.corner_values = {}
        self._corner_samples = []
        self._corner_t0 = None
        self.corner_hold = 0.0
        self._thumb_still = []
        self._thumb_armed = True

    def cancel_calibration(self) -> None:
        self.calibrating = False
        self.calib_state = "idle"
        self.calib_segments = []
        self._calib_stroke = []
        self._calib_queue = []
        self._corner_samples = []

    def curl_range(self) -> Tuple[float, float]:
        """(closed, open) openness of middle+ring+pinky; measured or a typical default."""
        op, cl = self.config.get("curl_open"), self.config.get("curl_closed")
        if op is None or cl is None or float(op) - float(cl) < 0.05:
            return 1.0, 1.9
        return float(cl), float(op)

    def clear_x_calibration(self) -> None:
        """Forget the measured horizontal axis (falls back to the hand direction)."""
        self.config["paper_x_angle_deg"] = None

    def pop_calibration_done(self) -> bool:
        """True once after a calibration has just finished."""
        done, self._calib_done = self._calib_done, False
        return done

    def _calibration_step(self, pen: Tuple[float, float], pen_down: bool, now: float = 0.0) -> None:
        if self.calib_phase == "thumb":
            self._thumb_corner_step(now)
            return
        if self.calib_phase == "corners":
            self._corner_step(pen, pen_down, now)
            return
        a = self.aspect or 1.0
        if pen_down:
            if self._calib_stroke:
                prev = self._calib_stroke[-1]
                self.calib_segments.append(((prev[0] / a, prev[1]), (pen[0] / a, pen[1])))
            self._calib_stroke.append(pen)
            self.calib_state = "drawing"
            # The first clear move of each stroke; the first one along the bundle says "right".
            if not self._calib_move_seen:
                x0, y0 = self._calib_stroke[0]
                dx, dy = pen[0] - x0, pen[1] - y0
                n = math.hypot(dx, dy)
                if n >= 0.5 * max(0.02, self.palm_size):
                    self._calib_first_moves.append((dx / n, dy / n))
                    self._calib_move_seen = True
            if len(self._calib_stroke) % 5 == 0:  # live progress while sweeping
                core = self._calib_stroke[2:]
                self._update_calib_estimate([(x1 - x0, y1 - y0) for (x0, y0), (x1, y1) in zip(core, core[1:])], core)
            return
        if not self._calib_stroke:
            return
        # Pen lifted: keep the stroke without its first/last frames (pinch on/off wobble).
        stroke, self._calib_stroke = self._calib_stroke, []
        self._calib_move_seen = False
        core = stroke[2:-2] if len(stroke) > 6 else []
        for (x0, y0), (x1, y1) in zip(core, core[1:]):
            self._calib_data.append((x1 - x0, y1 - y0))
        self._calib_points_all.extend(core)
        ready = self.calib_progress >= 1.0  # the screen already said "enough"
        self._update_calib_estimate()
        if (ready or self.calib_progress >= 1.0) and self.calib_estimate is not None:
            self._finish_calibration()
        else:
            self.calib_state = "more"

    def _update_calib_estimate(self, extra_steps: Sequence = (), extra_points: Sequence = ()) -> None:
        """Densest direction bundle of all sweep steps (axial, so left and right sweeps agree).
        `extra_*` = the stroke still being drawn (for live progress)."""
        steps = [(dx, dy) for dx, dy in list(self._calib_data) + list(extra_steps) if math.hypot(dx, dy) > 1e-4]
        if not steps:
            return
        bins = 90  # 2-degree bins over 180 degrees
        hist = [0.0] * bins
        for dx, dy in steps:
            theta = math.atan2(dy, dx) % math.pi
            hist[int(theta / math.pi * bins) % bins] += math.hypot(dx, dy)
        smooth = [sum(hist[(k + o) % bins] for o in range(-3, 4)) for k in range(bins)]
        peak = (smooth.index(max(smooth)) + 0.5) * math.pi / bins
        limit = math.radians(float(self.config.get("calib_bundle_deg", 20.0)))
        cx = cy = inside = 0.0
        for dx, dy in steps:
            theta = math.atan2(dy, dx)
            if abs(_wrap(2.0 * (theta - peak))) / 2.0 <= limit:
                w = math.hypot(dx, dy)
                cx += w * math.cos(2.0 * theta)
                cy += w * math.sin(2.0 * theta)
                inside += w
        if inside <= 0:
            return
        axis = 0.5 * math.atan2(cy, cx)
        # Stray strokes are skipped here too: the first stroke that starts along the bundle
        # was the "start to the right" move.
        for ux, uy in self._calib_first_moves:
            along = math.cos(axis) * ux + math.sin(axis) * uy
            if abs(along) >= math.cos(limit * 1.5):
                if along < 0:
                    axis += math.pi
                break
        self.calib_estimate = _wrap(axis)
        target = float(self.config.get("calib_target_length", 6.0))
        self.calib_progress = min(1.0, inside / max(0.02, self.palm_size) / max(0.1, target))
        pts = list(self._calib_points_all) + list(extra_points)
        if pts:
            a = self.aspect or 1.0
            self.calib_center = (sum(p[0] for p in pts) / len(pts) / a, sum(p[1] for p in pts) / len(pts))

    def _finish_calibration(self) -> None:
        self.config["paper_x_angle_deg"] = round(math.degrees(self.calib_estimate), 1)
        self.config["paper_rotation_deg"] = 0.0
        # How far the hand travelled left/right while sweeping (fallback for the corners).
        us = sorted(self.hand_move(p) for p in self._calib_points_all)
        if len(us) >= 10:
            self._sweep_move_range = (us[int(0.05 * (len(us) - 1))], us[int(0.95 * (len(us) - 1))])
        # The first sweep went to the right, so the axis already points to screen right.
        self.config["paper_invert_x"] = False
        self._next_calib_phase()

    # ------------------------------------------------- corners / range mode

    def hand_move(self, pen: Tuple[float, float]) -> float:
        """Hand position along the horizontal line (step 1), in palm widths."""
        axis = self.x_axis_angle or 0.0
        return (pen[0] * math.cos(axis) + pen[1] * math.sin(axis)) / max(0.02, self.palm_size)

    @property
    def range_x_source(self) -> str:
        return "move" if str(self.config.get("range_x_source", "turn")) == "move" else "turn"

    @property
    def range_ready(self) -> bool:
        x_keys = ("range_left_pos", "range_right_pos") if self.range_x_source == "move" else (
            "range_left_deg", "range_right_deg")
        return all(self.config.get(k) is not None for k in x_keys + ("range_top", "range_bottom"))

    def screen_point_for(self, yaw: float, move: float, openness: float) -> Optional[Tuple[float, float]]:
        """Range mode: hand pose -> screen (0..1). None if not calibrated."""
        if not self.range_ready:
            return None
        top, bottom = float(self.config["range_top"]), float(self.config["range_bottom"])
        if self.range_x_source == "move":
            left, right = float(self.config["range_left_pos"]), float(self.config["range_right_pos"])
            span, pos = right - left, move - left
        else:
            left = math.radians(float(self.config["range_left_deg"]))
            right = math.radians(float(self.config["range_right_deg"]))
            span, pos = _wrap(right - left), _wrap(yaw - left)
        if abs(span) < 1e-3 or abs(bottom - top) < 1e-6:
            return None
        m = float(self.config.get("range_margin", 0.04))
        nx = pos / span * (1.0 + 2.0 * m) - m
        ny = (openness - top) / (bottom - top) * (1.0 + 2.0 * m) - m
        if bool(self.config.get("paper_invert_x", False)):
            nx = 1.0 - nx
        if bool(self.config.get("flip_x", False)):
            nx = 1.0 - nx
        return max(0.0, min(1.0, nx)), max(0.0, min(1.0, ny))

    @property
    def corner_target(self) -> Optional[Tuple[str, float, float]]:
        if self.calibrating and self.calib_phase in ("corners", "thumb") and self.corner_index < len(CORNERS):
            return CORNERS[self.corner_index]
        return None

    def _corner_step(self, pen: Tuple[float, float], pen_down: bool, now: float) -> None:
        hold = float(self.config.get("corner_hold_s", 0.6))
        settle = float(self.config.get("corner_settle_s", 0.15))
        if pen_down and self._curl is not None:
            if self._corner_t0 is None:
                self._corner_t0 = now
                self._corner_samples = []
            held = now - self._corner_t0
            if held >= settle and self._yaw is not None:
                self._corner_samples.append((self._yaw, self.hand_move(pen), self._curl))
            self.corner_hold = min(1.0, held / max(1e-3, hold))
            self.calib_state = "ok" if held >= hold else "holding"
            self.calib_progress = (self.corner_index + self.corner_hold) / len(CORNERS)
            return
        if self._corner_t0 is None:
            return
        held_long = self.calib_state == "ok" and len(self._corner_samples) >= 2
        samples, self._corner_samples = self._corner_samples, []
        self._corner_t0 = None
        self.corner_hold = 0.0
        if not held_long:
            self.calib_state = "short"
            self.calib_progress = self.corner_index / len(CORNERS)
            return
        ref = samples[0][0]
        yaws = sorted(ref + _wrap(v[0] - ref) for v in samples)  # angles near each other
        moves = sorted(v[1] for v in samples)
        cs = sorted(v[2] for v in samples)
        name = CORNERS[self.corner_index][0]
        k = len(samples) // 2
        self.corner_values[name] = (_wrap(yaws[k]), moves[k], cs[k])
        self.corner_index += 1
        self.calib_progress = self.corner_index / len(CORNERS)
        if self.corner_index < len(CORNERS):
            self.calib_state = "wait"
            return
        self._finish_corners()

    def _finish_corners(self) -> None:
        v = self.corner_values
        top = (v["tl"][2] + v["tr"][2]) / 2.0
        bottom = (v["bl"][2] + v["br"][2]) / 2.0
        if top - bottom < float(self.config.get("curl_min_range", 0.25)) * 0.6:
            self._restart_corners("narrow_y")
            return
        # Left/right: the wrist turn and the hand move between the left and right corners.
        left_yaw = _wrap(v["tl"][0] + 0.5 * _wrap(v["bl"][0] - v["tl"][0]))
        right_yaw = _wrap(v["tr"][0] + 0.5 * _wrap(v["br"][0] - v["tr"][0]))
        left_move = (v["tl"][1] + v["bl"][1]) / 2.0
        right_move = (v["tr"][1] + v["br"][1]) / 2.0
        turn_score = abs(math.degrees(_wrap(right_yaw - left_yaw))) / float(self.config.get("range_min_turn_deg", 12.0))
        move_score = abs(right_move - left_move) / float(self.config.get("range_min_move", 0.6))
        update: Dict[str, Any] = {}
        if max(turn_score, move_score) >= 1.0:
            if turn_score >= move_score:
                update.update(range_x_source="turn", range_left_deg=round(math.degrees(left_yaw), 2),
                              range_right_deg=round(math.degrees(right_yaw), 2))
            else:
                update.update(range_x_source="move", range_left_pos=round(left_move, 3),
                              range_right_pos=round(right_move, 3))
        elif self._sweep_move_range is not None:
            # The corners barely differ left/right: use how far the hand went in step 1.
            lo, hi = self._sweep_move_range
            update.update(range_x_source="move", range_left_pos=round(lo, 3), range_right_pos=round(hi, 3))
        else:
            self._restart_corners("narrow_x")
            return
        update.update(
            range_top=round(top, 3),
            range_bottom=round(bottom, 3),
            # The same openness range also scales up/down in the pen (relative) mode.
            curl_open=round(top, 3),
            curl_closed=round(bottom, 3),
            movement_mode="range",
            # The calibrated left/right already sets the direction.
            paper_invert_x=False,
        )
        self.config.update(update)
        self._next_calib_phase()

    def _restart_corners(self, reason: str) -> None:
        self.corner_index = 0
        self.corner_values = {}
        self.calib_progress = 0.0
        self.calib_state = reason

    # ------------------------------------------------- thumb mode

    @property
    def thumb_mode(self) -> bool:
        return str(self.config.get("movement_mode", "relative")).lower() == "thumb"

    @property
    def thumb_ready(self) -> bool:
        corners = self.config.get("thumb_corners")
        return isinstance(corners, (list, tuple)) and len(corners) == 4

    def calibration_phases(self) -> Tuple[str, ...]:
        """The calibration that fits the current movement mode."""
        mode = str(self.config.get("movement_mode", "relative")).lower()
        if mode == "thumb":
            return ("thumb",)
        return ("x", "corners")

    def is_mode_calibrated(self) -> bool:
        if self.thumb_mode:
            return self.thumb_ready
        if str(self.config.get("movement_mode", "relative")).lower() == "range":
            return self.range_ready and self.config.get("paper_x_angle_deg") is not None
        return self.config.get("paper_x_angle_deg") is not None

    def _thumb_h(self) -> Optional[list]:
        """Homography from thumb hand-coordinates to the screen (corners slightly outside)."""
        corners = self.config.get("thumb_corners")
        if not self.thumb_ready:
            return None
        if self._homography is not None and self._homography_src == corners:
            return self._homography
        m = float(self.config.get("range_margin", 0.04))
        dst = [(-m, -m), (1 + m, -m), (1 + m, 1 + m), (-m, 1 + m)]
        self._homography = _homography([tuple(c) for c in corners], dst)
        self._homography_src = [list(c) for c in corners]
        return self._homography

    def thumb_screen_point(self, tp: Tuple[float, float]) -> Optional[Tuple[float, float]]:
        h = self._thumb_h()
        if h is None:
            return None
        x, y = _apply_homography(h, tp)
        return max(0.0, min(1.0, x)), max(0.0, min(1.0, y))

    def hand_to_image(self, tp: Tuple[float, float]) -> Optional[Tuple[float, float]]:
        """Hand coordinates -> normalized image point (for drawing on the camera view)."""
        if self._hand_frame is None:
            return None
        (wx, wy), (rx, ry), (ux, uy), palm = self._hand_frame
        x = wx + (tp[0] * rx + tp[1] * ux) * palm
        y = wy + (tp[0] * ry + tp[1] * uy) * palm
        return x / (self.aspect or 1.0), y

    def _thumb_cursor(self, result: GestureResult, now: float) -> None:
        """Thumb mode: cursor follows the thumb; held still while the thumb clicks."""
        point = self.thumb_screen_point(self._thumb) if self._thumb is not None else None
        if point is not None:
            self._thumb_hist.append((now, point))
        while self._thumb_hist and now - self._thumb_hist[0][0] > 1.0:
            self._thumb_hist.popleft()

        clicking = self._click_candidate is not None or self._click_latched is not None
        if clicking:
            if self._freeze_point is None:
                lookback = float(self.config.get("click_freeze_lookback_s", 0.25))
                before = [p for t, p in self._thumb_hist if t <= now - lookback]
                self._freeze_point = before[-1] if before else (
                    self._thumb_hist[0][1] if self._thumb_hist else point)
            self._freeze_until = float("inf")
        elif self._freeze_point is not None:
            if self._freeze_until == float("inf"):
                self._freeze_until = now + float(self.config.get("click_release_hold_s", 0.35))
            elif now >= self._freeze_until:
                self._freeze_point = None

        if self._freeze_point is not None:
            result.hold_point = self._freeze_point
            result.screen_point = self._freeze_point
            result.is_moving = False
            return
        result.screen_point = point
        if point is not None:
            result.is_moving = True
            result.action = "move_cursor"
            result.active_gesture = "thumb"

    def _action_of_gesture(self, gesture_id: str) -> str:
        return str(self._gesture_cfg(gesture_id).get("action", "none"))

    def _extend_click(self, seen: bool, now: float) -> Optional[str]:
        """Thumb mode clicks: index out = left, index + middle out = right.
        Returns the gesture id that fires this frame, if any."""
        if not seen:
            return None
        ix, mid = self._extended["index"], self._extended["middle"]
        if not ix and not mid:
            pose = None  # neutral: both curled -> arm the next click
        elif ix and mid:
            pose = "index_middle_extend"
        elif ix:
            pose = "index_extend"
        else:
            pose = "other"  # middle alone: ignore
        if pose is None:
            self._click_armed = True
            self._click_latched = None
            self._click_candidate = None
            return None
        if not self._click_armed or self._click_latched is not None or pose == "other":
            self._click_candidate = None
            return None
        if not self._is_enabled(pose):
            self._click_candidate = None
            return None
        if pose != self._click_candidate:
            # A new pose (e.g. the middle joins the index): restart the wait, so a slow
            # right click does not first fire a left click.
            self._click_candidate = pose
            self._click_t0 = now
            return None
        if now - self._click_t0 < float(self.config.get("extend_confirm_s", 0.15)):
            return None
        self._click_candidate = None
        self._click_latched = pose
        self._click_armed = False
        return pose if self._can_trigger(pose, now) else None

    def _thumb_corner_step(self, now: float) -> None:
        """Capture a corner when the thumb has been held still long enough."""
        if self._thumb is None:
            return
        hold = float(self.config.get("thumb_hold_s", 0.7))
        tol = float(self.config.get("thumb_still_tol", 0.04))
        tp = self._thumb
        if not self._thumb_armed:
            last = self.corner_values.get(CORNERS[self.corner_index - 1][0]) if self.corner_index else None
            if last is None or math.hypot(tp[0] - last[0], tp[1] - last[1]) >= float(
                self.config.get("thumb_rearm_dist", 0.12)
            ):
                self._thumb_armed = True
                self._thumb_still = []
            else:
                self.calib_state = "move_on"
                return
        self._thumb_still.append((now, tp))
        # Keep only the recent run of samples that stay close together.
        while len(self._thumb_still) > 1:
            mx = sum(p[0] for _, p in self._thumb_still) / len(self._thumb_still)
            my = sum(p[1] for _, p in self._thumb_still) / len(self._thumb_still)
            if all(math.hypot(p[0] - mx, p[1] - my) <= tol for _, p in self._thumb_still):
                break
            self._thumb_still.pop(0)
        held = self._thumb_still[-1][0] - self._thumb_still[0][0]
        self.corner_hold = min(1.0, held / max(1e-3, hold))
        self.calib_state = "holding" if held > 0.1 else "wait"
        self.calib_progress = (self.corner_index + self.corner_hold) / len(CORNERS)
        if held < hold:
            return
        mx = sum(p[0] for _, p in self._thumb_still) / len(self._thumb_still)
        my = sum(p[1] for _, p in self._thumb_still) / len(self._thumb_still)
        self.corner_values[CORNERS[self.corner_index][0]] = (mx, my)
        self.corner_index += 1
        self.corner_hold = 0.0
        self._thumb_still = []
        self._thumb_armed = False
        self.calib_progress = self.corner_index / len(CORNERS)
        if self.corner_index < len(CORNERS):
            self.calib_state = "move_on"
            return
        quad = [self.corner_values[name] for name, _, _ in CORNERS]
        area = 0.5 * abs(sum(quad[i][0] * quad[(i + 1) % 4][1] - quad[(i + 1) % 4][0] * quad[i][1]
                             for i in range(4)))
        if area < float(self.config.get("thumb_min_area", 0.004)) or not _is_convex(quad) or _homography(
            quad, [(0, 0), (1, 0), (1, 1), (0, 1)]
        ) is None:
            self._restart_corners("narrow_thumb")
            self._thumb_armed = True
            return
        self.config["thumb_corners"] = [[round(x, 4), round(y, 4)] for x, y in quad]
        self.config["movement_mode"] = "thumb"
        self._homography = None
        self._next_calib_phase()

    def dump_debug(self, path: Path) -> Path:
        """Write the recent per-frame pinch data (thumb-finger distances, state) as CSV."""
        rows = list(self.debug_log)
        path.parent.mkdir(parents=True, exist_ok=True)
        keys = list(rows[0].keys()) if rows else ["t"]
        with open(path, "w", encoding="utf-8") as f:
            f.write(",".join(keys) + "\n")
            for row in rows:
                f.write(",".join(str(row.get(k, "")) for k in keys) + "\n")
        return path

    def paper_angle(self) -> float:
        """Paper "up" direction in the image: hand/auto direction plus the user rotation."""
        return self.forward_angle + math.radians(float(self.config.get("paper_rotation_deg", 0.0)))

    def paper_depth_scale(self) -> float:
        """Stretch for forward/back strokes: 1 / cos(tilt) times the extra depth gain."""
        tilt = max(0.0, min(75.0, float(self.config.get("paper_tilt_deg", 45.0))))
        gain = float(self.config.get("paper_depth_gain", 1.0)) or 1.0
        return gain / math.cos(math.radians(tilt))

    def adjust_paper_rotation(self, delta_deg: float) -> float:
        val = max(-90.0, min(90.0, float(self.config.get("paper_rotation_deg", 0.0)) + delta_deg))
        self.config["paper_rotation_deg"] = round(val, 1)
        return self.config["paper_rotation_deg"]

    def adjust_paper_tilt(self, delta_deg: float) -> float:
        val = max(0.0, min(75.0, float(self.config.get("paper_tilt_deg", 45.0)) + delta_deg))
        self.config["paper_tilt_deg"] = round(val, 1)
        return self.config["paper_tilt_deg"]

    def _advance_paper(self, dx: float, dy: float, turn: float = 0.0, curl_step: float = 0.0) -> None:
        """Move the pen on the paper by one frame's step.
        dx, dy: pen movement in the image (image-height units).
        turn: hand rotation since pen down; undoing it turns an elbow arc into a straight line.
        curl_step: change of middle+ring+pinky openness (negative = curling in)."""
        palm = max(0.02, self.palm_size)
        dx /= palm
        dy /= palm
        if turn:
            cos_t, sin_t = math.cos(-turn), math.sin(-turn)
            dx, dy = dx * cos_t - dy * sin_t, dx * sin_t + dy * cos_t

        axis = self.x_axis_angle
        if axis is not None:
            # Calibrated: project onto the measured horizontal line and its perpendicular.
            ca, sa = math.cos(axis), math.sin(axis)
            px = dx * ca + dy * sa
            py_hand = -dx * sa + dy * ca
        else:
            rot = -self.paper_angle()
            cos_r, sin_r = math.cos(rot), math.sin(rot)
            px = dx * cos_r - dy * sin_r
            py_hand = dx * sin_r + dy * cos_r

        if str(self.config.get("vertical_source", "fingers")).lower() == "fingers":
            # Curling the three fingers in (openness drops) moves the cursor down.
            closed, opened = self.curl_range()
            py = -curl_step / (opened - closed) * float(self.config.get("curl_gain", 0.45))
        else:
            py = py_hand * self.paper_depth_scale()
        if bool(self.config.get("paper_invert_x", True)):
            px = -px
        if bool(self.config.get("flip_x", False)):
            px = -px
        self._paper = (self._paper[0] + px, self._paper[1] + py)

    def paper_to_image(self, du: float, dv: float) -> Tuple[float, float]:
        """Convert a paper offset (palm units) to a normalized image offset (for drawing the paper)."""
        dv /= self.paper_depth_scale()
        if bool(self.config.get("paper_invert_x", True)):
            du = -du
        if bool(self.config.get("flip_x", False)):
            du = -du
        axis = self.x_axis_angle
        if axis is not None:
            ca, sa = math.cos(axis), math.sin(axis)
            ix = (du * ca - dv * sa) * self.palm_size
            iy = (du * sa + dv * ca) * self.palm_size
        else:
            rot = self.paper_angle()
            cos_r, sin_r = math.cos(rot), math.sin(rot)
            ix = (du * cos_r - dv * sin_r) * self.palm_size
            iy = (du * sin_r + dv * cos_r) * self.palm_size
        return ix / (self.aspect or 1.0), iy

    # Alias for backward compatibility
    def evaluate(
        self,
        landmarks: Optional[Sequence[Any]],
        timestamp: Optional[float] = None,
        image_size: Optional[Tuple[int, int]] = None,
    ) -> GestureResult:
        return self.process(landmarks, timestamp=timestamp, image_size=image_size)
