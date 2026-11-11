"""One small checking model per taught gesture: "is the hand making this gesture right now, or not?" (2026-11-11).

Teaching the production model a new class from a person's uses made it forget old gestures in every setting tried
(docs/use-log.md: 212 -> 153..200 of 246 repetitions). A verifier leaves that model alone: the production encoder is only read
(frozen), and a small head on its embedding is trained per gesture. Nothing the app already recognises can get worse.

- yes examples: the uses of that gesture from the use log (src/online/use_import.py, label = the gesture's key);
- no examples: every other labelled window in the store: the guided recordings of all gestures and of doing nothing, commands
  the person marked as not meant, and the other taught gestures.
The uses of the newest day are kept aside (2026-11-11, the person's decision: a test on the same day's uses was kinder than
another day turned out to be), and the no examples of the validation sessions. A verifier is saved only when it recognises at
least MIN_RECALL of the kept-aside uses (FRAMES windows in a row over its threshold, as the app asks) while at most MAX_FALSE of
the kept-aside no windows are over it. The threshold is the one of THRESHOLDS that does best under that limit. So a gesture
used on one day only has no verifier yet ("waiting", reason "one_day"); the one that is saved is then trained on all uses.

Files: data/online/verifiers/<hash of key>.json (weights as lists; no torch needed to read). A verifier belongs to the encoder it
was trained on (`encoder`, a hash of the encoder's weights): after the encoder changes it is not loaded until trained again.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np

VERIFIER_DIR = "verifiers"
MIN_USES = 20             # uses of a gesture before a verifier is trained for it
MIN_HELD = 4              # uses of the newest day(s) needed to test it
MIN_TRAIN = 10            # ... and uses of the days before to train it
STATUS_FILE = "status.json"
MIN_RECALL = .8           # share of the kept-aside uses it must recognise
MAX_FALSE = .02           # share of the kept-aside "no" windows that may be over the threshold
THRESHOLDS = (.5, .6, .7, .8, .9)
FRAMES = 3                # windows in a row over the threshold = recognised (the app's check asks the same)
HIDDEN = 32
NEG_CAP = 40000           # "no" windows used for training (a random share when there are more)


def encoder_fingerprint(state: Dict[str, Any]) -> str:
    """A hash of the encoder's weights (everything but the class head): the same encoder gives the same embeddings."""
    digest = hashlib.sha1()
    for name in sorted(state):
        if not name.startswith("head."):
            digest.update(name.encode())
            digest.update(np.ascontiguousarray(state[name].detach().cpu().numpy()).tobytes())
    return digest.hexdigest()[:16]


def path_for(root: Path | str, key: str) -> Path:
    return Path(root) / VERIFIER_DIR / (hashlib.md5(key.encode("utf-8")).hexdigest()[:12] + ".json")


@dataclass
class Verifier:
    key: str
    mean: np.ndarray
    scale: np.ndarray
    w1: np.ndarray
    b1: np.ndarray
    w2: np.ndarray
    b2: float
    threshold: float
    encoder: str
    uses: int = 0
    metrics: Dict[str, Any] = field(default_factory=dict)
    created: float = 0.0

    def prob(self, embedding: np.ndarray) -> np.ndarray:
        """(n, E) embeddings -> (n,) probability that the hand is making this gesture."""
        x = (np.asarray(embedding, dtype=np.float64) - self.mean) / self.scale
        hidden = np.maximum(x @ self.w1 + self.b1, 0.0)
        return 1.0 / (1.0 + np.exp(-(hidden @ self.w2 + self.b2)))

    def to_dict(self) -> Dict[str, Any]:
        return {"key": self.key, "mean": self.mean.tolist(), "scale": self.scale.tolist(), "w1": self.w1.tolist(),
                "b1": self.b1.tolist(), "w2": self.w2.tolist(), "b2": float(self.b2), "threshold": self.threshold,
                "encoder": self.encoder, "uses": self.uses, "metrics": self.metrics, "created": self.created}

    @classmethod
    def from_dict(cls, doc: Dict[str, Any]) -> "Verifier":
        arr = lambda name: np.asarray(doc[name], dtype=np.float64)   # noqa: E731
        return cls(key=str(doc["key"]), mean=arr("mean"), scale=arr("scale"), w1=arr("w1"), b1=arr("b1"), w2=arr("w2"),
                   b2=float(doc["b2"]), threshold=float(doc["threshold"]), encoder=str(doc.get("encoder", "")),
                   uses=int(doc.get("uses", 0)), metrics=dict(doc.get("metrics") or {}), created=float(doc.get("created", 0.0)))


