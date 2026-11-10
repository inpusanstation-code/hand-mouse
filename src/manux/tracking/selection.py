"""Choosing the control hand (port of hand-mouse/src/hand_selection.py, same behaviour).

The physical hand is MediaPipe's handedness label, swapped when the camera image is mirrored
(v0.3 `physical_side`, kept as-is). This rule lives only here: everything after tracking sees
physical hands. A label with a score below `min_score` counts as unsure.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Optional, Sequence, Tuple

from manux.tracking.landmarker import RawHand

MIN_SCORE = .75


def physical_side(hand: RawHand, mirrored: bool, min_score: float = MIN_SCORE) -> str:
    """'Left' / 'Right' (the user's real hand), or '' when the label is unsure."""
    if hand.label not in ("Left", "Right") or not hand.score >= min_score:
        return ""
    return {"Left": "Right", "Right": "Left"}[hand.label] if mirrored else hand.label


def select(hands: Sequence[RawHand], side: str, mirrored: bool, min_score: float = MIN_SCORE) -> Optional[RawHand]:
    """The one hand on `side`. None when there is no such hand or more than one (ambiguous)."""
    matches = [h for h in hands if side and physical_side(h, mirrored, min_score) == side]
    return matches[0] if len(matches) == 1 else None


def _center_and_size(hand: RawHand) -> Tuple[Tuple[float, float], float]:
    """Centre of the landmark box and its longer side, in frame units."""
    xs = [p[0] for p in hand.landmarks]
    ys = [p[1] for p in hand.landmarks]
    return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2), max(max(xs) - min(xs), max(ys) - min(ys))


class HandFollower:
    """Keeps the control hand when a small (far) hand's left/right reading flips or its score drops.

    From virtual-hand-20261110 (`src/hand_selection.py`, far-hand-loss.md section 22): on a 2-3 m distance course about
    38% of the lost frames were hands MediaPipe found but `select` dropped (29% read as the other hand, 9% score
    under 0.75). The strict `select` always comes first and is the only way to start following. Afterwards ONE
    detection in about the same place and of about the same size is the same hand, whatever its label says. Limits
    keep the other hand out: at most `max_gap` s since the last accepted frame and `max_unconfirmed` s since a strict
    reading. Risk: another hand at the same spot can be taken for up to `max_unconfirmed` s.
    """

    def __init__(self, max_gap: float = .5, max_unconfirmed: float = 3.0, reach: float = 1.5,
                 min_reach: float = .05, max_size_change: float = 2.0) -> None:
        self.max_gap, self.max_unconfirmed = max_gap, max_unconfirmed
        self.reach, self.min_reach, self.max_size_change = reach, min_reach, max_size_change
        self.reset()

    def reset(self) -> None:
        self.followed = False          # the last select() accepted a hand only through this class
        self._side = ""
        self._center: Optional[Tuple[float, float]] = None
        self._size = 0.0
        self._seen_at = 0.0
        self._confirmed_at = 0.0

    def select(self, hands: Sequence[RawHand], side: str, mirrored: bool, now: float,
               min_score: float = MIN_SCORE) -> Optional[RawHand]:
        """Like `select`, plus following. A followed hand comes back with its label set to `side`."""
        if side != self._side:
            self.reset()
            self._side = side
        self.followed = False
        chosen = select(hands, side, mirrored, min_score)
        if chosen is not None:
            self._center, self._size = _center_and_size(chosen)
            self._seen_at = self._confirmed_at = now
            return chosen
        if not side or len(hands) != 1 or self._center is None:
            return None
        if now - self._seen_at > self.max_gap or now - self._confirmed_at > self.max_unconfirmed:
            return None
        center, size = _center_and_size(hands[0])
        if size <= 0 or not 1 / self.max_size_change <= size / self._size <= self.max_size_change:
            return None
        limit = max(self.reach * self._size, self.min_reach)
        if abs(center[0] - self._center[0]) > limit or abs(center[1] - self._center[1]) > limit:
            return None
        self._center, self._size, self._seen_at = center, size, now
        self.followed = True
        label = {"Left": "Right", "Right": "Left"}[side] if mirrored else side
        return replace(hands[0], label=label, score=max(hands[0].score, min_score))


class HandChoice:
    """The capture step: one hand held up alone for `hold_seconds` (at least 5 frames) chooses itself."""

    hold_seconds = 5.0

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.side = ""
        self.since: Optional[float] = None
        self.last_at: Optional[float] = None
        self.frames = 0

    def seconds_remaining(self, now: float) -> float:
        return self.hold_seconds if self.since is None else max(0.0, self.hold_seconds - (now - self.since))

    def observe(self, hands: Sequence[RawHand], mirrored: bool, now: float) -> str:
        side = physical_side(hands[0], mirrored) if len(hands) == 1 else ""
        if not side:
            self.reset()
            return ""
        if side != self.side or self.last_at is None or now - self.last_at > .25:
            self.reset()
            self.side, self.since = side, now
        if self.last_at is None or now > self.last_at:
            self.last_at = now
            self.frames += 1
        return side if self.frames >= 5 and self.seconds_remaining(now) == 0 else ""
