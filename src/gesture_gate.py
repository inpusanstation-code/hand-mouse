"""
Intent check with the trained gesture model (2026-11-05): the rules still decide, the TCN confirms.

models/gesture_tcn.onnx (scripts/train_tcn.py) looks at the last 0.5 s of the hand (src/tcn_features.py) every frame
and gives probabilities for none / thumb_index / thumb_ring. When the rules want to
- right click (thumb + ring): the click goes out only if the model also saw thumb_ring (probability >= threshold for
  `frames_in_a_row` frames within the last `lookback` s). Not yet? The click waits up to `gate_wait` s for it, then
  is dropped.
- start a scroll grab (thumb + index): the grab starts only once the model saw thumb_index; until then the cursor
  just stays put. Once allowed, the grab runs to its end.
Everything else (left click, cursor, the other gestures) is untouched: the model was trained on these two only.
In the held-out postures of the first recording this cut the misfires while moving with a half fist from 51 to 6
(docs/recording.md). Switch: the "손짓 확인 (TCN)" toggle on the Qt screen, or "tcn_gate" in the config.
"""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

import numpy as np

from src.gesture_catalog import NAMES
from src.spatial_features import extract_spatial_features
from src.spatial_mlp import (
    DEFAULT_SPATIAL_MLP_PATH,
    STATIC_POSTURE_LABELS,
    SpatialMlpModel,
    blend_tcn_and_spatial_probs,
)
from src.tcn_features import FEATURE_VERSION, frame_features, windows

DEFAULT_MODEL = Path(__file__).resolve().parents[1] / "models" / "gesture_tcn.onnx"
DEFAULT_SPATIAL_MODEL = DEFAULT_SPATIAL_MLP_PATH
DEFAULT_THRESHOLD = 0.7
GATED = {"right_click": "thumb_ring", "left_click": "thumb_middle", "scroll_grab": "thumb_index",
         "task_switcher": "thumb_pinky", "show_desktop": "palm_side"}


def load_spatial_mlp(spatial_path: Path = DEFAULT_SPATIAL_MODEL) -> Optional[SpatialMlpModel]:
    """Load `models/spatial_mlp.json` if present and valid, else return None."""
    try:
        p = Path(spatial_path)
        if p.is_file():
            return SpatialMlpModel.load(p)
    except Exception:
        pass
    return None


def load_predictor(model_path: Path = DEFAULT_MODEL) -> Tuple[Callable[[np.ndarray], np.ndarray], Dict[str, Any]]:
    """(window -> class probabilities, model info). Raises if the model or onnxruntime is missing."""
    from src.gesture_models import load_single, compose_predictor
    predict, info = load_single(model_path, FEATURE_VERSION)
    predict, info = compose_predictor(model_path, predict, info)
    spatial_candidate = Path(model_path).parent / "spatial_mlp.json"
    if spatial_candidate.is_file():
        info = dict(info)
        info.setdefault("spatial_mlp_path", str(spatial_candidate))
    return predict, info


