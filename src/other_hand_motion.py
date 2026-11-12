"""Motion mode with the other hand (2026-11-12, "모션모드는 왼손으로 하게 만들수 있나?").

Entering motion mode took a thumbs-up held still for 0.8 s and leaving it the same again, and while it was on the cursor
stood still. The Qt screen already finds up to two hands and used only the control hand. Now the other hand (the left one
for a right-handed user) is a motion hand of its own:

  arm    the other hand shown open (all four fingers out) or with the index alone, fairly still, for `motion_other_arm` s
  swipe  the same strokes as motion mode (MotionMode: the open hand = tabs, the index alone = forward / back, the user's
         own registered motions), read from that hand
  end    the hand lowered out of view for `motion_other_lost` s; nothing to switch off

The control hand goes on moving the cursor and clicking the whole time.

Which detection is the other hand (`other_hand`): MediaPipe sometimes returns one hand twice or flips its left / right
reading (failure logs 2026-11-11: 'Left,Left' 206 and 'Right,Right' 93 frames of 5,248). So the other hand must read as the
opposite side of the control hand AND sit apart from the control hand's box; a reading on top of it is the control hand.

Left out on purpose: the downward stroke (Win+Down) - a raised hand is lowered to end, and that is a downward stroke.
Not measured: how often a hand that comes into view by chance (the face, the keyboard) is read as a swipe. The recordings
keep only the control hand.
"""
from __future__ import annotations

import math
from typing import Any, Optional, Sequence

from src.hand_selection import _box, _center_and_size, merge_duplicates
from src.motion_mode import MotionEvent, MotionMode, hand_features

APART = .2          # share of the smaller box the two may overlap and still be two hands (merge_duplicates: .6 = one hand)


def _overlap(a, b) -> float:
    ax0, ay0, ax1, ay1 = _box(a)
    bx0, by0, bx1, by1 = _box(b)
    inter = max(0.0, min(ax1, bx1) - max(ax0, bx0)) * max(0.0, min(ay1, by1) - max(ay0, by0))
    small = min(max(1e-9, (ax1 - ax0) * (ay1 - ay0)), max(1e-9, (bx1 - bx0) * (by1 - by0)))
    return inter / small


SIDE_SCORE = .5     # the left / right reading of a hand on its own (selected_detection wants .75 for the control hand)
NEAR = .8           # hand sizes: about where the other hand was a moment ago (two hands sit .3-.4 apart, boxes .15-.27)


def _side(d, mirrored: bool) -> str:
    side = getattr(d, "handedness", "")
    if side not in ("Left", "Right") or not float(getattr(d, "score", 0.0) or 0.0) >= SIDE_SCORE:
        return ""
    return {"Left": "Right", "Right": "Left"}[side] if mirrored else side


def near(d, last) -> bool:
    """Is `d` about where `last` = (centre, size) was?"""
    if not last or last[1] <= 0:
        return False
    (cx, cy), size = _center_and_size(d)
    (lx, ly), ls = last
    reach = NEAR * max(ls, size)
    return abs(cx - lx) <= reach and abs(cy - ly) <= reach


def other_hand(detections: Sequence[Any], control, control_side: str, mirrored: bool, last=None):
    """The hand that is not the control hand. None without a control side set, or when it cannot be told.

    2026-11-12 ("손날 ㄱ각도가 되면 왼손 인식이 끊어진다"): of the frames with two hands found apart, the left hand was
    dropped in 350 because its left / right reading was under .75 and in 348 because both read as the same side. A hand
    apart from the control hand is a second hand whatever it reads, so: with the control hand known, the one other hand
    (apart from it) is it; without the control hand, the opposite reading (score .5 and up) or the place where the other
    hand was a moment ago (`last` = its centre and size)."""
    if control_side not in ("Left", "Right"):
        return None
    want = "Right" if control_side == "Left" else "Left"
    rest = [d for d in merge_duplicates(list(detections))
            if control is None or not (d is control or _overlap(d, control) > APART)]
    if not rest:
        return None
    if control is not None and len(rest) == 1:
        return rest[0]
    opposite = [d for d in rest if _side(d, mirrored) == want]
    if len(opposite) == 1:
        return opposite[0]
    there = [d for d in rest if near(d, last)]
    return there[0] if len(there) == 1 else None


class OtherHandMotion:
    """Motion mode run on the other hand: armed by showing it open, ended by lowering it (see the module text)."""

    def __init__(self, config: Optional[dict] = None) -> None:
        cfg = dict(config or {})
        # no downward stroke, built in or the user's own (lowering the hand is one: the user's "fist down = F5" fired as the
        # left hand dropped, 2026-11-12), no timeouts: the hand being there is the mode. Smaller, slower strokes count.
        from src.motion_mode import DEFAULTS
        cfg.update({"motion_close_enabled": 0.0, "motion_custom_down": 0.0, "motion_timeout": 0.0, "motion_hand_lost_exit": 0.0,
                    "motion_swipe_min_dx": float(cfg.get("motion_other_min_dx", DEFAULTS["motion_other_min_dx"])),
                    "motion_swipe_min_speed": float(cfg.get("motion_other_min_speed", DEFAULTS["motion_other_min_speed"]))})
        self.motion = MotionMode(cfg)
        self._open_since: Optional[float] = None
        self._anchor = (0.0, 0.0)
        self._lost_since: Optional[float] = None

    @property
    def active(self) -> bool:
        return self.motion.active

    def cfg(self, key: str) -> float:
        return self.motion.cfg(key)

    def arming(self, now: float) -> float:
        """0..1 while the open hand is being held to arm, 0 otherwise."""
        if self.active or self._open_since is None:
            return 0.0
        return max(0.0, min(1.0, (now - self._open_since) / max(1e-6, self.cfg("motion_other_arm"))))

    def reset(self, now: float = 0.0) -> Optional[MotionEvent]:
        self._open_since, self._lost_since = None, None
        if self.motion.active:
            ev = self.motion.update(now, None, request="off")
            ev.info["why"] = "off"
            return ev
        return None

    def step(self, now: float, landmarks: Optional[Sequence[Any]]) -> Optional[MotionEvent]:
        if landmarks is None:
            self._open_since = None
            if not self.motion.active:
                return None
            if self._lost_since is None:
                self._lost_since = now
            if now - self._lost_since >= self.cfg("motion_other_lost"):
                self._lost_since = None
                ev = self.motion.update(now, None, request="off")
                ev.info["why"] = "lowered"
                return ev
            return None
        self._lost_since = None
        if self.motion.active:
            ev = self.motion.update(now, landmarks)
            if ev is not None and ev.kind == "exit":
                self._open_since = None       # (a thumbs-up held on that hand) shown open again, it arms again
            return ev
        f = hand_features(landmarks)
        curls = f["curl"]
        v_hand = min(curls[:2]) >= self.cfg("motion_index_open") and max(curls[2:]) <= self.cfg("motion_index_fold")
        if self.motion.stroke_shape(curls) is None and not v_hand:   # shown open, the index alone or a V (2026-11-12)
            self._open_since = None
            return None
        palm = f["palm"]
        if self._open_since is None or math.hypot(palm[0] - self._anchor[0], palm[1] - self._anchor[1]) > self.cfg("motion_other_still"):
            self._open_since, self._anchor = now, palm   # (moving on: the hold starts again from here)
            return None
        if now - self._open_since >= self.cfg("motion_other_arm"):
            self._open_since = None
            ev = self.motion.update(now, None, request="on")
            ev.info["how"] = "other_hand"
            return ev
        return None

