"""`pinch-shape-v1`: how much a hand looks like the person's own thumb + index pinch, from its whole shape.

The virtual hand clicks on a hand *posture*, not on two fingertips happening to touch (2026-11-10 request: "가상손 모드는
mediapipe pinch 판정으로 작동하는게 아니라 pinch모양을 하는 손동작으로 명령신호를 잡는게 핵심"). Fingertip distance
alone also closes for a relaxed, curled hand. This small model scores the 33 `pose-angles-v1` columns (rotation and
size free, perception.pose_angles) of frames whose fingertips look closed: 1 = the person's pinch shape, 0 = other
hands whose tips also look closed (resting, other gestures).

It is a personal model: trained on the person's recordings by `tools/train_pinch_shape.py`, stored outside the
repository in `<data>/models/virtual_hand/pinch_shape.json` (contracts: personal models stay in the user folder). No
file -> no gate (the contact rule alone, as before). numpy only; one tanh hidden layer.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import numpy as np

from manux.perception.pose_angles import FEATURE_VERSION, FEATURES, pose_angles

VERSION = "pinch-shape-v1"
FILE = Path("models") / "virtual_hand" / "pinch_shape.json"


class PinchShapeModel:
    def __init__(self, mu, sd, w1, b1, w2, b2, threshold: float = .5, info: Optional[Dict[str, Any]] = None) -> None:
        self.mu, self.sd = np.asarray(mu, float), np.asarray(sd, float)
        self.w1, self.b1 = np.asarray(w1, float), np.asarray(b1, float)
        self.w2, self.b2 = np.asarray(w2, float), float(b2)
        if self.mu.shape != (FEATURES,) or self.w1.shape[0] != FEATURES or self.w1.shape[1] != self.w2.shape[0]:
            raise ValueError("pinch shape model has the wrong size")
        self.threshold = float(threshold)
        self.info = dict(info or {})

    def score_features(self, x: np.ndarray) -> np.ndarray:
        z = (np.atleast_2d(np.asarray(x, float)) - self.mu) / self.sd
        return 1.0 / (1.0 + np.exp(-(np.tanh(z @ self.w1 + self.b1) @ self.w2 + self.b2)))

    def score(self, world) -> Optional[float]:
        """0..1 for one hand's 21 world joints; None when the joints are not usable."""
        x = pose_angles(world) if world is not None else None
        return None if x is None else float(self.score_features(x)[0])

    # ------------------------------------------------------------------ file
    def to_json(self) -> Dict[str, Any]:
        return {"version": VERSION, "features": FEATURE_VERSION, "threshold": self.threshold, "info": self.info,
                "mu": self.mu.tolist(), "sd": self.sd.tolist(), "w1": self.w1.tolist(), "b1": self.b1.tolist(),
                "w2": self.w2.tolist(), "b2": self.b2}

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(self.to_json()), encoding="utf-8")
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: Path) -> "PinchShapeModel":
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        if doc.get("version") != VERSION or doc.get("features") != FEATURE_VERSION:
            raise ValueError(f"not a {VERSION} model on {FEATURE_VERSION}")
        return cls(doc["mu"], doc["sd"], doc["w1"], doc["b1"], doc["w2"], doc["b2"], doc.get("threshold", .5),
                   doc.get("info"))


def load_optional(data_dir: Path) -> Optional[PinchShapeModel]:
    """The person's model, or None (missing or unreadable: the virtual hand then clicks on contact alone)."""
    path = Path(data_dir) / FILE
    try:
        return PinchShapeModel.load(path) if path.is_file() else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def train(x: np.ndarray, y: np.ndarray, *, hidden: int = 16, l2: float = 1e-3, steps: int = 300, seed: int = 0,
          threshold: float = .5, info: Optional[Dict[str, Any]] = None) -> PinchShapeModel:
    """Full-batch gradient descent, classes weighted equally. `x` (n, 33) pose-angles rows, `y` 1 = pinch."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) == 0 or y.min() == y.max():
        raise ValueError("need both pinch and not-pinch frames")
    rng = np.random.default_rng(seed)
    mu, sd = x.mean(0), x.std(0) + 1e-6
    z = (x - mu) / sd
    w1, b1 = rng.normal(0, .3, (z.shape[1], hidden)), np.zeros(hidden)
    w2, b2 = rng.normal(0, .3, hidden), 0.0
    weight = np.where(y > .5, .5 / y.mean(), .5 / (1 - y.mean())) / len(y)
    rate = 1.0
    for _ in range(steps):
        h = np.tanh(z @ w1 + b1)
        p = 1 / (1 + np.exp(-(h @ w2 + b2)))
        g = (p - y) * weight
        gh = np.outer(g, w2) * (1 - h ** 2)
        w2 -= rate * (h.T @ g + l2 * w2)
        b2 -= rate * g.sum()
        w1 -= rate * (z.T @ gh + l2 * w1)
        b1 -= rate * gh.sum(0)
    return PinchShapeModel(mu, sd, w1, b1, w2, b2, threshold, info)


def rows(frames: Sequence[Any]) -> np.ndarray:
    """pose-angles rows of world-joint lists (unusable ones dropped)."""
    out = [a for a in (pose_angles(w) for w in frames) if a is not None]
    return np.array(out, float).reshape(-1, FEATURES)
