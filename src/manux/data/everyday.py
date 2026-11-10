"""Everyday-use candidates: short pieces of normal use the person can label later (from virtual-hand-20261110 online/collector).

Each candidate is an ordinary MANUX recording (docs/contracts.md section 9, `mode: free`) in `<recordings>/everyday/`,
joints only. Until the person says what it was, every frame is `target: idle` and the meta `split` is `candidate`, so
the training center ignores it (`recording_sets` reads only `train` / `eval`, and `idle` is never a class). Labeling
rewrites the file as a `train` recording with the person's label; from then on the existing retraining, held-out
evaluation and install flow uses it like any other recording (no separate online learner, user decision 2026-11-10).
"""
from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from manux.data.recording import read

FOLDER = "everyday"
CANDIDATE_SPLIT = "candidate"
UNLABELED = {"target": "idle", "phase": "candidate"}
NONE_CHOICE = "none"


def folder_of(recordings_dir: Path) -> Path:
    return Path(recordings_dir) / FOLDER


def candidates(folder: Path, limit: int = 30) -> List[Dict[str, Any]]:
    """Newest first: the candidates still waiting for a label."""
    rows: List[Dict[str, Any]] = []
    for path in sorted(Path(folder).glob("*.jsonl.gz"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            rec = read(path)
        except (OSError, ValueError):
            continue
        if not rec.complete or rec.meta.get("split") != CANDIDATE_SPLIT:
            continue
        info = next((e for e in rec.events if e.get("kind") == "candidate"), {})
        rows.append({"path": str(path), "name": path.name, "created": rec.meta.get("created", ""),
                     "seconds": round(float(info.get("end", 0.0)) - float(info.get("start", 0.0)), 2),
                     "action": str(info.get("top_action", "")), "reason": str(info.get("reason", "")),
                     "frames": len(rec.frames)})
        if len(rows) >= limit:
            break
    return rows


def _inside(folder: Path, path: Path) -> Path:
    path = Path(path)
    if path.parent.resolve() != Path(folder).resolve() or not path.name.endswith(".jsonl.gz"):
        raise ValueError("후보 폴더 밖의 파일입니다")
    return path


def label(folder: Path, path: Path, target: str, task: str = "", gesture: str = "") -> Path:
    """Rewrite one candidate as a `train` recording. `target` is a catalog class, or "none" for "nothing was meant".
    Frames from the first active one on get the label; the frames before it are `transition`. Atomic."""
    path = _inside(folder, path)
    rec = read(path)
    if rec.meta.get("split") != CANDIDATE_SPLIT:
        raise ValueError("이미 정리한 구간입니다")
    info = next((e for e in rec.events if e.get("kind") == "candidate"), {})
    start = float(info.get("start", 0.0))
    meta = {**rec.meta, "split": "train", "label_source": "user_corrected", "source_kind": "everyday"}
    lines: List[Mapping[str, Any]] = [{**meta, "type": "meta"}]
    counts: Dict[str, int] = {}
    for frame in rec.frames:
        if target == NONE_CHOICE:
            lab = {"target": "none", "phase": "use"}
        elif float(frame.get("t", 0.0)) < start:
            lab = {"target": "transition", "phase": "prep", "task": task}
        else:
            lab = {"target": target, "phase": "do", "task": task, **({"gesture": gesture} if gesture else {})}
        counts[lab["target"] if frame.get("lm") else "no_hand"] = counts.get(lab["target"] if frame.get("lm") else "no_hand", 0) + 1
        lines.append({**frame, "type": "frame", "label": lab})
    lines += [{**e, "type": "event"} for e in rec.events]
    lines.append({"type": "end", "frames": len(rec.frames), "counts": counts, "marks": 0})
    part = path.with_name(path.name + ".relabel.part")
    with gzip.open(part, "wt", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(part, path)
    return path


def discard(folder: Path, path: Path) -> None:
    _inside(folder, path).unlink(missing_ok=True)
