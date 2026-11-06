from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from src.gesture_gate import GestureGate
from src.spatial_features import SPATIAL_FEATURES, SPATIAL_FEATURE_VERSION, extract_spatial_features, session_spatial_features
from src.spatial_mlp import SpatialMlpModel, blend_tcn_and_spatial_probs, train_spatial_mlp


def _synthetic_hand(pinch_target: int | None = None):
    """Build 21 anatomically plausible 3D landmarks (`[x, y, z]`) with optional thumb pinch."""
    pts = np.zeros((21, 3), dtype=np.float64)
    # Wrist at (0.5, 0.8, 0.0), Middle MCP at (0.5, 0.55, 0.0)
    pts[0] = [0.50, 0.80, 0.00]
    base_x = {1: 0.38, 5: 0.43, 9: 0.50, 13: 0.56, 17: 0.62}
    # Thumb chain 1..4
    for k, ratio in enumerate((0.25, 0.50, 0.75, 1.0), start=1):
        pts[k] = [0.38 - 0.03 * ratio, 0.72 - 0.14 * ratio, -0.02 * ratio]
    # Four fingers (5..8, 9..12, 13..16, 17..20)
    for mcp in (5, 9, 13, 17):
        bx = base_x[mcp]
        pts[mcp] = [bx, 0.56, 0.0]
        pts[mcp + 1] = [bx, 0.46, -0.01]
        pts[mcp + 2] = [bx, 0.39, -0.015]
        pts[mcp + 3] = [bx, 0.32, -0.02]
    if pinch_target is not None:
        # Bring thumb tip (4) and target fingertip together
        mid = 0.5 * (pts[4] + pts[pinch_target])
        pts[4] = mid.copy()
        pts[pinch_target] = mid.copy() + np.array([0.002, 0.002, 0.0])
    landmarks = [SimpleNamespace(x=float(p[0]), y=float(p[1]), z=float(p[2])) for p in pts]
    world = [[float(p[0] - 0.5), float(p[1] - 0.6), float(p[2])] for p in pts]
    return SimpleNamespace(landmarks=landmarks, world=world), pts


def test_extract_spatial_features_96_dims_and_pinch_sensitivity():
    hand_open, pts_open = _synthetic_hand(None)
    hand_idx, pts_idx = _synthetic_hand(8)
    hand_ring, pts_ring = _synthetic_hand(16)

    f_open = extract_spatial_features(hand_open.landmarks)
    f_idx = extract_spatial_features(pts_idx.tolist())
    f_ring = extract_spatial_features([{"x": p[0], "y": p[1], "z": p[2]} for p in pts_ring])

    assert f_open is not None and f_open.shape == (SPATIAL_FEATURES,)
    assert f_idx is not None and f_idx.shape == (96,)
    assert f_ring is not None and f_ring.shape == (96,)
    assert np.isfinite(f_open).all()

    # Feature 68 is thumb-index 3D pinch distance; Feature 70 is thumb-ring 3D pinch distance
    assert f_idx[68] < f_open[68] * 0.25
    assert f_ring[70] < f_open[70] * 0.25

    batch, valid = session_spatial_features([{"lm": pts_open.tolist()}, {"lm": None}])
    assert batch.shape == (2, 96)
    assert valid.tolist() == [True, False]


def test_train_save_load_spatial_mlp_and_predict(tmp_path):
    _, pts_open = _synthetic_hand(None)
    _, pts_idx = _synthetic_hand(8)
    _, pts_ring = _synthetic_hand(16)

    rng = np.random.default_rng(7)
    xs, ys = [], []
    for cls_id, base_pts in enumerate((pts_open, pts_idx, pts_ring)):
        for _ in range(30):
            noisy = base_pts + rng.normal(0.0, 0.004, size=base_pts.shape)
            vec = extract_spatial_features(noisy)
            assert vec is not None
            xs.append(vec)
            ys.append(cls_id)

    x_arr = np.stack(xs)
    y_arr = np.array(ys, dtype=np.int64)
    classes = ("none", "thumb_index", "thumb_ring")

    model, metrics = train_spatial_mlp(x_arr, y_arr, classes=classes, epochs=35, seed=7)
    assert metrics.train_accuracy >= 95.0
    assert metrics.test_accuracy >= 90.0
    assert model.feat_dim == SPATIAL_FEATURES
    assert model.feature_version == SPATIAL_FEATURE_VERSION

    out_file = model.save(tmp_path / "spatial_mlp.json")
    reloaded = SpatialMlpModel.load(out_file)
    pred = reloaded.predict(extract_spatial_features(pts_ring))
    assert pred["action"] == "thumb_ring"
    assert pred["confidence"] > 0.7


