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


EDGE = .1      # the box stays this far inside the camera image (palm centre past it: the hand leaves the picture)


def safe_box(box) -> Tuple[float, float, float, float]:
    """The box pulled EDGE inside the camera image. 2026-11-10 '멀리가지도 않았는데 손을 인식을 못함': a box drawn to
    0.98 of the image put the palm centre at the edge to reach the monitor's edge, and half the hand out of the picture.
    Recordings: the hand was lost after 68 of 1000 frames with the palm centre in the outer 10% (top / bottom; 26-46 at
    the sides) against 11 in the middle. ui.bridge keeps the same EDGE for the box it shows and saves."""
    x0, y0, x1, y1 = (min(1 - EDGE, max(EDGE, float(v))) for v in box)
    return x0, y0, x1, y1


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
    """Hand in the box -> 0..1 on the monitor: the box edges ARE the monitor edges (the cursor, i.e. the clicking point,
    reaches every edge). Steadied by a One Euro filter. While `hold` is true the point stays where it aimed: where the
    palm was AIM_BACK s before, if that is within AIM_BACK_MAX (the tilt of closing fingers, not a real move).

    Finding the hand again after a gap eases in over EASE s (it used to land across the screen in one frame, 2.2/min in a
    40 min replay). Releasing a hold does not ease any more (hand-mouse branch behaviour, restored 2026-11-10): the filter
    restarts at the held point. The aim-back went back any distance (8.9/min); now only tilt-sized.
    """

    MIN_CUTOFF, BETA, SPEED_SCALE = .4, .012, 1000.0
    EASE = .2              # s from a held / lost position to the live one
    GAP = .1               # s without a hand after which the next position eases in
    AIM_BACK_MAX = .02     # monitor fractions: a longer way back is a real move, not the pinch tilt

    def __init__(self) -> None:
        self._filter = OneEuro(self.MIN_CUTOFF, self.BETA, speed_scale=self.SPEED_SCALE)
        self.reset()

    def reset(self) -> None:
        self.pos: Optional[Tuple[float, float]] = None
        self._history: deque = deque(maxlen=30)
        self.held = False
        self._filter.reset()
        self._ease_from: Optional[Tuple[float, float]] = None
        self._ease_t = 0.0
        self._last_t: Optional[float] = None

    def _start_ease(self, live: Tuple[float, float], now: float) -> None:
        self._ease_from, self._ease_t = self.pos, now
        self._filter.reset(live)               # the filter restarts at the live hand, the ease covers the distance
        self._filter.t = now

    def target(self, lm: Landmarks, box, hold: bool = False, now: float = 0.0, aim: bool = True) -> Tuple[float, float]:
        x0, y0, x1, y1 = box
        cx, cy = palm_centre(lm)
        nx = min(1.0, max(0.0, (cx - x0) / (x1 - x0)))
        ny = min(1.0, max(0.0, (cy - y0) / (y1 - y0)))
        gap = self._last_t is not None and now - self._last_t > self.GAP
        self._last_t = now
        if hold and self.pos is not None:
            if not self.held:
                self.held = True
                self._ease_from = None
                earlier = [p for t, p in self._history if t <= now - AIM_BACK] if aim else []
                if earlier and math.dist(earlier[-1], self.pos) <= self.AIM_BACK_MAX:
                    self.pos = earlier[-1]
            return self.pos
        if self.pos is not None and gap:
            self._start_ease((nx, ny), now)       # the hand found again after a gap: ease in (no jump across the screen)
        elif self.held:
            # 2026-11-10 restored from the hand-mouse virtual-hand branch: no 0.2 s ease after a click / fist hold (it read
            # as 'stops, then suddenly fast'); the filter restarts at the held point and follows the hand at its own speed
            self._filter.reset(self.pos)
            self._filter.t = now
            self._ease_from = None
        self.held = False
        fx, fy = self._filter((nx, ny), now)
        fx = nx if abs(fx - nx) < 1e-3 else fx       # the filter only nears a clamped edge: the box edge is the monitor edge
        fy = ny if abs(fy - ny) < 1e-3 else fy
        if self._ease_from is not None:
            k = (now - self._ease_t) / self.EASE
            if k >= 1.0:
                self._ease_from = None
            else:
                k = k * k * (3 - 2 * k)               # smoothstep: no kick at either end
                (ax, ay) = self._ease_from
                fx, fy = ax + (fx - ax) * k, ay + (fy - ay) * k
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

    def step(self, lm: Landmarks, width: int, height: int, frames: Optional[int] = None,
             shape_ok: bool = True) -> Optional[str]:
        """`shape_ok`: the whole hand is the person's pinch shape (perception.pinch_shape); False keeps it open."""
        pt = _pixels(lm, width, height)
        if pt is None:
            return None
        size = math.dist(pt[0], pt[9])
        tip, other = TIPS[self.finger], TIPS[self.other]
        self.ratio = math.dist(pt[THUMB_TIP], pt[tip]) / size
        if not self.closed:
            if (shape_ok and self.ratio < self.CLOSE and math.dist(pt[0], pt[tip]) / size > self.FINGER_OUT
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
    """Thumb, index and middle tips together (right click), both fingers out from the wrist, and the ring and little
    fingers out too.

    2026-11-10 (right clicks for no reason): the three tips also meet in a relaxed, curled hand. On the recordings (none
    of them a right click) 250 such closes had the ring / little fingertip at a median 1.10 / 1.01 hand sizes from the
    wrist; the person's pinch-shaped hands 1.58 / 1.47. Requiring RING_OUT (little finger 0.9 of it) kept 28% of them;
    3 frames instead of 2 and no right click around a fist (the feature) remove more."""

    CLOSE, OPEN, FRAMES = .22, .30, 3
    FINGER_OUT = .8
    RING_OUT = 1.2

    def __init__(self) -> None:
        self.closed = False
        self._n = 0

    def reset(self) -> None:
        self.closed, self._n = False, 0

    @classmethod
    def others_out(cls, pt, world: Optional[Landmarks]) -> bool:
        """Ring and little fingertips away from the wrist (hand-size units; 3D world joints when given)."""
        if world is not None and len(world) == 21:
            size3 = math.dist(world[0], world[9])
            if size3 > 1e-6:
                return (math.dist(world[0], world[16]) / size3 >= cls.RING_OUT
                        and math.dist(world[0], world[20]) / size3 >= .9 * cls.RING_OUT)
        size = math.dist(pt[0], pt[9])
        return math.dist(pt[0], pt[16]) / size >= cls.RING_OUT and math.dist(pt[0], pt[20]) / size >= .9 * cls.RING_OUT

    def step(self, lm: Landmarks, width: int, height: int, world: Optional[Landmarks] = None,
             allowed: bool = True) -> Optional[str]:
        pt = _pixels(lm, width, height)
        if pt is None:
            return None
        size = math.dist(pt[0], pt[9])
        far = max(math.dist(pt[THUMB_TIP], pt[8]), math.dist(pt[THUMB_TIP], pt[12])) / size
        if not self.closed:
            out = (allowed and min(math.dist(pt[0], pt[8]), math.dist(pt[0], pt[12])) / size > self.FINGER_OUT
                   and self.others_out(pt, world))
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


FIST_CURL = .9                      # 3D: each fingertip within this share of its middle joint's distance to the wrist


def is_fist(lm: Landmarks, world: Optional[Landmarks] = None) -> bool:
    """All four fingertips nearer the wrist than their knuckles' middle joints (curled). Same idea as the pinch
    feature's fist, kept local so this feature does not import another one (architecture rule).

    2026-11-10 '움직이면 멈췄다가 갑자기 따라온다': judged in the image plane, fingers pointing at the camera look short and
    read as a fist, which holds the cursor (scrolling). With the 3D world joints and tips at most FIST_CURL of the
    middle joint's distance: on 52.8 min of not-gesturing recordings the cursor froze 6.5 times a minute instead of
    19.3 (with Grip's 3-frame start), while the curled fingers of thumbs-up frames still counted (90.5% vs 89.4%)."""
    if len(lm) != 21:
        return False
    if world is not None and len(world) == 21:
        w = world[0]
        return all(math.dist(world[tip], w) < FIST_CURL * math.dist(world[pip], w)
                   for pip, tip in ((6, 8), (10, 12), (14, 16), (18, 20)))
    w = lm[0]
    for pip, tip in ((6, 8), (10, 12), (14, 16), (18, 20)):
        if math.dist(lm[tip][:2], w[:2]) >= math.dist(lm[pip][:2], w[:2]):
            return False
    return True


class Grip:
    """A fist holding the page: on after FRAMES fist frames in a row; once held SETTLED s it is kept through a GRACE s
    loss of the shape (one shaky frame does not let go). A short, maybe false fist ends at once (2026-11-10)."""

    GRACE = .4
    FRAMES = 3
    SETTLED = .3

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.on = False
        self.started = False
        self._lost: Optional[float] = None
        self._n = 0
        self._since = 0.0

    def step(self, fist: bool, now: float) -> bool:
        self.started = False
        if fist:
            self._lost = None
            self._n += 1
            if not self.on and self._n >= self.FRAMES:
                self.on = self.started = True
                self._since = now
        else:
            self._n = 0
            if self.on:
                if self._lost is None:
                    self._lost = now
                grace = self.GRACE if self._lost - self._since >= self.SETTLED else 0.0
                if grace == 0.0 or now - self._lost > grace:
                    self.reset()
        return self.on


# ---------------------------------------------------------------------------- the hand drawn on the screen
SIZE_PX = 110.0          # wrist -> middle-finger knuckle of the drawn hand, logical pixels (the click offset unit)


# Palm segments for the size estimate: their 3D length never changes, their 2D length shrinks when they turn away.
SIZE_SEGMENTS = ((0, 5), (0, 9), (0, 13), (0, 17), (5, 17), (5, 9), (9, 13), (13, 17), (1, 5))


def hand_size_px(lm: Landmarks, width: int, height: int, world: Optional[Landmarks] = None) -> Optional[float]:
    """Wrist -> middle knuckle as it would look facing the camera, in image pixels.

    The plain 2D wrist -> middle knuckle length collapses when the fingers turn toward the camera, which drew a huge
    hand (2026-11-10 report). With the 3D world joints (metres, the same whatever the turn), the palm segment lying
    flattest to the image gives the pixels per metre; times the 3D palm length it is the size. Without world joints:
    the largest of a few 2D palm lengths divided by their usual share of the palm length."""
    pts = _pixels(lm, width, height)
    if pts is None:
        return None
    if world is not None and len(world) == 21:
        ratios = []
        for a, b in SIZE_SEGMENTS:
            metres = math.dist(world[a], world[b])
            if metres > 1e-4:
                ratios.append(math.dist(pts[a], pts[b]) / metres)
        palm_m = math.dist(world[0], world[9])
        if ratios and palm_m > 1e-4:
            return max(ratios) * palm_m
    shares = {(0, 9): 1.0, (0, 5): .95, (0, 17): .85, (5, 17): .75}
    return max(math.dist(pts[a], pts[b]) / share for (a, b), share in shares.items())


class HandDrawer:
    """The drawn hand: the camera picture's shape (as the hand-mouse virtual-hand branch drew it), at a steady size.

    2026-11-10 reports, in order: '손을 아래로 굽히면 비정상적으로 가상손의 크기가 작아진다', then '가상손이 뒤틀려 있다'
    twice. What was tried and measured:
    - picture shape scaled by a 3D-estimated size (pixels per metre from palm segments): 19% of recorded frames under
      0.7x the wanted palm size (short, noisy segments overestimate the size);
    - the hand drawn in its own 3D frame: always palm-on, so a turned hand looked twisted (5% even mirrored);
    - the 3D world joints seen from the camera: matched the recordings, but live, with the hand close to the camera,
      MediaPipe's world joints often put the palm edge-on while the picture shows it face-on (knuckles in one point).
    So the shape is the picture's own (never twisted) and only the scale is chosen: the larger of the picture's palm
    length (wrist -> middle knuckle) and its knuckle row (index -> little knuckle) / ACROSS. Bending the hand down
    shortens the first, turning it edge-on narrows the second; the larger stays. A slow One Euro filter keeps the size
    from twitching.
    """

    ACROSS = .7          # knuckle row / palm length of a hand facing the camera (recordings: 2D median .71, 3D .66)

    def __init__(self) -> None:
        self._size = OneEuro(.3, .002)

    def reset(self) -> None:
        self._size.reset()

    def __call__(self, lm: Landmarks, world: Optional[Landmarks], width: int, height: int,
                 size_px: float = SIZE_PX, now: Optional[float] = None) -> Optional[List[float]]:
        pts = _pixels(lm, width, height)
        if pts is None:
            return None
        palm = max(math.dist(pts[0], pts[9]), math.dist(pts[5], pts[17]) / self.ACROSS)
        palm = self._size((palm,), now)[0]
        return view_points(lm, width, height, size_px=size_px, hand_px=palm)


def view_points(lm: Landmarks, width: int, height: int, size_px: float = SIZE_PX,
                hand_px: Optional[float] = None) -> Optional[List[float]]:
    """The 21 joints relative to the palm centre, scaled so the hand is `size_px` big: [x0, y0, x1, y1, ...] (logical
    px). A far, small hand is drawn as large as a near one. `hand_px` is the hand's size in the image
    (`hand_size_px`, smoothed by the caller); the plain wrist -> middle knuckle length when not given."""
    pts = _pixels(lm, width, height)
    if pts is None:
        return None
    k = size_px / max(1.0, hand_px if hand_px else math.dist(pts[0], pts[9]))
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
