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


SCORE_TIE = .2           # scores this close do not decide between two readings of one hand
PART_RATIO = 1.5         # one reading this many times the other's size: the small one is a part of the hand


def merge_duplicates(detections, last=None):
    """MediaPipe sometimes returns one hand twice (2026-11-11 failure logs: 'Left,Left' 206 and 'Right,Right' 93 frames out
    of 5248, each time dropping the control hand because two candidates matched). Of two boxes that mostly cover each other
    one stays. Two real hands do not overlap that much.

    Which one (2026-11-11 evening, "가상 손이 위로 점프 튀었다가 제자리로 2번 정도 반복"): the higher score used to stay, but the
    second reading is a small hand found inside the real one (a third of its size, at the fingers: above its centre) and
    the two scores are .97-1.00 each - so every few frames the small one won, and the drawn hand jumped up by half a hand
    and back (failure logs of that evening: one hand returned twice in 494 frames, the small reading used in 130, 48
    switches from one frame to the next). Now, with scores within SCORE_TIE: a reading PART_RATIO times the other's size
    stays (the small one is a part of the hand); of two of about one size the one most like the hand of the frame before
    (`last` = its box centre and longer side), else the higher score."""
    if len(detections) < 2:
        return list(detections)
    import math

    def score(d):
        return float(getattr(d, "score", 0.0) or 0.0)

    def better(a, b):
        """Does reading `a` stay instead of `b` (two readings of one hand)?"""
        if abs(score(a) - score(b)) > SCORE_TIE:
            return score(a) > score(b)
        (ca, sa), (cb, sb) = _center_and_size(a), _center_and_size(b)
        if max(sa, sb) >= PART_RATIO * max(1e-9, min(sa, sb)):
            return sa > sb
        if last is not None and last[1] > 0:
            def far(c, size):
                return abs(math.log(max(size, 1e-9) / last[1])) + math.hypot(c[0] - last[0][0], c[1] - last[0][1]) / last[1]
            return far(ca, sa) < far(cb, sb)
        return score(a) > score(b)

    kept = []
    for d in detections:
        ax0, ay0, ax1, ay1 = _box(d)
        a_area = max(1e-9, (ax1 - ax0) * (ay1 - ay0))
        same = None
        for n, k in enumerate(kept):
            bx0, by0, bx1, by1 = _box(k)
            inter = max(0.0, min(ax1, bx1) - max(ax0, bx0)) * max(0.0, min(ay1, by1) - max(ay0, by0))
            if inter / min(a_area, max(1e-9, (bx1 - bx0) * (by1 - by0))) >= SAME_HAND_OVERLAP:
                same = n
                break
        if same is None:
            kept.append(d)
        elif better(d, kept[same]):
            kept[same] = d
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
        recent = self._center is not None and self._seen_at is not None and now - self._seen_at <= self.max_gap
        detections = merge_duplicates(detections, (self._center, self._size) if recent else None)
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
