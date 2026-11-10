"""Gestures added from a few demonstrations, in plain hand-pose space: no neural network, no torch, instant.

Ported from virtual-hand-20261110 `src/online/pose_memory.py` (and `ClassEntry` from `memory.py` there). A frame is the
63 numbers of the 21 joints in the hand's own frame (`local3d-v1` columns 0..62, `perception/local3d.py`). A frame is a
registered gesture only when it lies within that gesture's spread AND closer to it than to every other class, the
poses the app already knows included ("known" classes compete but are never reported). Adding one changes no
weights.

Measured in the source on one person's guided recordings (5 demonstrations from one session, scored on another):
missed 44% of the time (FRR), took another gesture or rest for the new one 5.3% (FAR). One session's demonstrations
are weak when the posture changes; demonstrate in the postures you will use.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from manux.perception.local3d import FEATURE_VERSION, frame_features

SCHEMA = "manux-pose-memory/1"
UNKNOWN = "unknown"
USER_SOURCE = "user_registered"
POSE_DIM = 63
CUSTOM_PROTOTYPES = 3
LIMIT_QUANTILE, LIMIT_FACTOR = .9, 1.5
RUN_FRAMES = 4                       # frames in a row before a registered gesture counts


@dataclass
class ClassEntry:
    label: str
    prototypes: np.ndarray           # (k, 63)
    threshold: float                 # distance beyond which a frame is not this class (inf for known classes)
    samples: int = 0
    demos: int = 0
    source: str = ""
    distance_mean: float = 0.0
    distance_std: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)


def pose_features(frames: Sequence[Mapping[str, Any]], aspect: float) -> np.ndarray:
    """(n, 63) from frames {"t", "lm", "world"}; a frame with a lost hand is all zeros (a hand nobody would make)."""
    return frame_features(frames, aspect)[:, :POSE_DIM].astype(np.float32)


def distances(x: np.ndarray, prototypes: np.ndarray) -> np.ndarray:
    """Root mean square joint distance to the nearest prototype, in hand sizes."""
    x = np.atleast_2d(np.asarray(x, dtype=np.float32))
    return np.sqrt(((x[:, None, :] - prototypes[None, :, :]) ** 2).sum(-1)).min(axis=1) / np.sqrt(21.0)


def pose_kmeans(x: np.ndarray, k: int, seed: int = 0, rounds: int = 8, max_points: int = 3000) -> np.ndarray:
    rng = np.random.default_rng(seed)
    x = np.asarray(x, dtype=np.float32)
    if len(x) > max_points:
        x = x[rng.choice(len(x), max_points, replace=False)]
    c = x[rng.integers(len(x))][None]
    while len(c) < min(k, len(x)):
        c = np.vstack([c, x[int(((x[:, None] - c[None]) ** 2).sum(-1).min(axis=1).argmax())]])
    for _ in range(rounds):
        owner = ((x[:, None] - c[None]) ** 2).sum(-1).argmin(axis=1)
        c = np.stack([x[owner == i].mean(axis=0) if (owner == i).any() else c[i] for i in range(len(c))])
    return c


class PoseMemory:
    def __init__(self, feature_version: str = FEATURE_VERSION) -> None:
        self.feature_version = feature_version
        self.classes: Dict[str, ClassEntry] = {}

    @property
    def labels(self) -> List[str]:
        return list(self.classes)

    def registered(self) -> List[ClassEntry]:
        return [e for e in self.classes.values() if e.source == USER_SOURCE]

    def add_known(self, label: str, poses: np.ndarray, *, k: int = 4, seed: int = 0, source: str = "known") -> ClassEntry:
        """A pose the app already has (or rest): registered gestures must beat it to count."""
        entry = ClassEntry(label, pose_kmeans(poses, k, seed), threshold=float("inf"), samples=len(poses), source=source)
        self.classes[label] = entry
        return entry

    def add_class(self, label: str, poses: np.ndarray, *, demo_ids: Optional[Sequence[int]] = None, source: str = USER_SOURCE,
                  seed: int = 0, extra: Optional[Dict[str, Any]] = None) -> ClassEntry:
        """A registered gesture. Its distance limit comes from each demonstration measured against the others."""
        if not label or label == UNKNOWN:
            raise ValueError("a class needs a real name")
        x = np.asarray(poses, dtype=np.float32)
        if x.ndim != 2 or len(x) == 0:
            raise ValueError("no poses")
        ids = np.zeros(len(x), dtype=int) if demo_ids is None else np.asarray(demo_ids)
        groups = np.unique(ids)
        if len(groups) >= 2:
            spread = np.concatenate([distances(x[ids == g], pose_kmeans(x[ids != g], CUSTOM_PROTOTYPES, seed)) for g in groups])
        else:
            spread = distances(x, pose_kmeans(x, CUSTOM_PROTOTYPES, seed))
        limit = float(np.quantile(spread, LIMIT_QUANTILE)) * LIMIT_FACTOR
        entry = ClassEntry(label, pose_kmeans(x, CUSTOM_PROTOTYPES, seed), threshold=max(limit, 1e-3), samples=len(x),
                           demos=len(groups), source=source, distance_mean=float(spread.mean()),
                           distance_std=float(spread.std()), extra=dict(extra or {}))
        self.classes[label] = entry
        return entry

    def remove_class(self, label: str) -> bool:
        return self.classes.pop(label, None) is not None

    def classify_arrays(self, x: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Class index per frame (-1 = none), and the distance to it."""
        x = np.atleast_2d(np.asarray(x, dtype=np.float32))
        entries = list(self.classes.values())
        if not entries:
            return np.full(len(x), -1), np.full(len(x), np.inf)
        d = np.stack([distances(x, e.prototypes) for e in entries], axis=1)
        limits = np.array([e.threshold for e in entries])
        allowed = np.where(d <= limits, d, np.inf)
        best = allowed.argmin(axis=1)
        rows = np.arange(len(x))
        index = np.where(np.isfinite(allowed[rows, best]), best, -1)
        return index, d[rows, best]

    def classify(self, pose: np.ndarray) -> Dict[str, Any]:
        index, dist = self.classify_arrays(pose)
        i = int(index[0])
        return {"label": self.labels[i] if i >= 0 else UNKNOWN, "distance": float(dist[0])}

    def copy(self) -> "PoseMemory":
        return PoseMemory.from_dict(self.to_dict())

    def to_dict(self) -> Dict[str, Any]:
        return {"schema": SCHEMA, "feature_version": self.feature_version,
                "classes": [{"label": e.label, "prototypes": np.round(e.prototypes, 5).tolist(),
                             "threshold": None if np.isinf(e.threshold) else e.threshold, "samples": e.samples,
                             "demos": e.demos, "source": e.source, "distance_mean": e.distance_mean,
                             "distance_std": e.distance_std, "extra": e.extra} for e in self.classes.values()]}

    @classmethod
    def from_dict(cls, doc: Mapping[str, Any]) -> "PoseMemory":
        if doc.get("schema") != SCHEMA:
            raise ValueError("not a pose memory")
        memory = cls(str(doc.get("feature_version", "")))
        for row in doc["classes"]:
            memory.classes[row["label"]] = ClassEntry(
                row["label"], np.asarray(row["prototypes"], dtype=np.float32),
                float("inf") if row["threshold"] is None else float(row["threshold"]), int(row["samples"]),
                int(row["demos"]), str(row["source"]), float(row["distance_mean"]), float(row["distance_std"]),
                dict(row.get("extra") or {}))
        return memory

    def save(self, path: Path | str) -> Path:
        """Atomic: a crash leaves the old file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.to_dict(), fh, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return path

    @classmethod
    def load(cls, path: Path | str) -> "PoseMemory":
        memory = cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
        if memory.feature_version != FEATURE_VERSION:
            raise ValueError(f"pose memory uses features {memory.feature_version}, the code has {FEATURE_VERSION}")
        return memory


class PoseRecognizer:
    """Frame by frame: a registered gesture that has won `run` frames in a row, reported once per hold."""

    def __init__(self, memory: PoseMemory, run: int = RUN_FRAMES) -> None:
        self.memory, self.run = memory, run
        self.reset()

    def reset(self) -> None:
        self._label: Optional[str] = None
        self._count = 0
        self.current: Optional[str] = None

    def step(self, t: float, lm: Any, world: Any, aspect: float) -> Optional[str]:
        if lm is None or world is None:
            self.reset()
            return None
        label = self.memory.classify(pose_features([{"t": t, "lm": lm, "world": world}], aspect))["label"]
        entry = self.memory.classes.get(label)
        if entry is None or entry.source != USER_SOURCE:
            self.reset()
            return None
        if label == self._label:
            self._count += 1
        else:
            self._label, self._count, self.current = label, 1, None
        if self._count == self.run:
            self.current = label
            return label
        return None
