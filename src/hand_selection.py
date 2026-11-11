"""Select one physical hand from camera detections."""
import copy


def physical_side(detection, mirrored):
    side = detection.handedness
    if side not in ("Left", "Right") or not detection.score >= .75:
        return ""
    return {"Left": "Right", "Right": "Left"}[side] if mirrored else side


def selected_detection(detections, side, mirrored):
    matches = [hand for hand in detections if side and physical_side(hand, mirrored) == side]
    return matches[0] if len(matches) == 1 else None


SAME_HAND_OVERLAP = .6   # share of the smaller box covered by the other: the same hand found twice


def _box(detection):
    xs = [p.x for p in detection.landmarks]
    ys = [p.y for p in detection.landmarks]
    return min(xs), min(ys), max(xs), max(ys)


def merge_duplicates(detections):
    """MediaPipe sometimes returns one hand twice (2026-11-11 failure logs: 'Left,Left' 206 and 'Right,Right' 93 frames out
    of 5248, each time dropping the control hand because two candidates matched). Of two boxes that mostly cover each other
    the higher score stays. Two real hands do not overlap that much."""
    if len(detections) < 2:
        return list(detections)
    kept = []
    for d in sorted(detections, key=lambda d: -float(getattr(d, "score", 0.0) or 0.0)):
        ax0, ay0, ax1, ay1 = _box(d)
        a_area = max(1e-9, (ax1 - ax0) * (ay1 - ay0))
        same = False
        for k in kept:
            bx0, by0, bx1, by1 = _box(k)
            inter = max(0.0, min(ax1, bx1) - max(ax0, bx0)) * max(0.0, min(ay1, by1) - max(ay0, by0))
            if inter / min(a_area, max(1e-9, (bx1 - bx0) * (by1 - by0))) >= SAME_HAND_OVERLAP:
                same = True
                break
        if not same:
            kept.append(d)
    return kept


def _center_and_size(detection):
    """Centre of the landmark box and its longer side, in normalized frame units."""
    xs = [p.x for p in detection.landmarks]
    ys = [p.y for p in detection.landmarks]
    return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2), max(max(xs) - min(xs), max(ys) - min(ys))


class HandFollower:
    """Keeps the control hand when a small hand's left/right reading flips or loses confidence (docs/far-hand-loss.md, 22).

    The strict rule of selected_detection always comes first and is the only way to start following. Afterwards a single
    detection in about the same place and of about the same size counts as the same hand, whatever its reading says.
    The limits keep the other hand out: the gap since the last accepted frame, and the time since a strict reading."""

    def __init__(self, max_gap=.5, max_unconfirmed=3.0, reach=1.5, min_reach=.05, max_size_change=2.0):
        self.max_gap = max_gap
        self.max_unconfirmed = max_unconfirmed
        self.reach = reach
        self.min_reach = min_reach
        self.max_size_change = max_size_change
        self.reset()

    def reset(self):
        self.followed = False  # the last select() accepted a hand only through this class
        self._side = ""
        self._center = None
        self._size = 0.0
        self._seen_at = None
        self._confirmed_at = None

    def _remember(self, center, size, now):
        self._center, self._size, self._seen_at = center, size, now

    def _same_hand(self, center, size):
        if size <= 0 or not 1 / self.max_size_change <= size / self._size <= self.max_size_change:
            return False
        limit = max(self.reach * self._size, self.min_reach)
        return abs(center[0] - self._center[0]) <= limit and abs(center[1] - self._center[1]) <= limit

    def select(self, detections, side, mirrored, now):
        if side != self._side:
            self.reset()
            self._side = side
        self.followed = False
        detections = merge_duplicates(detections)
        chosen = selected_detection(detections, side, mirrored)
        if chosen is not None:
            self._remember(*_center_and_size(chosen), now)
            self._confirmed_at = now
            return chosen
        if not side or not detections or self._center is None:
            return None
        if now - self._seen_at > self.max_gap or now - self._confirmed_at > self.max_unconfirmed:
            return None
        # the one detection in about the same place and of about the same size (2026-11-11: with two detections it used
        # to give up even when only one of them could be the followed hand)
        near = [(d, *_center_and_size(d)) for d in detections]
        near = [(d, c, s) for d, c, s in near if self._same_hand(c, s)]
        if len(near) != 1:
            return None
        found, center, size = near[0]
        self._remember(center, size, now)
        self.followed = True
        hand = copy.copy(found)
        hand.handedness = {"Left": "Right", "Right": "Left"}[side] if mirrored else side
        return hand


class HandSelection:
    hold_seconds = 5.0

    def seconds_remaining(self, now):
        return self.hold_seconds if self.since is None else max(0.0, self.hold_seconds - (now - self.since))

    def reset(self):
        self.side = ""
        self.since = None
        self.last_at = None
        self.frames = 0

    def __init__(self):
        self.reset()

    def observe(self, detections, mirrored, now):
        side = physical_side(detections[0], mirrored) if len(detections) == 1 else ""
        if not side:
            self.reset()
            return ""
        if side != self.side or self.last_at is None or now - self.last_at > .25:
            self.reset()
            self.side = side
            self.since = now
        if self.last_at is None or now > self.last_at:
            self.last_at = now
            self.frames += 1
        return side if self.frames >= 5 and self.seconds_remaining(now) == 0 else ""
