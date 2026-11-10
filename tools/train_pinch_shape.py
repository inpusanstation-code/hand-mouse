"""Train the person's pinch-shape model for the virtual hand (perception.pinch_shape) from their recordings.

    uv run --locked --python 3.12 python tools/train_pinch_shape.py            # the app's data folder
    uv run --locked --python 3.12 python tools/train_pinch_shape.py --dry-run  # report only, write nothing

Frames used: those whose thumb and index tips look closed (tip distance <= 0.3 hand sizes, the contact rule's range).
1 = inside a `thumb_index` repetition (phase `do`), 0 = every other label, except frames up to 3 s after a
`thumb_index` repetition (often the same pinch still closed). Recordings marked `split: eval` and derived copies are
left out (evaluation data never trains). The report scores recordings held out of training (6 groups by recording),
then the model is trained on all of them and written to `<data>/models/virtual_hand/pinch_shape.json`.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import List, Sequence, Tuple

import numpy as np

from manux.data.recording import read, replay
from manux.perception.pinch_shape import FILE, train
from manux.perception.pose_angles import pose_angles

CONTACT = .3
AFTER = 3.0


def recordings(data_dir: Path) -> List[Path]:
    folder = data_dir / "recordings"
    out = []
    for path in sorted(folder.rglob("*.jsonl.gz")):
        if "derived" in path.parts:
            continue
        out.append(path)
    return out


def collect(paths: Sequence[Path]) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    xs, ys, groups = [], [], []
    for gi, path in enumerate(paths):
        try:
            rec = read(path)
        except (OSError, ValueError):
            continue
        if not rec.complete or str(rec.meta.get("split", "train")) == "eval" or rec.meta.get("lineage"):
            continue
        last_pinch = -1e9
        for item in replay(rec):
            lab = item.record.get("label") or {}
            target, phase, t = str(lab.get("target", "none")), lab.get("phase"), item.frame.t
            if target == "thumb_index" and phase == "do":
                last_pinch = t
            hand = item.hand
            if hand is None or hand.world is None:
                continue
            pt = [(p[0] * item.frame.width, p[1] * item.frame.height) for p in hand.landmarks]
            size = math.dist(pt[0], pt[9])
            if size <= 1 or math.dist(pt[4], pt[8]) / size > CONTACT:
                continue
            positive = target == "thumb_index" and phase == "do"
            if not positive and (target == "thumb_index" or t - last_pinch <= AFTER):
                continue                                   # ambiguous: the same pinch, before / after its window
            row = pose_angles(hand.world)
            if row is None:
                continue
            xs.append(row); ys.append(1.0 if positive else 0.0); groups.append(gi)
    return np.array(xs, float).reshape(-1, 33), np.array(ys), np.array(groups)


def held_out(x, y, g, folds: int = 6, threshold: float = .5):
    prob = np.zeros(len(y))
    files = np.unique(g)
    for part in np.array_split(np.random.default_rng(1).permutation(files), min(folds, len(files))):
        m = np.isin(g, part)
        if y[~m].min() == y[~m].max():
            continue
        prob[m] = train(x[~m], y[~m]).score_features(x[m])
    pos, neg = y > .5, y < .5
    return {"pinch_frames_kept": round(float((prob[pos] >= threshold).mean()), 3),
            "other_contact_frames_kept": round(float((prob[neg] >= threshold).mean()), 3)}


def main(argv=None) -> int:
    from manux.settings.paths import resolve
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", type=Path, default=None)
    ap.add_argument("--threshold", type=float, default=.5)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    data_dir = args.data_dir or resolve().data_dir
    paths = recordings(data_dir)
    x, y, g = collect(paths)
    if len(y) == 0 or y.min() == y.max():
        print("thumb_index 녹화와 다른 녹화가 모두 있어야 학습할 수 있습니다.", file=sys.stderr)
        return 1
    report = {"recordings": int(len(np.unique(g))), "pinch_frames": int(y.sum()), "other_frames": int((y < .5).sum()),
              "held_out": held_out(x, y, g, threshold=args.threshold)}
    if not args.dry_run:
        model = train(x, y, threshold=args.threshold, info=report)
        model.save(data_dir / FILE)
        report["saved"] = str(data_dir / FILE)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
