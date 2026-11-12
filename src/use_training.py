"""The collected uses as training data for the gesture TCN that is exported to models/gesture_tcn.onnx (2026-11-12:
"앱이 켜졌을 때 틈틈이 onnx를 앱이 알아서 자동으로 모은 수집 데이터를 가지고 학습").

Until now the use log (src/use_log.py) only taught the models under data/online; the exported model was trained from the
guided recordings alone, by hand. Here the uses become one more "recording" for scripts/train_tcn.py:

- a click the person PASSED in the review (src/use_review.py) whose gesture the model has a class for (thumb_index …):
  the moment of the click is an example of that gesture;
- a command marked as not meant (F / F8, or pausing right after) or judged a false detection in the review: the stretch
  that set it off is "none" - whatever the command was, the hand was not making a gesture;
- everything else teaches nothing here (unreviewed clicks, taught gestures: the exported model has no class for them).

Every `HOLD_OUT`-th usable event is kept out of training, so the old and the new model can be compared on uses neither
was trained on (`compare`). Nothing here writes to the log or to the models.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

NONE = "none"
CONTEXT_SECONDS = 1.0        # history kept before the labelled stretch (the model looks back half a second)
BEFORE_CLICK = .15           # labelled stretch before a passed click: the moment of the pinch
BEFORE_REJECTED = .5         # ... before a command that was not meant: what set it off
AFTER = .15
MIN_FRAMES = 3
HOLD_OUT = 5                 # every 5th usable event is only tested on
STATE_FILE = "onnx_auto.json"


def _usable(frame: Dict[str, Any]) -> bool:
    return bool(frame.get("lm")) and bool(frame.get("world")) and len(frame["lm"]) == 21 and len(frame["world"]) == 21


def event_target(ev: Dict[str, Any], verdict: str, classes: Sequence[str]) -> Optional[str]:
    """What one logged command teaches the exported model: a class name, "none", or None (nothing)."""
    from src.online.use_import import click_key, unmarkable_right_click
    from src.use_review import BAD, OK
    if ev.get("marked") or verdict == BAD:
        return NONE if NONE in classes else None
    source, key, label = str(ev.get("source", "")), str(ev.get("key", "")), str(ev.get("label") or "")
    try:
        if unmarkable_right_click(ev):
            return None
    except Exception:
        pass
    if verdict == OK and click_key(source, key, label) and label in classes and label != NONE:
        return label
    return None


def _clip(ev: Dict[str, Any], target: str) -> Optional[List[Dict[str, Any]]]:
    """The event's frames from the context to just after the command, each with its training target (None = context).
    Only an unbroken run of frames with the hand, ending at the command: the features need every frame."""
    t = float(ev["t"])
    before = BEFORE_REJECTED if target == NONE else BEFORE_CLICK
    first = t - before
    frames = [f for f in ev.get("frames") or [] if t - before - CONTEXT_SECONDS <= float(f.get("t", 0.0)) <= t + AFTER]
    run: List[Dict[str, Any]] = []
    for f in frames:                                   # the last unbroken run
        if _usable(f) and (not run or 0 < float(f["t"]) - float(run[-1]["t"]) <= .25):
            run.append(f)
        elif _usable(f):
            run = [f]
        else:
            run = []
    labelled = [f for f in run if float(f["t"]) >= first]
    if len(labelled) < MIN_FRAMES:
        return None
    return [{"t": float(f["t"]), "lm": f["lm"], "world": f["world"],
             "label": {"target": target if float(f["t"]) >= first else None, "phase": "do", "task": target}} for f in run]


def collect(folder: Path | str, classes: Sequence[str]) -> List[Dict[str, Any]]:
    """Every usable event of the log, oldest first: {"file", "id", "target", "frames", "held"}."""
    from src import use_review
    from src.use_log import read_events
    reviews = use_review.load(folder)
    out: List[Dict[str, Any]] = []
    for ev in read_events(Path(folder), frames=True):
        target = event_target(ev, use_review.verdict(reviews, ev.get("file", ""), ev.get("id")), classes)
        if target is None:
            continue
        clip = _clip(ev, target)
        if clip is None:
            continue
        out.append({"file": ev.get("file", ""), "id": ev.get("id"), "target": target, "frames": clip})
    for n, item in enumerate(out):
        item["held"] = n % HOLD_OUT == HOLD_OUT - 1
    return out


def counts(folder: Path | str, classes: Sequence[str]) -> Dict[str, int]:
    """Usable events per target, from the small index files only (no joints): what a round would learn from."""
    from src import use_review
    from src.use_log import read_events
    reviews = use_review.load(folder)
    out: Dict[str, int] = {}
    for ev in read_events(Path(folder), frames=False):
        target = event_target(ev, use_review.verdict(reviews, ev.get("file", ""), ev.get("id")), classes)
        if target is not None:
            out[target] = out.get(target, 0) + 1
    return out


def as_record(items: Sequence[Dict[str, Any]], aspect: float = 720 / 1280) -> Optional[Tuple[str, Dict[str, Any], list]]:
    """The events (not the held-out ones) as one extra record for capture_dataset.load_sessions: each event is a
    segment of its own, its context frames carry no target. None when there is nothing to learn from."""
    from src.spatial_features import SPATIAL_FEATURES, extract_spatial_features
    from src.tcn_features import FEATURES, frame_features
    train = [i for i in items if not i.get("held")]
    if not train:
        return None
    frames: List[Dict[str, Any]] = []
    seg_ranges: List[Tuple[int, int]] = []
    t_shift = 0.0
    for item in train:
        start = len(frames)
        t0 = float(item["frames"][0]["t"])
        for f in item["frames"]:
            frames.append({**f, "t": round(float(f["t"]) - t0 + t_shift, 4)})
        seg_ranges.append((start, len(frames)))
        t_shift = frames[-1]["t"] + 1.0                 # a gap between events: never one stretch
    n = len(frames)
    features = np.zeros((n, FEATURES), np.float32)
    spatial = np.zeros((n, SPATIAL_FEATURES), np.float32)
    segments = np.full(n, -1, np.int64)
    for a, b in seg_ranges:
        features[a:b] = frame_features(frames[a:b], aspect)
        segments[a:b] = a
    targets: List[Optional[str]] = []
    for i, f in enumerate(frames):
        target = (f.get("label") or {}).get("target")
        if features[i, -1] == 0:
            target = None                               # the features found no hand there
        elif target is not None:
            vec = extract_spatial_features(f["lm"])
            if vec is not None:
                spatial[i] = vec
        targets.append(target)
    meta = {"type": "meta", "mode": "use", "complete": True, "frame_aspect": aspect, "occlusion_calibrated": True,
            "pc": "use-log", "events": len(train)}
    meta["_cached_extract"] = {
        "path": "use-log", "meta": {k: v for k, v in meta.items()}, "frames": frames, "features": features,
        "spatial_features": spatial, "segments": segments, "seg_ranges": seg_ranges, "cond_keys": ["unassigned"] * n,
        "raw_targets": list(targets), "valid_targets": list(targets),
        "quality_scores": np.ones(n, np.float32), "sample_weights": np.ones(n, np.float32), "label_refinement_stats": {},
    }
    return "use-log", meta, frames


def fired(prob: np.ndarray, index: int, thr: float, k: int) -> bool:
    """`k` frames in a row at or above `thr` for class `index`."""
    run = 0
    for p in prob[:, index]:
        run = run + 1 if p >= thr else 0
        if run >= k:
            return True
    return False


def score(predict: Callable[[np.ndarray], np.ndarray], info: Dict[str, Any], items: Sequence[Dict[str, Any]],
          aspect: float = 720 / 1280) -> Dict[str, Any]:
    """One model on the held-out events: clicks it recognises (its gesture fires in the labelled stretch) and rejected
    commands it would have let through (any gesture fires there)."""
    from src.tcn_features import frame_features, windows
    classes = list(info.get("classes") or [])
    thr = float(info.get("threshold", .7))
    k = int(info.get("frames_in_a_row", 3))
    out = {"clicks": 0, "clicks_seen": 0, "rejected": 0, "rejected_fired": 0}
    for item in items:
        if not item.get("held"):
            continue
        feats = frame_features(item["frames"], aspect)
        x = windows(feats, int(info.get("window", 15)))
        labelled = np.array([(f.get("label") or {}).get("target") is not None for f in item["frames"]])
        # (the app's predictors take a batch of one window and give that window's probabilities)
        rows = [np.asarray(predict(w[None])) for w in x[labelled]]
        prob = np.stack([r[0] if r.ndim == 2 else r for r in rows])
        if item["target"] == NONE:
            out["rejected"] += 1
            if any(fired(prob, c, thr, k) for c, name in enumerate(classes) if name != NONE):
                out["rejected_fired"] += 1
        elif item["target"] in classes:
            out["clicks"] += 1
            if fired(prob, classes.index(item["target"]), thr, min(k, int(labelled.sum()))):
                out["clicks_seen"] += 1
    return out


def read_state(root: Path | str) -> Dict[str, Any]:
    try:
        doc = json.loads((Path(root) / STATE_FILE).read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(root: Path | str, state: Dict[str, Any]) -> None:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / (STATE_FILE + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    tmp.replace(root / STATE_FILE)
