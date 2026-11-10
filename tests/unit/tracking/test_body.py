"""Body/head skeleton guide (tracking.body_assist): synthetic points only, no camera or model."""
from manux.core.contracts import FrameInfo
from manux.tracking.body import BodyGuide, guide_roi, pose_label
from manux.tracking.landmarker import RawHand
from manux.tracking.tracker import HandTracker

W, H = 1280, 720


def skeleton(wrist=(.30, .60), elbow=(.30, .45), other=(.70, .60), vis=.9):
    """33 points; the Pose 'Left' arm (13, 15) at elbow/wrist, the 'Right' wrist at `other`."""
    pts = [(.5, .3, vis)] * 33
    pts[11], pts[12] = (.4, .35, vis), (.6, .35, vis)          # shoulders 256 px apart
    pts[13], pts[15] = (*elbow, vis), (*wrist, vis)
    pts[14], pts[16] = (.70, .45, vis), (*other, vis)
    return tuple(pts)


def hand_at(cx, cy, size=.04, label="Left", score=.95):
    return RawHand(tuple((cx + size * (i % 5 - 2) / 4, cy + size * (i // 5 - 2) / 4, 0.) for i in range(21)), label, score)


def test_mirrored_physical_right_is_pose_left_like_the_hand_label():
    assert pose_label("Right", True) == "Left" and pose_label("Right", False) == "Right"


def test_square_sits_past_the_wrist_along_the_forearm():
    x0, y0, x1, y1 = guide_roi(skeleton(), "Right", True, W, H)
    assert x1 - x0 == y1 - y0 >= 192
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    assert abs(cx - .30 * W) < 2 and cy > .60 * H              # pushed down, away from the elbow


def test_recent_hand_picks_the_nearest_wrist_and_its_size():
    roi = guide_roi(skeleton(), "Right", True, W, H, last=(.70 * W, .62 * H, 100.))
    assert roi[0] < .70 * W < roi[2] and roi[2] - roi[0] == 240


def test_no_square_for_invisible_wrist_or_big_hand():
    assert guide_roi(skeleton(vis=.2), "Right", True, W, H) is None
    assert guide_roi(skeleton(), "Right", True, W, H, last=(400, 400, .5 * H)) is None
    assert guide_roi((), "Right", True, W, H) is None


class FakeLandmarker:
    last_detect_ms = 1.0

    def __init__(self, crop_hand):
        self.crop_hand, self.calls = crop_hand, []

    def detect(self, image, roi=None):
        self.calls.append(roi)
        return [] if roi is None else [self.crop_hand]


class FakePose:
    def __init__(self, path, points=None):
        self.points, self.runs = points or skeleton(), 0

    def detect_all(self, image, now):
        self.runs += 1
        return self.points

    def close(self): pass


def frame(t=1.0):
    return FrameInfo(seq=1, t=t, width=W, height=H, mirrored=True)


def test_lost_hand_is_found_in_the_skeleton_square():
    lm = FakeLandmarker(hand_at(.30, .65))
    tracker = HandTracker(lm)
    tracker.body = BodyGuide("unused.task", factory=FakePose)
    result = tracker.step(frame(), object(), "Right")
    assert result.hand is not None and result.path == "full>body" and tracker.body.used == 1
    assert lm.calls[0] is None and lm.calls[1] == tracker.body.roi


def test_without_guide_or_with_failed_pose_tracking_is_unchanged():
    lm = FakeLandmarker(hand_at(.30, .65))
    assert HandTracker(lm).step(frame(), object(), "Right").hand is None and lm.calls == [None]

    def broken(path): raise FileNotFoundError(path)
    tracker = HandTracker(lm)
    tracker.body = BodyGuide("missing.task", factory=broken)
    assert tracker.step(frame(), object(), "Right").hand is None and tracker.body.failed


def test_tracked_hand_runs_pose_only_every_n_frames():
    class Found(FakeLandmarker):
        def detect(self, image, roi=None):
            return [self.crop_hand]
    tracker = HandTracker(Found(hand_at(.3, .6)))
    tracker.body = BodyGuide("unused.task", every_n=3, factory=FakePose)
    for i in range(6):
        tracker.step(frame(1 + i / 30), object(), "Right")
    assert tracker.body._tracker.runs == 2


def test_drawn_skeleton_is_steadier_than_raw_and_does_not_blink():
    import random
    from manux.tracking.body import SkeletonSmoother
    rnd, smooth = random.Random(0), SkeletonSmoother()
    raw_x, out_x, shown = [], [], []
    for i in range(90):                                     # still body, 3 s at 30 fps, ~1% jitter
        x = .5 + rnd.uniform(-.01, .01)
        vis = .5 + (.05 if i % 2 else -.05)                 # visibility hovering at the threshold
        pts = [(x, .5, .9)] * 33
        pts[0] = (x, .5, vis)
        out = smooth(pts, i / 30)
        raw_x.append(x); out_x.append(out[1][0]); shown.append(out[0][2] >= .5)
    spread = lambda v: max(v[30:]) - min(v[30:])
    assert spread(out_x) < .5 * spread(raw_x)
    assert sum(a != b for a, b in zip(shown[30:], shown[31:])) == 0


def test_preview_view_is_smoothed_but_search_points_stay_raw():
    class FakePose:
        def __init__(self, _): self.n = 0
        def detect_all(self, image, t):
            self.n += 1
            return tuple([(.5 + (.02 if self.n % 2 else -.02), .5, .9)] * 33)
        def close(self): pass
    g = BodyGuide("unused.task", every_n=1, factory=FakePose)
    for i in range(10):
        raw = g.step(object(), i / 30, need=False)
    assert raw[0][0] in (.48, .52)
    assert abs(g.fresh_view(9 / 30)[0][0] - .5) < .02
    assert g.fresh_view(2.0) is None
