"""Which way the hand points on the screen, in 8 directions (2026-11-11, user: "the open-hand uses were collected whatever way
the hand pointed; learned together they will misfire - the direction also gets its own command, so collect and learn each
direction (diagonals too) apart").

The direction is the wrist -> middle-finger knuckle line as the (mirrored) preview shows it: "up" is a hand held upright,
"left" one pointing left on the screen. A taught gesture's uses are then kept per direction under "<key>@<direction>"
(e.g. "comp_open_hand_hold@up"): counted, learned (src/online/verifier.py) and checked apart."""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, Optional, Sequence

DIRS = ("up", "up_right", "right", "down_right", "down", "down_left", "left", "up_left")
NAMES = {"up": "위쪽", "up_right": "오른쪽 위", "right": "오른쪽", "down_right": "오른쪽 아래", "down": "아래쪽",
         "down_left": "왼쪽 아래", "left": "왼쪽", "up_left": "왼쪽 위"}
ARROWS = {"up": "↑", "up_right": "↗", "right": "→", "down_right": "↘", "down": "↓", "down_left": "↙", "left": "←", "up_left": "↖"}
SEP = "@"
ASPECT = 720 / 1280
WINDOW = .5            # seconds before the command whose hand gives the direction (the shape was being held then)
MIN_LEN = 1e-4


def _xy(p: Any) -> Optional[tuple]:
    if p is None:
        return None
    if isinstance(p, (list, tuple)):
        return (float(p[0]), float(p[1])) if len(p) >= 2 else None
    return (float(p.x), float(p.y))


def vector(landmarks: Sequence[Any], aspect: float = ASPECT) -> Optional[tuple]:
    """Wrist -> middle knuckle on the screen (y down), or None."""
    if landmarks is None or len(landmarks) != 21:
        return None
    a, b = _xy(landmarks[0]), _xy(landmarks[9])
    if a is None or b is None:
        return None
    v = (b[0] - a[0], (b[1] - a[1]) * aspect)
    return v if math.hypot(*v) > MIN_LEN else None


def of_vector(v: Optional[tuple]) -> str:
    if v is None:
        return ""
    angle = math.degrees(math.atan2(v[0], -v[1])) % 360          # 0 = up, 90 = right (clockwise on the screen)
    return DIRS[int((angle + 22.5) // 45) % 8]


def direction(landmarks: Sequence[Any], aspect: float = ASPECT) -> str:
    return of_vector(vector(landmarks, aspect))


def of_frames(frames: Iterable[Dict[str, Any]], t: Optional[float] = None, window: float = WINDOW,
              aspect: float = ASPECT) -> str:
    """The direction of the hand over the `window` seconds up to `t` (all frames when t is None): the mean of the unit
    vectors, so a wobble or a lost frame does not flip it."""
    sx = sy = 0.0
    n = 0
    for f in frames:
        ft = f.get("t")
        if t is not None and ft is not None and not (t - window <= float(ft) <= t + 1e-6):
            continue
        v = vector(f.get("lm"), aspect)
        if v is None:
            continue
        length = math.hypot(*v)
        sx, sy, n = sx + v[0] / length, sy + v[1] / length, n + 1
    return of_vector((sx, sy)) if n else ""


def split(key: str, d: str) -> str:
    return f"{key}{SEP}{d}" if d and SEP not in key else key


def base(key: str) -> str:
    return str(key).split(SEP, 1)[0]


def of_key(key: str) -> str:
    parts = str(key).split(SEP, 1)
    return parts[1] if len(parts) == 2 and parts[1] in NAMES else ""


def name(d: str) -> str:
    return f"{ARROWS[d]} {NAMES[d]}" if d in NAMES else ""
