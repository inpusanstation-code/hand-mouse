"""Hand-shape judges and the box mapping of the virtual hand (ported from virtual-hand-20261110 `src/virtual_hand.py`).

Pure geometry on 21 whole-frame landmarks `(x, y, z)` in 0..1, with the frame size to measure in pixels. Nothing here
knows about the rule engine, the OS or Qt. The numbers are the source's, measured there on one person's recordings
(see docs/virtual-hand.md in that folder): thumb + index closes on 93% of the repetitions, about 6 false closes a
minute while resting.
"""
from __future__ import annotations

import math
from collections import deque
from typing import List, Optional, Sequence, Tuple

Landmarks = Sequence[Tuple[float, float, float]]

THUMB_TIP = 4
PALM = (0, 5, 9, 13, 17)            # wrist and the four knuckles: their mean is the palm centre
TIPS = {"index": 8, "middle": 12, "ring": 16, "pinky": 20}
MIN_BOX = .1
AIM_BACK = .15                      # s: a click lands where the palm was this long before the fingers touched


def palm_centre(lm: Landmarks) -> Tuple[float, float]:
    return (sum(lm[i][0] for i in PALM) / len(PALM), sum(lm[i][1] for i in PALM) / len(PALM))


def _pixels(lm: Landmarks, width: int, height: int) -> Optional[List[Tuple[float, float]]]:
    if len(lm) != 21:
        return None
    pts = [(p[0] * width, p[1] * height) for p in lm]
    return pts if math.dist(pts[0], pts[9]) >= 1.0 else None


def valid_box(box) -> bool:
    try:
        x0, y0, x1, y1 = (float(v) for v in box)
    except (TypeError, ValueError):
        return False
    return 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1 and x1 - x0 >= MIN_BOX and y1 - y0 >= MIN_BOX


class OneEuro:
    """One Euro filter (Casiez et al. 2012) over a point of any dimension: the cutoff rises with the speed."""

    def __init__(self, min_cutoff: float, beta: float, d_cutoff: float = 1.0, speed_scale: float = 1.0) -> None:
        self.min_cutoff, self.beta, self.d_cutoff, self.speed_scale = min_cutoff, beta, d_cutoff, speed_scale
        self.reset()

    def reset(self, x: Optional[Sequence[float]] = None) -> None:
        self.x = None if x is None else list(x)
        self.dx = None if x is None else [0.0] * len(x)
        self.t: Optional[float] = None

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        return 1.0 / (1.0 + 1.0 / (2 * math.pi * cutoff * dt))

    def __call__(self, x: Sequence[float], t: Optional[float] = None) -> List[float]:
        x = list(x)
        if self.x is None or len(self.x) != len(x):
            self.reset(x)
            self.t = t
            return list(x)
        dt = (t - self.t) if (t is not None and self.t is not None and t > self.t) else 1 / 30
        self.t = t
        ad = self._alpha(self.d_cutoff, dt)
        self.dx = [ad * (a - b) / dt + (1 - ad) * d for a, b, d in zip(x, self.x, self.dx)]
        speed = math.sqrt(sum(d * d for d in self.dx)) * self.speed_scale
        a = self._alpha(self.min_cutoff + self.beta * speed, dt)
        self.x = [a * n + (1 - a) * o for n, o in zip(x, self.x)]
        return list(self.x)


class BoxMapper:
    """Palm centre in the box -> 0..1 on the monitor; the box edges are the monitor edges, steadied by a One Euro filter.
    While `hold` is true the point stays where the palm was AIM_BACK s before (the aim, not the pinch tilt)."""

    MIN_CUTOFF, BETA, SPEED_SCALE = .4, .012, 1000.0

    def __init__(self) -> None:
        self.pos: Optional[Tuple[float, float]] = None
        self._history: deque = deque(maxlen=30)
        self.held = False
        self._filter = OneEuro(self.MIN_CUTOFF, self.BETA, speed_scale=self.SPEED_SCALE)

    def reset(self) -> None:
        self.pos = None
        self._history.clear()
        self.held = False
        self._filter.reset()

    def target(self, lm: Landmarks, box, hold: bool = False, now: float = 0.0, aim: bool = True) -> Tuple[float, float]:
        x0, y0, x1, y1 = box
        cx, cy = palm_centre(lm)
        nx = min(1.0, max(0.0, (cx - x0) / (x1 - x0)))
        ny = min(1.0, max(0.0, (cy - y0) / (y1 - y0)))
        if hold and self.pos is not None:
            if not self.held:
                self.held = True
                earlier = [p for t, p in self._history if t <= now - AIM_BACK] if aim else []
                if earlier:
                    self.pos = earlier[-1]
                self._filter.reset(self.pos)
                self._filter.t = now
            return self.pos
        self.held = False
        fx, fy = self._filter((nx, ny), now)
        fx = nx if abs(fx - nx) < 1e-3 else fx       # the filter only nears a clamped edge: the box edge is the monitor edge
        fy = ny if abs(fy - ny) < 1e-3 else fy
        self.pos = (fx, fy)
        self._history.append((now, self.pos))
        return self.pos


