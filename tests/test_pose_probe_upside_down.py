"""Upside-down V told by the "보여주기" probe (2026-11-11 log 091241): a frame no rule matched (ring finger 1.6) was
filled in as the upright V because the nearest-shape table has no direction."""
from types import SimpleNamespace

from src.pose_probe import hand_posture, nearest_posture

FRAME = [[0.7159, -0.1089, 0.0], [0.599, 0.0086, -0.0461], [0.5556, 0.2176, -0.1025], [0.5883, 0.3914, -0.1421], [0.6409, 0.5169, -0.1801], [0.5765, 0.188, -0.2269], [0.507, 0.4938, -0.2958], [0.4899, 0.6806, -0.3198], [0.4737, 0.8373, -0.3302], [0.6899, 0.172, -0.2235], [0.6743, 0.5601, -0.3063], [0.6659, 0.8088, -0.3265], [0.6641, 0.9974, -0.3388], [0.7885, 0.1718, -0.2059], [0.7302, 0.5108, -0.2579], [0.6878, 0.4578, -0.2162], [0.6779, 0.3623, -0.1776], [0.8545, 0.1808, -0.1893], [0.7906, 0.4597, -0.2058], [0.7514, 0.4127, -0.1614], [0.7468, 0.3252, -0.124]]


def test_unmatched_upside_down_v_is_told_as_upside_down():
    pts = [SimpleNamespace(x=p[0], y=p[1], z=p[2]) for p in FRAME]
    assert hand_posture(pts, 720 / 1280) == ""
    assert nearest_posture(FRAME) == "v_sign_down"


def test_the_upright_mirror_of_it_stays_v():
    flipped = [[p[0], 1.0 - p[1], p[2]] for p in FRAME]
    assert nearest_posture(flipped) == "v_sign"


def test_the_result_keeps_a_picture_of_a_frame_told_as_its_shape():
    import numpy as np
    from src.pose_probe import PoseProbe, hand_shot
    pts = [SimpleNamespace(x=p[0], y=p[1], z=p[2]) for p in FRAME]
    frame = np.zeros((720, 1280, 3), np.uint8)
    shot = hand_shot(frame, pts)
    assert shot is not None and shot.shape == (160, 160, 3) and shot.any()      # the joints are drawn on it
    probe = PoseProbe()
    probe.start(0.0)
    for i in range(30):
        marked = shot.copy()
        marked[0, 0, 0] = i                                                     # which frame it came from
        probe.step(3.1 + i / 30, hand_posture(pts, probe.aspect), lm=FRAME, shot=marked)
    probe.finish_if_due(10.0)
    # 2026-11-11: the rules alone do not know this frame, so it is "not in the list" (it used to be filled in as the
    # nearest shape); the picture and the replay of the look are kept all the same
    assert probe.result["unknown"] and probe.result["posture"] == ""
    assert probe.shot is not None and probe.shot[0, 0, 0] == 15                 # the middle one
    assert [int(c[0, 0, 0]) for c in probe.clip] == list(range(30))             # every picture in order, for the replay
    seq = probe.shot_seq
    probe.start(20.0)
    probe.finish_if_due(30.0)                                                   # no hand: failed, no picture
    assert probe.shot is None and probe.clip == [] and probe.shot_seq == seq + 1


def test_a_hand_off_the_frame_gives_no_picture():
    import numpy as np
    from src.pose_probe import hand_shot
    off = [SimpleNamespace(x=2.0 + p[0], y=p[1], z=0.0) for p in FRAME]
    assert hand_shot(np.zeros((720, 1280, 3), np.uint8), off) is None