def save_verifier(root: Path | str, verifier: Verifier) -> Path:
    path = path_for(root, verifier.key)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(verifier.to_dict(), fh, ensure_ascii=False)
    os.replace(tmp, path)
    return path


def load_verifiers(root: Path | str, encoder: Optional[str] = None) -> Dict[str, Verifier]:
    """{key: verifier}. With `encoder`, only those trained on that encoder. A broken file is skipped."""
    out: Dict[str, Verifier] = {}
    for path in sorted((Path(root) / VERIFIER_DIR).glob("*.json")):
        try:
            verifier = Verifier.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if encoder is None or verifier.encoder == encoder:
            out[verifier.key] = verifier
    return out


def delete_verifier(root: Path | str, key: str) -> bool:
    try:
        path_for(root, key).unlink()
        return True
    except OSError:
        return False


def _runs(over: np.ndarray, frames: int = FRAMES) -> bool:
    """True when `frames` values in a row are True."""
    run = 0
    for value in over:
        run = run + 1 if value else 0
        if run >= frames:
            return True
    return False


def _fit(x: np.ndarray, y: np.ndarray, seed: int, steps: int = 400):
    import torch
    torch.manual_seed(seed)
    mean, scale = x.mean(axis=0), x.std(axis=0) + 1e-6
    xt = torch.from_numpy(((x - mean) / scale).astype(np.float32))
    yt = torch.from_numpy(y.astype(np.float32))
    net = torch.nn.Sequential(torch.nn.Linear(x.shape[1], HIDDEN), torch.nn.ReLU(), torch.nn.Linear(HIDDEN, 1))
    positives = max(1.0, float(y.sum()))
    weight = torch.tensor(min(50.0, (len(y) - positives) / positives))      # few yes examples against many no examples
    loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=weight)
    optimizer = torch.optim.Adam(net.parameters(), lr=1e-2, weight_decay=1e-4)
    for _ in range(steps):
        optimizer.zero_grad()
        loss_fn(net(xt).squeeze(1), yt).backward()
        optimizer.step()
    first, last = net[0], net[2]
    return (mean, scale, first.weight.detach().numpy().T.astype(np.float64), first.bias.detach().numpy().astype(np.float64),
            last.weight.detach().numpy()[0].astype(np.float64), float(last.bias.detach().numpy()[0]))


