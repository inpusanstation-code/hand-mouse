"""Which commands the watching model has earned the right to stop (learning while using, step 2, 2026-11-11).

The use log (src/use_log.py) keeps, for every rule command, what each watching model would have said: `shadow` (the trained TCN,
models/gesture_tcn.onnx) and `shadow_online` (the model learned from this person, data/online). From the commands the person marked
as "not meant" and the ones left unmarked, `decide` picks the commands where a model would have stopped enough of the marked ones
while stopping almost none of the others. Only those are enforced (QtRuntime._use_enforce); everything else stays as it is.

A command is "<action>:<label>" (the same label means different things in different modes: thumb_index is the scroll grab with
the rules and the click with the virtual hand). Verdicts count only when they came from the model file that is in use now, on
this PC, and while that command was not already being enforced (enforced commands that ran have all passed, which says nothing).
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

KINDS = ("tcn", "online")
FIELD = {"tcn": "shadow", "online": "shadow_online"}


@dataclass(frozen=True)
class Limits:
    min_marked: int = 20            # marked ("not meant") commands the model judged
    min_meant: int = 20             # unmarked ones it judged
    min_stop_marked: float = .5     # share of the marked ones it would have stopped
    max_stop_meant: float = .05     # share of the unmarked ones it would have stopped by mistake


def gate_key(action: str, label: str) -> str:
    return f"{action}:{label}"


def gate_on_kind(ev: Dict[str, Any]) -> str:
    """Which real checker was switched on for this event ("" = none). Step 1 files wrote True / False."""
    g = ev.get("gate_on")
    return g if isinstance(g, str) else ("tcn" if g else "")


def tally(events: Iterable[Dict[str, Any]], pc: Optional[str] = None,
          models: Optional[Dict[str, str]] = None) -> Dict[str, Dict[str, Dict[str, int]]]:
    """{kind: {command: {"marked", "stop_marked", "meant", "stop_meant"}}} over the commands a model judged: rule commands, and
    taught gestures' commands once a model has learned them ("<key>:<key>").
    `models` = {kind: version in use}: verdicts of another version are left out (a kind without a version: all left out)."""
    out: Dict[str, Dict[str, Dict[str, int]]] = {k: {} for k in KINDS}
    for ev in events:
        source, name = ev.get("source"), str(ev.get("key", ""))
        taught = source == "registered" or (source == "binding" and name.startswith("comp_"))   # use_import.learnable
        if not (source == "rule" or taught) or (pc is not None and ev.get("pc") != pc):
            continue
        for kind in KINDS:
            v = ev.get(FIELD[kind]) or {}
            if "would_pass" not in v or gate_on_kind(ev) == kind or ev.get("enforced") == kind:
                continue
            if models is not None and (not models.get(kind) or v.get("model") != models[kind]):
                continue
            row = out[kind].setdefault(gate_key(str(ev.get("key", "")), str(v.get("label", ""))),
                                       dict(marked=0, stop_marked=0, meant=0, stop_meant=0))
            stop = not v["would_pass"]
            if ev.get("marked"):
                row["marked"] += 1
                row["stop_marked"] += stop
            else:
                row["meant"] += 1
                row["stop_meant"] += stop
    return out


def earned(row: Dict[str, int], limits: Limits = Limits()) -> bool:
    return (row["marked"] >= limits.min_marked and row["meant"] >= limits.min_meant
            and row["stop_marked"] / row["marked"] >= limits.min_stop_marked
            and row["stop_meant"] / row["meant"] <= limits.max_stop_meant)


def decide(events: Iterable[Dict[str, Any]], pc: Optional[str] = None, models: Optional[Dict[str, str]] = None,
           limits: Limits = Limits()) -> Dict[str, Dict[str, Any]]:
    """{command: {"model": kind, "version": ..., counts}} for the commands a model may stop. When both models earned one,
    the one that would have stopped more of the marked commands gets it."""
    out: Dict[str, Dict[str, Any]] = {}
    for kind, rows in tally(events, pc, models).items():
        for key, row in rows.items():
            if not earned(row, limits):
                continue
            rate = row["stop_marked"] / row["marked"]
            if key not in out or rate > out[key]["stop_marked"] / out[key]["marked"]:
                out[key] = {"model": kind, "version": (models or {}).get(kind, ""), **row}
    return out


def save(path: Path, decision: Dict[str, Dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(decision, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load(path: Path) -> Dict[str, Dict[str, Any]]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}