class ShapePinch:
    """Thumb + finger closed, from the shape alone: tip distance over hand size (wrist -> middle knuckle), the finger out
    from the wrist (a fist also brings the thumb onto the fingers), and nearer the thumb than the other of index / middle.
    step() -> "down" when the fingers close, "up" when they open, else None."""

    CLOSE, OPEN, FRAMES = .18, .24, 2
    FINGER_OUT = .8

    def __init__(self, finger: str = "index") -> None:
        self.finger = finger
        self.other = "middle" if finger == "index" else "index"
        self.closed = False
        self._n = 0
        self.ratio = 1.0

    def reset(self) -> None:
        self.closed, self._n = False, 0

    def step(self, lm: Landmarks, width: int, height: int, frames: Optional[int] = None) -> Optional[str]:
        pt = _pixels(lm, width, height)
        if pt is None:
            return None
        size = math.dist(pt[0], pt[9])
        tip, other = TIPS[self.finger], TIPS[self.other]
        self.ratio = math.dist(pt[THUMB_TIP], pt[tip]) / size
        if not self.closed:
            if (self.ratio < self.CLOSE and math.dist(pt[0], pt[tip]) / size > self.FINGER_OUT
                    and self.ratio < math.dist(pt[THUMB_TIP], pt[other]) / size):
                self._n += 1
                if self._n >= (frames or self.FRAMES):
                    self.closed, self._n = True, 0
                    return "down"
            else:
                self._n = 0
            return None
        if self.ratio > self.OPEN:
            self.closed = False
            return "up"
        return None


class ShapeTriple:
    """Thumb, index and middle tips together (right click), both fingers out from the wrist."""

    CLOSE, OPEN, FRAMES = .22, .30, 2
    FINGER_OUT = .8

    def __init__(self) -> None:
        self.closed = False
        self._n = 0

    def reset(self) -> None:
        self.closed, self._n = False, 0

    def step(self, lm: Landmarks, width: int, height: int) -> Optional[str]:
        pt = _pixels(lm, width, height)
        if pt is None:
            return None
        size = math.dist(pt[0], pt[9])
        far = max(math.dist(pt[THUMB_TIP], pt[8]), math.dist(pt[THUMB_TIP], pt[12])) / size
        if not self.closed:
            out = min(math.dist(pt[0], pt[8]), math.dist(pt[0], pt[12])) / size > self.FINGER_OUT
            if far < self.CLOSE and out:
                self._n += 1
                if self._n >= self.FRAMES:
                    self.closed, self._n = True, 0
                    return "down"
            else:
                self._n = 0
            return None
        if far > self.OPEN:
            self.closed = False
            return "up"
        return None


