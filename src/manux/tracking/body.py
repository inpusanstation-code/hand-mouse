"""Body/head skeleton that points the hand search at the arm when the hand is lost (`tracking.body_assist`, on by default since 2026-11-10).

A far hand is small and the hand detector loses it, but the body is big and MediaPipe Pose keeps it. Pose's wrist
then says where to look: a full-resolution square at the wrist, pushed a little along the forearm, is searched
again with the hand model. Measured on the 1-3 m distance course (2026-11-10, recordings only, not live): pose wrist
error ~0.2x the hand box; after a simulated 3 s loss a 192 px square at the pose wrist covered the hand on 96-100%
of frames against 48-92% for the last seen position. Not yet measured: whether Pose fails at the same moments.

Labels: Pose's left/right follow the same convention as the hand model's label (95% of 200k recorded frames on
a mirrored camera matched pose index 15 to hand label "Left"), so the physical side flips the same way
(`selection.physical_side`). The skeleton never decides a gesture; it only proposes one extra crop.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, Optional, Sequence, Tuple

from manux.tracking.landmarker import Roi

Point = Tuple[float, float, float]          # x, y (0..1 of the frame), visibility
WRIST = {"Left": 15, "Right": 16}           # by Pose label (same convention as the hand model's label)
ELBOW = {"Left": 13, "Right": 14}
SHOULDERS = (11, 12)
MIN_VISIBILITY = .5


def pose_label(side: str, mirrored: bool) -> str:
    """The Pose label of the user's physical `side` hand (inverse of `selection.physical_side`)."""
    return {"Left": "Right", "Right": "Left"}.get(side, "") if mirrored else side


def _px(p: Point, width: int, height: int) -> Tuple[float, float]:
    return p[0] * width, p[1] * height


def guide_roi(points: Sequence[Point], side: str, mirrored: bool, width: int, height: int, *,
              last: Optional[Tuple[float, float, float]] = None, scale: float = 2.4, min_px: int = 192,
              max_hand_frac: float = .35) -> Optional[Roi]:
    """Square to search for the hand, from a 33-point Pose. `last` = (cx, cy, size) of the last hand in px.

    With a recent hand the wrist nearest to it is used (no left/right guess); otherwise the `side` wrist.
    None when no usable wrist is visible or the hand would be big (the whole frame already finds those).
    """
    if len(points) < 17 or width <= 0 or height <= 0:
        return None
    labels = [l for l in ("Left", "Right") if points[WRIST[l]][2] >= MIN_VISIBILITY]
    if last is not None and labels:
        label = min(labels, key=lambda l: math.dist(_px(points[WRIST[l]], width, height), last[:2]))
    else:
        label = pose_label(side, mirrored)
        if label not in labels:
            return None
    wx, wy = _px(points[WRIST[label]], width, height)
    ex, ey = _px(points[ELBOW[label]], width, height)
    forearm = math.hypot(wx - ex, wy - ey)
    if last is not None:
        size = last[2]
    else:                                   # no hand yet: a hand is about half the shoulder width
        a, b = (points[i] for i in SHOULDERS)
        shoulders = math.dist(_px(a, width, height), _px(b, width, height)) if min(a[2], b[2]) >= MIN_VISIBILITY else 0
        size = max(.5 * shoulders, .7 * forearm)
    if size <= 0 or size >= max_hand_frac * height:
        return None
    if forearm > 1 and points[ELBOW[label]][2] >= MIN_VISIBILITY:      # the hand sits past the wrist
        wx, wy = wx + (wx - ex) / forearm * .5 * size, wy + (wy - ey) / forearm * .5 * size
    want = int(round(min(min(width, height), max(min_px, scale * size))))
    x0 = int(round(min(max(wx - want / 2, 0), width - want)))
    y0 = int(round(min(max(wy - want / 2, 0), height - want)))
    return x0, y0, x0 + want, y0 + want


