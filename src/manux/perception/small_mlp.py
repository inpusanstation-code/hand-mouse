"""A one-hidden-layer classifier for hand poses, trained in about a second with numpy (no torch, no files).

Used by gesture registration (perception.pose_registration): the person's pose against their resting hands. Inputs are
standardised; the two classes are weighted equally; full-batch gradient descent with a little weight decay.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np


class SmallMLP:
    def __init__(self, mu, sd, w1, b1, w2, b2) -> None:
        self.mu, self.sd = np.asarray(mu, np.float32), np.asarray(sd, np.float32)
        self.w1, self.b1 = np.asarray(w1, np.float32), np.asarray(b1, np.float32)
        self.w2, self.b2 = np.asarray(w2, np.float32), float(b2)
        if self.w1.shape != (self.mu.shape[0], self.b1.shape[0]) or self.w2.shape != self.b1.shape:
            raise ValueError("small MLP has inconsistent sizes")

    @property
    def inputs(self) -> int:
        return int(self.mu.shape[0])

    def score(self, x: np.ndarray) -> np.ndarray:
        z = (np.atleast_2d(np.asarray(x, np.float32)) - self.mu) / self.sd
        return 1.0 / (1.0 + np.exp(-(np.tanh(z @ self.w1 + self.b1) @ self.w2 + self.b2)))

    def to_dict(self) -> Dict[str, Any]:
        r = lambda a: np.round(a, 6).tolist()
        return {"mu": r(self.mu), "sd": r(self.sd), "w1": r(self.w1), "b1": r(self.b1), "w2": r(self.w2), "b2": self.b2}

    @classmethod
    def from_dict(cls, doc: Dict[str, Any]) -> "SmallMLP":
        return cls(doc["mu"], doc["sd"], doc["w1"], doc["b1"], doc["w2"], doc["b2"])


def train(pos: np.ndarray, neg: np.ndarray, *, hidden: int = 24, steps: int = 300, l2: float = 1e-3,
          seed: int = 0, rate: float = 1.0, init: Optional[SmallMLP] = None) -> SmallMLP:
    pos, neg = np.asarray(pos, np.float32), np.asarray(neg, np.float32)
    if len(pos) == 0 or len(neg) == 0:
        raise ValueError("need examples of both the pose and the rest")
    x = np.concatenate([pos, neg])
    y = np.r_[np.ones(len(pos), np.float32), np.zeros(len(neg), np.float32)]
    rng = np.random.default_rng(seed)
    mu, sd = x.mean(0), x.std(0) + 1e-4
    z = (x - mu) / sd
    w1 = rng.normal(0, .3, (z.shape[1], hidden)).astype(np.float32)
    b1 = np.zeros(hidden, np.float32)
    w2 = rng.normal(0, .3, hidden).astype(np.float32)
    b2 = 0.0
    weight = np.where(y > .5, .5 / len(pos), .5 / len(neg)).astype(np.float32)
    for _ in range(steps):
        h = np.tanh(z @ w1 + b1)
        p = 1 / (1 + np.exp(-(h @ w2 + b2)))
        g = (p - y) * weight
        gh = np.outer(g, w2) * (1 - h ** 2)
        w2 -= rate * (h.T @ g + l2 * w2)
        b2 -= rate * float(g.sum())
        w1 -= rate * (z.T @ gh + l2 * w1)
        b1 -= rate * gh.sum(0)
    return SmallMLP(mu, sd, w1, b1, w2, b2)