class ShapeSwitch:
    """Task switcher: thumb folded onto the palm, the four fingers straight and pointing up, held still HOLD s. Fires once,
    then waits for the shape to go away."""

    EXTENDED, TUCK, UP = 1.5, .5, .94
    HOLD, STILL = .5, .03

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._since: Optional[float] = None
        self._anchor: Optional[Tuple[float, float]] = None
        self._armed = True

    def shape(self, lm: Landmarks, width: int, height: int) -> bool:
        pt = _pixels(lm, width, height)
        if pt is None:
            return False
        w = pt[0]
        palm = math.dist(w, pt[9])
        for mcp, tip in ((5, 8), (9, 12), (13, 16), (17, 20)):
            if math.dist(pt[tip], w) / max(1e-6, math.dist(pt[mcp], w)) <= self.EXTENDED:
                return False
        if min(math.dist(pt[THUMB_TIP], pt[j]) for j in (5, 6, 9, 10, 13, 17)) / palm > self.TUCK:
            return False
        vx, vy = pt[12][0] - w[0], pt[12][1] - w[1]
        return -vy / max(1e-6, math.hypot(vx, vy)) >= self.UP

    def step(self, lm: Landmarks, width: int, height: int, now: float) -> bool:
        if not self.shape(lm, width, height):
            self._since, self._anchor, self._armed = None, None, True
            return False
        here = palm_centre(lm)
        if self._since is None or math.dist(here, self._anchor) > self.STILL:
            self._since, self._anchor = now, here
            return False
        if self._armed and now - self._since >= self.HOLD:
            self._armed = False
            return True
        return False


def is_fist(lm: Landmarks) -> bool:
    """All four fingertips nearer the wrist than their knuckles' middle joints (curled). Same idea as the pinch
    feature's fist, kept local so this feature does not import another one (architecture rule)."""
    if len(lm) != 21:
        return False
    w = lm[0]
    for pip, tip in ((6, 8), (10, 12), (14, 16), (18, 20)):
        if math.dist(lm[tip][:2], w[:2]) >= math.dist(lm[pip][:2], w[:2]):
            return False
    return True


class Grip:
    """A fist holding the page, kept through a GRACE s loss of the shape (one shaky frame does not let go)."""

    GRACE = .4

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.on = False
        self.started = False
        self._lost: Optional[float] = None

    def step(self, fist: bool, now: float) -> bool:
        self.started = False
        if fist:
            self._lost = None
            if not self.on:
                self.on = self.started = True
        elif self.on:
            if self._lost is None:
                self._lost = now
            if now - self._lost > self.GRACE:
                self.reset()
        return self.on


# ---------------------------------------------------------------------------- the hand drawn on the screen
SIZE_PX = 110.0          # wrist -> middle-finger knuckle of the drawn hand, logical pixels (the click offset unit)


def view_points(lm: Landmarks, width: int, height: int, size_px: float = SIZE_PX) -> Optional[List[float]]:
    """The 21 joints relative to the palm centre, scaled so the hand is `size_px` big: [x0, y0, x1, y1, ...] (logical
    px). A far, small hand is drawn as large as a near one. None for a degenerate hand."""
    pts = _pixels(lm, width, height)
    if pts is None:
        return None
    k = size_px / math.dist(pts[0], pts[9])
    cx, cy = palm_centre(lm)
    ox, oy = cx * width, cy * height
    flat: List[float] = []
    for x, y in pts:
        flat += [round((x - ox) * k, 1), round((y - oy) * k, 1)]
    return flat


def pinch_point(pts: Sequence[float], finger: str = "index") -> List[float]:
    """Where the thumb and `finger` meet on the drawn hand (logical px from the palm centre)."""
    t, f = THUMB_TIP, TIPS[finger]
    return [round((pts[2 * t] + pts[2 * f]) / 2, 1), round((pts[2 * t + 1] + pts[2 * f + 1]) / 2, 1)]


def triple_point(pts: Sequence[float]) -> List[float]:
    """Centre of the thumb, index and middle tips on the drawn hand."""
    ids = (THUMB_TIP, TIPS["index"], TIPS["middle"])
    return [round(sum(pts[2 * i] for i in ids) / 3, 1), round(sum(pts[2 * i + 1] for i in ids) / 3, 1)]


class ViewSmoother:
    """Steadies the drawn joints, each with its own speed (a still palm stays still while a finger closes).
    Source measurement: fingertip jitter (frame-to-frame second difference, median) 6.8 px -> 2.2 px."""

    MIN_CUTOFF, BETA = .5, .03

    def __init__(self) -> None:
        self._filters = [OneEuro(self.MIN_CUTOFF, self.BETA) for _ in range(21)]

    def reset(self) -> None:
        for f in self._filters:
            f.reset()

    def __call__(self, pts: Sequence[float], now: Optional[float] = None) -> List[float]:
        out: List[float] = []
        for i, f in enumerate(self._filters):
            out += [round(v, 1) for v in f(pts[2 * i:2 * i + 2], now)]
        return out