class _Euro:
    """One Euro filter over (x, y) in frame units: still joints stay still, moving joints follow with little lag."""

    def __init__(self, min_cutoff: float, beta: float, d_cutoff: float = 1.0) -> None:
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.x: Optional[Tuple[float, float]] = None
        self.dx = (0.0, 0.0)
        self.t = 0.0

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        return 1.0 / (1.0 + 1.0 / (2 * math.pi * cutoff * dt))

    def __call__(self, x: float, y: float, t: float) -> Tuple[float, float]:
        dt = t - self.t
        if self.x is None or not 0 < dt <= .5:
            self.x, self.dx, self.t = (x, y), (0.0, 0.0), t
            return x, y
        self.t = t
        ad = self._alpha(self.d_cutoff, dt)
        self.dx = (ad * (x - self.x[0]) / dt + (1 - ad) * self.dx[0], ad * (y - self.x[1]) / dt + (1 - ad) * self.dx[1])
        a = self._alpha(self.min_cutoff + self.beta * math.hypot(*self.dx), dt)
        self.x = (a * x + (1 - a) * self.x[0], a * y + (1 - a) * self.x[1])
        return self.x


class SkeletonSmoother:
    """Steadies the DRAWN skeleton only (the search square and recordings use the raw points).

    Each joint has its own filter; visibility is eased and shown with hysteresis (on at .5, off below .35) so a
    joint near the threshold does not blink."""

    MIN_CUTOFF, BETA, VIS_ALPHA, SHOW, HIDE = 1.0, 4.0, .35, .5, .35

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._xy = [_Euro(self.MIN_CUTOFF, self.BETA) for _ in range(33)]
        self._vis = [0.0] * 33
        self._shown = [False] * 33

    def __call__(self, points: Sequence[Point], t: float) -> Tuple[Point, ...]:
        out = []
        for i, (x, y, v) in enumerate(points[:33]):
            self._vis[i] += self.VIS_ALPHA * (v - self._vis[i])
            self._shown[i] = self._vis[i] >= (self.HIDE if self._shown[i] else self.SHOW)
            fx, fy = self._xy[i](x, y, t)
            out.append((fx, fy, 1.0 if self._shown[i] else 0.0))
        return tuple(out)


class BodyGuide:
    """Runs Pose on the frames that need it and keeps the latest skeleton for the preview and recording.

    `detect(image, t)` returns 33 points or None. `tracker` is created lazily; a failure turns the guide off
    for this session and leaves hand tracking exactly as it was.
    """

    def __init__(self, model: Path, every_n: int = 3, factory: Optional[Callable[[Path], object]] = None) -> None:
        self.model, self.every_n = Path(model), max(1, int(every_n))
        self._factory = factory
        self._tracker = None
        self.failed = ""
        self.points: Optional[Tuple[Point, ...]] = None
        self.points_t = -1e9                 # frame time of `points`
        self.roi: Optional[Roi] = None       # the last crop the skeleton proposed (preview)
        self.roi_t = -1e9
        self.used = 0                        # proposed crops that found the control hand
        self._n = 0
        self._smooth = SkeletonSmoother()
        self.view: Optional[Tuple[Point, ...]] = None   # smoothed `points` for drawing

    def _ensure(self):
        if self._tracker is None:
            if self._factory is not None:
                self._tracker = self._factory(self.model)
            else:
                from manux.tracking.pose import PoseTracker
                self._tracker = PoseTracker(self.model)
        return self._tracker

    def step(self, image, t: float, need: bool) -> Optional[Tuple[Point, ...]]:
        """Pose on this frame when `need` (hand lost) or every `every_n` frames (preview, recording)."""
        self._n += 1
        if self.failed or image is None or not (need or self._n % self.every_n == 0):
            return self.points if t - self.points_t <= .3 else None
        try:
            self.points = self._ensure().detect_all(image, t)
        except Exception as exc:              # missing model / mediapipe: hand tracking goes on unchanged
            self.failed, self.points = f"{type(exc).__name__}: {exc}", None
            self.close()
            return None
        if self.points is None:
            if t - self.points_t > .3:
                self._smooth.reset()
                self.view = None
        else:
            self.view = self._smooth(self.points, t)
            self.points_t = t
        return self.points

    def fresh(self, t: float, within: float = .3) -> Optional[Tuple[Point, ...]]:
        return self.points if self.points is not None and t - self.points_t <= within else None

    def fresh_view(self, t: float, within: float = .3) -> Optional[Tuple[Point, ...]]:
        """The smoothed skeleton for the preview (never for decisions or recordings)."""
        return self.view if self.view is not None and t - self.points_t <= within else None

    def close(self) -> None:
        if self._tracker is not None:
            try:
                self._tracker.close()
            finally:
                self._tracker = None
