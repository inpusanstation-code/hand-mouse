"""Frame -> HandObservation for the control hand (the tracking part of hand-mouse qt_runtime._step).

Per frame: detect (inside the hand crop when enabled; a crop miss resets the crop and retries on
the whole frame), keep every hand for the capture screen, pick the control hand by physical side,
update the crop from it, and return it as a contract `HandObservation` (or None).

With a `BodyGuide` attached (`tracking.body_assist`, on by default): a frame that lost the control hand runs
Pose and searches once more in the square at the skeleton's wrist (`path` gets ">body"). Otherwise unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

from manux.core.contracts import FrameInfo, HandObservation
from manux.tracking.crop import HandCrop
from manux.tracking.landmarker import Landmarker, RawHand
from manux.tracking.selection import MIN_SCORE, HandFollower, physical_side


@dataclass(frozen=True)
class TrackResult:
    hand: Optional[HandObservation]                 # the control hand, or None
    hands: Tuple[RawHand, ...] = ()                 # every hand found (capture screen, diagnostics)
    path: str = "full"                              # "full" | "crop" | "crop_miss>full" | "skipped", + ">body"
    detect_ms: float = 0.0
    followed: bool = False                          # the hand was kept by HandFollower (label flipped or unsure)


def to_observation(raw: RawHand, frame: FrameInfo, side: str) -> HandObservation:
    return HandObservation(frame=frame, landmarks=raw.landmarks, handedness=side,  # type: ignore[arg-type]
                           score=raw.score, world=raw.world, from_crop=raw.from_crop)


class HandTracker:
    def __init__(self, landmarker: Landmarker, *, use_crop: bool = False, min_score: float = MIN_SCORE,
                 follow: bool = True) -> None:
        self.landmarker = landmarker
        self.use_crop = use_crop
        self.min_score = min_score
        self.crop = HandCrop()
        self.follower: Optional[HandFollower] = HandFollower() if follow else None
        self.body = None                            # optional tracking.body.BodyGuide
        self._last: Optional[Tuple[float, float, float, float]] = None   # cx, cy, size px, t of the last hand

    def reset(self) -> None:
        self.crop.reset()
        if self.follower is not None:
            self.follower.reset()
        self._last = None

    def step(self, frame: FrameInfo, image: Any, control_hand: str, detect: bool = True) -> TrackResult:
        if not detect:
            return TrackResult(None, (), "skipped")
        roi = self.crop.roi if self.use_crop else None
        hands: List[RawHand] = self.landmarker.detect(image, roi=roi)
        path = "crop" if roi is not None else "full"
        if roi is not None and not hands:
            self.crop.reset()
            hands = self.landmarker.detect(image, roi=None)
            path = "crop_miss>full"
        hand, followed = self._choose(hands, frame, control_hand)
        if self.body is not None:
            points = self.body.step(image, frame.t, need=hand is None)
            if hand is None and points:
                roi = self._body_roi(points, frame, control_hand)
                if roi is not None:
                    self.body.roi, self.body.roi_t = roi, frame.t
                    extra = self.landmarker.detect(image, roi=roi)
                    if extra:
                        found, kept = self._choose(extra, frame, control_hand)
                        if found is not None:
                            hands, hand, followed, path = extra, found, kept, path + ">body"
                            self.body.used += 1
        if hand is not None:
            xs = [p[0] * frame.width for p in hand.landmarks]
            ys = [p[1] * frame.height for p in hand.landmarks]
            self._last = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2,
                          max(max(xs) - min(xs), max(ys) - min(ys)), frame.t)
        if self.use_crop and hand is not None:
            self.crop.update(hand.landmarks, frame.width, frame.height)
        else:
            self.crop.reset()
        return TrackResult(hand, tuple(hands), path, float(getattr(self.landmarker, "last_detect_ms", 0.0)),
                           followed=followed and hand is not None)

    def _choose(self, hands, frame: FrameInfo, control_hand: str):
        if self.follower is not None:
            chosen = self.follower.select(hands, control_hand, frame.mirrored, frame.t, self.min_score)
            followed = self.follower.followed
        else:
            from manux.tracking.selection import select
            chosen, followed = select(hands, control_hand, frame.mirrored, self.min_score), False
        if chosen is None:
            return None, False
        try:
            return to_observation(chosen, frame, physical_side(chosen, frame.mirrored, self.min_score)), followed
        except ValueError:
            return None, False   # malformed landmarks: treat as no hand (contracts section 3)

    def _body_roi(self, points, frame: FrameInfo, control_hand: str):
        from manux.tracking.body import guide_roi
        last = self._last[:3] if self._last is not None and frame.t - self._last[3] <= 5.0 else None
        return guide_roi(points, control_hand, frame.mirrored, frame.width, frame.height, last=last,
                         scale=self.crop.scale, min_px=self.crop.min_px, max_hand_frac=self.crop.max_hand_frac)
