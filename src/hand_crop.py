"""
Hand-area crop: where to look next frame (2026-11-04).

With the whole frame shrunk to 640 px wide, a hand far from the webcam (or blurred in a
dim room) covers few model pixels and tracking drops while moving. Looking at a square
around the last known hand, at the camera's full resolution, gives the model a much
bigger hand. The crop stays put until the hand nears its edge (MediaPipe's video tracking
likes a stable image) and is not used when the hand is already big in the frame.
"""
from __future__ import annotations

from typing import Optional, Sequence, Tuple

Roi = Tuple[int, int, int, int]  # x0, y0, x1, y1 in frame pixels


class HandCrop:
    def __init__(self, scale: float = 2.4, min_px: int = 192, recenter: float = .18,
                 resize: float = .3, max_hand_frac: float = .35, hold_seconds: float = 0.8) -> None:
        self.scale = scale              # crop side = scale x hand size
        self.min_px = min_px            # never smaller than this (pixels)
        self.recenter = recenter        # move when the hand centre is this far from the crop centre (x side)
        self.resize = resize            # resize when the wanted side differs this much (fraction)
        self.max_hand_frac = max_hand_frac  # hand bigger than this x frame height: no crop needed
        self.hold_seconds = hold_seconds    # after a miss, keep trying the last crop this long (far hands flicker)
        self.last_seen: Optional[float] = None
        self.roi: Optional[Roi] = None
        self.moves = 0

    def reset(self) -> None:
        self.roi = None
        self.last_seen = None

    def miss(self, now: float) -> None:
        """No hand this frame: keep the last crop for `hold_seconds` so the next frames look there first."""
        if self.roi is not None and self.last_seen is not None and now - self.last_seen <= self.hold_seconds:
            return
        self.reset()

    def follow(self, box: Tuple[int, int, int, int], width: int, height: int, now: float) -> Optional[Roi]:
        """The detector lost the hand but a video tracker still sees it at `box` (x, y, w, h in pixels): put the crop there."""
        x, y, w, h = box
        size = max(w, h)
        if size <= 0:
            return None
        limit = min(width, height)
        want = int(round(min(limit, max(self.min_px, self.scale * size))))
        cx, cy = x + w / 2, y + h / 2
        half = want / 2
        x0 = int(round(min(max(cx - half, 0), width - want)))
        y0 = int(round(min(max(cy - half, 0), height - want)))
        self.roi = (x0, y0, x0 + want, y0 + want)
        self.last_seen = now          # the crop is alive as long as the tracker keeps following
        self.moves += 1
        return self.roi

    def update(self, landmarks: Sequence, width: int, height: int, now: Optional[float] = None) -> Optional[Roi]:
        """Feed the tracked hand's landmarks (normalized); returns the crop for the next frame."""
        if now is not None:
            self.last_seen = now
        xs = [p.x * width for p in landmarks]
        ys = [p.y * height for p in landmarks]
        if not xs:
            self.roi = None
            return None
        bw, bh = max(xs) - min(xs), max(ys) - min(ys)
        size = max(bw, bh)
        limit = min(width, height)
        if size >= self.max_hand_frac * height or size <= 0:
            self.roi = None  # big (close) hand: the whole frame already works
            return None
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        want = int(round(min(limit, max(self.min_px, self.scale * size))))
        if self.roi is not None:
            x0, y0, x1, y1 = self.roi
            side = x1 - x0
            ox, oy = (x0 + x1) / 2, (y0 + y1) / 2
            centred = abs(cx - ox) <= self.recenter * side and abs(cy - oy) <= self.recenter * side
            same_size = abs(want - side) <= self.resize * side
            if centred and same_size:
                return self.roi
        half = want / 2
        x0 = int(round(min(max(cx - half, 0), width - want)))
        y0 = int(round(min(max(cy - half, 0), height - want)))
        self.roi = (x0, y0, x0 + want, y0 + want)
        self.moves += 1
        return self.roi
