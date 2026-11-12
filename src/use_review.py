"""The person's look at the collected uses before they are learned from (2026-11-11 request: "오탐지도 다 포집해놨던데 …
자동 학습 시키기 전에 유저가 오탐지인지 아닌지 판단하는 세션 … 유저가 통과시킨 데이터들만 TCN 학습").

Every use of a taught gesture and every click is logged when the command runs (src/use_log.py) - also the ones that ran by
accident and were not marked with F. Here each waiting use gets a verdict:

    "ok"   it was meant: it may be learned as an example of that gesture
    "bad"  a false detection: never an example of the gesture. It is kept as what the gesture is NOT - learned as "none",
           like a use marked with F (src/online/use_import.py) - so the checking model sees the very hands that fooled the
           quick one. Nothing is deleted from the log.

The verdicts live beside the log, logs/use_events/reviews.json: {log file name: {event id: "ok" | "bad"}}. The log files
themselves are never rewritten. With config "use_review_required" (on by default) a use without a verdict waits in the log:
only passed uses reach the learning round, and the round starts when enough of them have passed.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

FILE = "reviews.json"
OK, BAD = "ok", "bad"
MARK = "review"              # the "marked" reason of a use the person rejected here
MAX_REVIEW = 200             # waiting uses of one gesture shown in a session (the newest)


def load(folder: Path | str) -> Dict[str, Dict[str, str]]:
    try:
        doc = json.loads((Path(folder) / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(doc, dict):
        return {}
    return {str(f): {str(i): v for i, v in ids.items() if v in (OK, BAD)} for f, ids in doc.items() if isinstance(ids, dict)}


def verdict(reviews: Dict[str, Dict[str, str]], file: str, event_id: Any) -> str:
    return (reviews.get(str(file)) or {}).get(str(event_id), "")


def set_verdicts(folder: Path | str, items: Iterable[Tuple[str, Any, str]]) -> Dict[str, Dict[str, str]]:
    """(log file name, event id, "ok" | "bad" | "" = take the verdict back). Written at once; verdicts of log files that
    are gone (the log's size limit) are dropped."""
    folder = Path(folder)
    reviews = load(folder)
    for file, event_id, value in items:
        ids = reviews.setdefault(str(file), {})
        if value in (OK, BAD):
            ids[str(event_id)] = value
        else:
            ids.pop(str(event_id), None)
    reviews = {f: ids for f, ids in reviews.items() if ids and (folder / f).is_file()}
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / (FILE + ".tmp")
    tmp.write_text(json.dumps(reviews), encoding="utf-8")
    tmp.replace(folder / FILE)
    return reviews


def waiting(folder: Path | str, root: Path | str, key: str, limit: int = MAX_REVIEW) -> List[Dict[str, Any]]:
    """The uses of one card (`key`: a taught gesture and hand direction "comp_x@up", or a click "left_click:thumb_index")
    that no learning round has taken yet and that were not marked with F: oldest first, with their frames, "file" and
    "review" ("", "ok", "bad"). The newest `limit`."""
    from src.hand_direction import base, of_key, split
    from src.online.use_import import (STATE_FILE, _file_click_kinds, _state, click_key, click_parts, event_direction,
                                       learnable)
    folder = Path(folder)
    state = _state(Path(root) / STATE_FILE)
    reviews = load(folder)
    action, _label, _kind = click_parts(key)
    plain = action or base(key)
    needle = json.dumps(plain, ensure_ascii=False)
    out: List[Dict[str, Any]] = []
    for path in sorted(folder.glob("*.jsonl")):
        done = set((state.get(path.name) or {}).get("ids") or [])
        kinds = _file_click_kinds(path) if action else {}
        events: Dict[int, Dict[str, Any]] = {}
        marked: set = set()
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                is_mark = '"type": "mark"' in line
                if not is_mark and needle not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("type") == "mark":
                    marked.add(rec.get("id"))
                elif rec.get("type") == "event" and rec.get("key") == plain and rec.get("id") not in done:
                    events[rec["id"]] = rec
        for eid in sorted(events):
            ev = events[eid]
            if eid in marked:
                continue
            source = str(ev.get("source", ""))
            if action:
                mine = click_key(source, plain, str(ev.get("label") or ""), kinds.get(eid, ""))
            else:
                mine = split(plain, event_direction(ev)) if learnable(source, plain) else ""
            if mine != key and not (not action and not of_key(key) and mine and base(mine) == key):
                continue
            ev["file"] = path.name
            ev["marked"] = ""
            ev["review"] = verdict(reviews, path.name, eid)
            out.append(ev)
    return out[-limit:]