def test_gesture_gate_spatial_mlp_zero_lag_veto_and_fast_boost():
    _, pts_open = _synthetic_hand(None)
    _, pts_ring = _synthetic_hand(16)
    rng = np.random.default_rng(11)

    xs, ys = [], []
    for cls_id, base_pts in enumerate((pts_open, pts_ring)):
        for _ in range(25):
            vec = extract_spatial_features(base_pts + rng.normal(0.0, 0.003, size=base_pts.shape))
            xs.append(vec)
            ys.append(cls_id)
    sp_model, _ = train_spatial_mlp(
        np.stack(xs),
        np.array(ys, dtype=np.int64),
        classes=("none", "thumb_ring"),
        epochs=35,
    )

    info = {"classes": ["none", "thumb_ring"], "window": 15, "threshold": 0.7, "frames_in_a_row": 3}

    # Case 1: TCN falsely outputs 0.75 for thumb_ring on a single frame while hand is actually open ('none').
    # Spatial MLP sees 'none' (>= 0.80) with 0-frame lag and vetoes the false click.
    gate_veto = GestureGate(lambda _w: np.array([0.25, 0.75]), {**info, "frames_in_a_row": 1}, spatial_model=sp_model)
    hand_open, _ = _synthetic_hand(None)
    gate_veto.step(0.0, hand_open, 0.5625)
    res_veto = gate_veto.filter(0.0, SimpleNamespace(action="right_click", is_moving=False))
    assert res_veto.action == "none"
    assert gate_veto.spatial_vetoed >= 1

    # Case 2: TCN is still warming up (0.50 < 0.70 threshold, and only 1 frame instead of k=3),
    # but Spatial MLP is >0.85 confident on frame 1 that the hand is pinching thumb_ring -> instant 0-lag confirmation!
    gate_boost = GestureGate(lambda _w: np.array([0.50, 0.50]), info, spatial_model=sp_model)
    hand_ring, _ = _synthetic_hand(16)
    gate_boost.step(0.0, hand_ring, 0.5625)
    res_boost = gate_boost.filter(0.0, SimpleNamespace(action="right_click", is_moving=False))
    assert res_boost.action == "right_click"
    assert gate_boost.spatial_boosted >= 1


def test_blend_tcn_and_spatial_probs_batch_and_single():
    classes = ["none", "thumb_index", "thumb_ring"]
    tcn_p = np.array([0.40, 0.05, 0.55])
    sp_p = np.array([0.02, 0.02, 0.96])
    blended = blend_tcn_and_spatial_probs(tcn_p, classes, sp_p, classes)
    assert blended.shape == (3,)
    assert np.isclose(blended.sum(), 1.0)
    assert blended[2] > tcn_p[2]


def test_extract_record_handles_numpy_array_landmarks():
    from pathlib import Path
    from src.capture_dataset import _extract_record

    _, lm_pts = _synthetic_hand(8)
    arr = np.asarray(lm_pts, dtype=np.float32)
    frames = [
        {"t": 0.0, "lm": arr, "world": arr.copy(), "label": {"phase": "do", "target": "thumb_index"}},
        {"t": 0.033, "lm": arr.copy(), "world": arr.copy(), "label": {"phase": "do", "target": "thumb_index"}},
    ]
    rec = _extract_record(Path("synthetic.jsonl.gz"), {"posture": 0, "complete": True}, frames, slim_frames=True)
    assert rec["spatial_features"].shape == (2, SPATIAL_FEATURES)
    assert np.any(rec["spatial_features"][0] != 0.0)