class GestureGate:
    def __init__(self, predict: Callable[[np.ndarray], np.ndarray], info: Dict[str, Any],
                 config: Optional[Dict[str, Any]] = None,
                 spatial_model: Optional[SpatialMlpModel] = None) -> None:
        cfg = config or {}
        self.predict = predict
        self.classes: List[str] = list(info["classes"])
        independent = set(info.get("independent_gestures") or [])
        self.disabled_gestures: set[str] = set(info.get("disabled_gestures") or []) - independent
        self.window = int(info["window"])
        self.threshold = float(cfg.get("gate_threshold", info.get("threshold", 0.7)))
        self.k = int(cfg.get("gate_frames", info.get("frames_in_a_row", 3)))
        self.thresholds = {} if "gate_threshold" in cfg else info.get("gesture_thresholds", {})
        self.frame_counts = {} if "gate_frames" in cfg else info.get("gesture_frames", {})
        self.lookback = float(cfg.get("gate_lookback", 0.5))
        self.wait = float(cfg.get("gate_wait", 0.3))
        self.spatial_alpha = float(cfg.get("spatial_mlp_alpha", info.get("spatial_mlp_alpha", 0.42)))
        self.spatial_veto_threshold = float(cfg.get("spatial_veto_threshold", info.get("spatial_veto_threshold", 0.80)))
        self.spatial_boost_threshold = float(cfg.get("spatial_boost_threshold", info.get("spatial_boost_threshold", 0.85)))
        if spatial_model is None and cfg.get("spatial_mlp_enabled", True):
            sp_path = info.get("spatial_mlp_path")
            if sp_path:
                spatial_model = load_spatial_mlp(Path(sp_path))
        self.spatial_model: Optional[SpatialMlpModel] = spatial_model
        self._frames: Deque[Dict[str, Any]] = deque(maxlen=self.window + 1)
        self._probs: Deque[Tuple[float, np.ndarray]] = deque(maxlen=60)
        self._spatial_probs: Deque[Tuple[float, np.ndarray]] = deque(maxlen=60)
        self.last: Optional[np.ndarray] = None
        self.last_tcn: Optional[np.ndarray] = None
        self.last_spatial: Optional[np.ndarray] = None
        self._pending = None     # a held rule click (action, label, since)
        self._grab_ok = False
        self._continuous = None
        self.blocked = 0                                      # rule actions the model did not confirm
        self.passed = 0
        self.spatial_vetoed = 0
        self.spatial_boosted = 0
        self.last_note = ""

    def reset(self) -> None:
        self._frames.clear()
        self._probs.clear()
        self._spatial_probs.clear()
        self.last = None
        self.last_tcn = None
        self.last_spatial = None
        self._pending = None
        self._grab_ok = False
        self._continuous = None

    # ---------------------------------------------------------------- model
    def step(self, now: float, hand: Any, aspect: float) -> Optional[np.ndarray]:
        lm = None
        if hand is None or not getattr(hand, "world", None):
            self._frames.append({"t": now})
        else:
            lm = [[p.x, p.y, p.z] for p in hand.landmarks]
            self._frames.append({"t": now, "world": hand.world, "lm": lm})
        feats = frame_features(list(self._frames), aspect)
        tcn_probs = np.asarray(self.predict(windows(feats, self.window)[-1:]), dtype=np.float64)
        self.last_tcn = tcn_probs
        probs = tcn_probs
        if self.spatial_model is not None and lm is not None:
            s_vec = extract_spatial_features(lm)
            if s_vec is not None:
                sp_probs = self.spatial_model.predict_proba(s_vec)
                self.last_spatial = sp_probs
                self._spatial_probs.append((now, sp_probs))
                probs = blend_tcn_and_spatial_probs(
                    tcn_probs,
                    self.classes,
                    sp_probs,
                    self.spatial_model.classes,
                    alpha=self.spatial_alpha,
                    veto_threshold=self.spatial_veto_threshold,
                    boost_threshold=self.spatial_boost_threshold,
                )
        self._probs.append((now, probs))
        self.last = probs
        return probs

    def spatial_instant_confirmed(self, name: str) -> bool:
        """0-frame-lag fast confirmation when Spatial MLP is highly confident (`>= boost_threshold`)
        and TCN already shows emerging probability (`>= 0.45 * threshold`)."""
        if self.spatial_model is None or self.last_spatial is None or self.last_tcn is None:
            return False
        if name not in STATIC_POSTURE_LABELS or name not in self.classes or name in self.disabled_gestures:
            return False
        if name not in self.spatial_model.classes:
            return False
        si = self.spatial_model.classes.index(name)
        ti = self.classes.index(name)
        thr = float(self.thresholds.get(name, self.threshold))
        return float(self.last_spatial[si]) >= self.spatial_boost_threshold and float(self.last_tcn[ti]) >= max(0.32, thr * 0.5)

    def spatial_vetoes(self, name: str) -> bool:
        """True when 0-lag Spatial MLP is confident the hand is in neutral/resting posture ('none')
        and NOT in the requested static posture `name`."""
        if self.spatial_model is None or self.last_spatial is None:
            return False
        if name not in STATIC_POSTURE_LABELS or "none" not in self.spatial_model.classes:
            return False
        none_idx = self.spatial_model.classes.index("none")
        p_none = float(self.last_spatial[none_idx])
        p_target = float(self.last_spatial[self.spatial_model.classes.index(name)]) if name in self.spatial_model.classes else 0.0
        p_tcn = float(self.last_tcn[self.classes.index(name)]) if (self.last_tcn is not None and name in self.classes) else 0.0
        return p_none >= self.spatial_veto_threshold and p_target < 0.15 and p_tcn < 0.88

    def confirmed(self, name: str, now: float) -> bool:
        """The model saw `name` for k frames in a row within the last `lookback` s (or 0-lag Spatial MLP fast boost)."""
        if name not in self.classes or name in self.disabled_gestures:
            return False
        if self.spatial_vetoes(name):
            self.spatial_vetoed += 1
            return False
        if self.spatial_instant_confirmed(name):
            self.spatial_boosted += 1
            return True
        c = self.classes.index(name)
        threshold = self.thresholds.get(name, self.threshold)
        required = self.frame_counts.get(name, self.k)
        run = 0
        for t, p in self._probs:
            if now - t > self.lookback:
                continue
            run = run + 1 if p[c] >= threshold else 0
            if run >= required:
                return True
        return False

    def allows(self, name: str, now: float) -> bool:
        """Untrained gestures retain their existing rule behavior, including legacy 3-class models."""
        return name not in self.classes or name in self.disabled_gestures or self.confirmed(name, now)

    # ---------------------------------------------------------------- the check
    def filter(self, now: float, result: Any) -> Any:
        """Confirm only learned actions; continuous grabs need confirmation once at their start."""
        action = getattr(result, "action", None)
        label = GATED.get(action)
        if action == "drag_hold":
            label = "thumb_index_middle" if getattr(result, "active_gesture", "") == "thumb_index_middle_pinch" else "thumb_middle"
        continuous = action in ("scroll_grab", "drag_hold")
        if self._continuous != (action, label):
            self._continuous = None
        if action not in (None, "none", "move_cursor"):
            self._pending = None  # a new action supersedes a delayed click
        if label in self.classes and label not in self.disabled_gestures:
            if self._continuous == (action, label) or self.confirmed(label, now):
                if continuous:
                    self._continuous = (action, label)
                self.passed += 1
                self.last_note = "TCN 확인: " + NAMES.get(label, label)
                return result
            if not continuous:
                self._pending = (action, label, now)
            result.action = "none"
            result.is_moving = False
            self.last_note = "TCN 확인 대기: " + NAMES.get(label, label)
            return result
        if self._pending is not None:
            kind, pending_label, since = self._pending
            if now - since > self.wait:
                self._pending = None
                self.blocked += 1
                self.last_note = "TCN: 의도 확인 안 됨"
            elif self.confirmed(pending_label, now):
                self._pending = None
                self.passed += 1
                self.last_note = "TCN 확인: " + NAMES.get(pending_label, pending_label)
                if action in ("none", "move_cursor", None):
                    result.action = kind
        return result