def train_verifiers(root: Path | str, *, emit: Callable[..., None] = lambda *a, **k: None, seed: int = 0,
                    min_uses: int = MIN_USES, min_recall: float = MIN_RECALL, max_false: float = MAX_FALSE) -> Dict[str, Dict[str, Any]]:
    """Trains (again) the verifier of every taught gesture whose uses changed since its verifier was made. Returns one report per
    gesture looked at: {"status": "saved" | "rejected" | "waiting" | "kept", "uses", "recall", "held", "false_rate", "threshold"}
    ("waiting": used on one day only, or too few uses on the newest day: nothing to test it on yet).
    A rejected one changes nothing: the verifier from before, if any, stays."""
    import torch

    from src.online.dataset import build_dataset, target_positions, window_positions
    from src.online.models import make_model
    from src.online.samples import GUIDED_SCHEDULED, PSEUDO_CANDIDATE, SUPERVISED_SOURCES, UNKNOWN, VALIDATED_PSEUDO, SampleStore
    from src.online.versions import ModelManager

    root = Path(root)
    store, manager = SampleStore(root), ModelManager(root)
    if not manager.has("production"):
        return {}
    production = manager.load()
    info = production["info"]
    classes: List[str] = list(info["classes"])
    window = int(info["window"])
    validation = set(info.get("validation_sessions") or [])
    fingerprint = encoder_fingerprint(production["state"])

    from dataclasses import replace
    from src.online.use_import import BEFORE_RULE, click_base, click_key, split_taught_labels
    split_taught_labels(store)                     # one checking model per gesture AND direction (2026-11-11)
    uses: Dict[str, list] = {}
    click_label: Dict[str, str] = {}               # a click's checking model -> the model label of the gesture that clicks
    for s in store.samples(sources=[PSEUDO_CANDIDATE]):
        extra = s.extra or {}
        if extra.get("taught") and s.label not in classes:
            uses.setdefault(s.label, []).append(s)
            continue
        key = (click_key(str(extra.get("source", "")), str(extra.get("key", "")), s.label, str(extra.get("kind") or ""))
               if not extra.get("marked") else "")
        if key:                                    # a left / right click of the person's (2026-11-11): its own checking model,
            uses.setdefault(key, []).append(replace(s, label=key))      # labelled with that model's key for this round only
            click_label[key] = s.label
    # Several models, set up by the data (2026-11-11: "필요하다면 멀티 TCN을 구성해서 … 앱이 알아서"): a kind of click (the
    # second tap of a double click) gets a checking model of its own once it has min_uses uses; until then its uses are
    # learned together with the plain click's, and the app asks that model about them (QtRuntime._click_model).
    for key in [k for k in uses if click_base(k) != k and len(uses[k]) < min_uses]:
        base = click_base(key)
        uses.setdefault(base, []).extend(replace(s, label=base) for s in uses.pop(key))
        click_label.setdefault(base, click_label.pop(key))
    # the clicks the person marked as not meant are what a click's checking model is for: more of them = train it again
    marked: Dict[str, int] = {}
    for s in store.samples(sources=[VALIDATED_PSEUDO]):
        extra = s.extra or {}
        key = click_key(str(extra.get("source", "")), str(extra.get("key", "")), s.suggested_label, str(extra.get("kind") or ""))
        if key and key not in uses:
            key = click_base(key)                  # its kind has no model of its own: counted with the plain click's
        if key:
            marked[key] = marked.get(key, 0) + 1
    count = lambda k: len(uses[k]) + marked.get(k, 0)      # noqa: E731
    existing = load_verifiers(root)
    todo = [k for k, items in uses.items() if len(items) >= min_uses
            and not (k in existing and existing[k].encoder == fingerprint and existing[k].uses == count(k))]
    out: Dict[str, Dict[str, Any]] = {k: {"status": "kept", "uses": len(uses[k]), "marked": marked.get(k, 0)} for k in uses
                                      if len(uses[k]) >= min_uses and k not in todo}
    if not todo:
        return out
    keys = sorted(uses)
    wide = classes + keys
    others = [s for s in store.samples(sources=[GUIDED_SCHEDULED, VALIDATED_PSEUDO, *SUPERVISED_SOURCES])
              if s.label in classes and s.label != UNKNOWN]
    data = build_dataset(store, others + [s for k in keys for s in uses[k]], wide)
    rows = target_positions(data)
    model = make_model(info["kind"], len(classes), window, info["embedding"])
    model.load_state_dict(production["state"])
    model.eval()
    parts = []
    with torch.no_grad():
        for i in range(0, len(rows), 2048):
            x = data.frames[window_positions(data.starts, rows[i:i + 2048], window)]
            parts.append(model.embed(torch.from_numpy(np.ascontiguousarray(x, dtype=np.float32))).numpy())
    emb = np.concatenate(parts) if parts else np.zeros((0, int(info["embedding"])))
    labels = data.labels[rows]
    owner = data.sample_of[rows]
    in_validation = np.array([s.session in validation for s in data.samples])[owner]
    # how long after its sample's labelled stretch began each window ends: a click is judged the moment it happens, so only
    # the windows up to then count for its checking model (the stretch goes on a little after the click)
    since = data.times[rows] - data.times[data.do_start[owner]] if len(rows) else np.zeros(0)
    rng = np.random.default_rng(seed)

    status: Dict[str, Dict[str, Any]] = {k: v for k, v in read_status(root).items() if k in uses}
    for n, key in enumerate(todo):
        emit("verifier", key=key, done=n, total=len(todo))
        c = wide.index(key)
        mine = sorted({int(i) for i in owner[labels == c]}, key=lambda i: data.samples[i].created)
        # The test is the newest day's uses, the training everything before: a verifier that only knows today's hand, light and
        # seat looked much better on today's uses than on another day's (docs/use-log.md, window comparison).
        days = sorted({use_day(data.samples[i]) for i in mine})
        held_samples: set = set()
        for day in reversed(days[1:]):                            # newest first, whole days, until there is enough to test on
            held_samples |= {i for i in mine if use_day(data.samples[i]) == day}
            if len(held_samples) >= MIN_HELD:
                break
        if len(held_samples) < MIN_HELD or len(mine) - len(held_samples) < MIN_TRAIN:
            reason = "one_day" if len(days) < 2 else "few_recent"
            out[key] = status[key] = {"status": "waiting", "reason": reason, "uses": len(mine), "days": len(days),
                                      "newest_day": days[-1] if days else ""}
            continue
        is_pos = labels == c
        left_out = np.zeros(len(labels), dtype=bool)                # neither yes nor no
        if key in click_label:
            after = is_pos & (since > BEFORE_RULE + 1 / 60)
            is_pos = is_pos & ~after
            # the same gesture elsewhere (the guided recordings of that pinch, a drag begun with it) is not a "no"
            same = labels == wide.index(click_label[key]) if click_label[key] in wide else np.zeros(len(labels), dtype=bool)
            left_out = after | same
        held_pos = is_pos & np.isin(owner, list(held_samples))
        train_pos = is_pos & ~held_pos
        neg = ~is_pos & ~left_out
        test_neg = neg & in_validation
        if not test_neg.any():                                    # no validation sessions: a random fifth of the no windows
            test_neg = neg & (rng.random(len(neg)) < .2)
        train_neg = np.flatnonzero(neg & ~test_neg)
        if len(train_neg) > NEG_CAP:
            train_neg = rng.choice(train_neg, NEG_CAP, replace=False)
        report: Dict[str, Any] = {"uses": len(mine), "held": len(held_samples), "days": len(days), "marked": marked.get(key, 0)}
        if not train_pos.any() or not len(train_neg):
            out[key] = status[key] = {**report, "status": "rejected", "reason": "too_little_data"}
            continue
        x = np.concatenate([emb[train_pos], emb[train_neg]])
        y = np.concatenate([np.ones(int(train_pos.sum())), np.zeros(len(train_neg))])
        mean, scale, w1, b1, w2, b2 = _fit(x, y, seed)
        verifier = Verifier(key=key, mean=mean, scale=scale, w1=w1, b1=b1, w2=w2, b2=b2, threshold=.5, encoder=fingerprint,
                            uses=len(mine), created=time.time())
        p = verifier.prob(emb)
        best = None
        for threshold in THRESHOLDS:
            false_rate = float((p[test_neg] >= threshold).mean()) if test_neg.any() else 0.0
            hit = sum(_runs(p[is_pos & (owner == i)] >= threshold) for i in held_samples)
            recall = hit / len(held_samples)
            row = {"threshold": threshold, "recall": round(recall, 3), "hit": hit, "false_rate": round(false_rate, 4)}
            if false_rate <= max_false and (best is None or (recall, threshold) > (best["recall"], best["threshold"])):
                best = row
            report.setdefault("curve", []).append(row)
        if best is None or best["recall"] < min_recall:
            loosest = report["curve"][0]
            out[key] = {**report, "status": "rejected", "recall": (best or loosest)["recall"],
                        "false_rate": (best or loosest)["false_rate"],
                        "reason": "misses_uses" if best is not None else "fires_on_other_things"}
            status[key] = {k: v for k, v in out[key].items() if k != "curve"}
            continue
        # It passed on the newest day without having seen it. The one that is used is trained on every use, that day included
        # (with the threshold that passed): the newest uses are the ones most like tomorrow's.
        all_neg = np.flatnonzero(neg)
        if len(all_neg) > NEG_CAP:
            all_neg = rng.choice(all_neg, NEG_CAP, replace=False)
        mean, scale, w1, b1, w2, b2 = _fit(np.concatenate([emb[is_pos], emb[all_neg]]),
                                           np.concatenate([np.ones(int(is_pos.sum())), np.zeros(len(all_neg))]), seed)
        verifier = Verifier(key=key, mean=mean, scale=scale, w1=w1, b1=b1, w2=w2, b2=b2, threshold=float(best["threshold"]),
                            encoder=fingerprint, uses=count(key), created=time.time())
        verifier.metrics = {"recall": best["recall"], "hit": best["hit"], "held": len(held_samples), "false_rate": best["false_rate"],
                            "no_windows": int(test_neg.sum()), "yes_windows": int(is_pos.sum()), "days": len(days),
                            "test": "newest_day", "marked": marked.get(key, 0)}
        save_verifier(root, verifier)
        out[key] = {**report, "status": "saved", "recall": best["recall"], "false_rate": best["false_rate"],
                    "threshold": verifier.threshold}
        status[key] = {k: v for k, v in out[key].items() if k != "curve"}
    write_status(root, status)
    return out


def use_day(sample: Any) -> str:
    """The day a use was logged: from the log file's name in its session ("use-YYYYMMDD-HHMMSS-pc"), else from when it was stored."""
    session = str(getattr(sample, "session", ""))
    if session.startswith("use-") and session[4:12].isdigit():
        return session[4:12]
    return time.strftime("%Y%m%d", time.localtime(float(getattr(sample, "created", 0.0))))


def read_status(root: Path | str) -> Dict[str, Dict[str, Any]]:
    """What the last round found for each taught gesture (verifiers/status.json): the app's notices read it."""
    try:
        doc = json.loads((Path(root) / VERIFIER_DIR / STATUS_FILE).read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def write_status(root: Path | str, status: Dict[str, Dict[str, Any]]) -> None:
    folder = Path(root) / VERIFIER_DIR
    folder.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(status, fh, ensure_ascii=False)
    os.replace(tmp, folder / STATUS_FILE)
