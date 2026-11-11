"""The use log (src/use_log.py) as training samples: what the hand did around each command, labelled by what the person did next
(learning while using, 2026-11-11).

The process this serves: a person teaches a hand shape in [말·글로 연결 (AI)] (a quick model tells it from then on), uses it again
and again, and every use is logged with the hand's movement before and after. Once a taught gesture has been used often enough,
those uses teach the TCN that gesture as a new class.

- A taught gesture's command (a composite gesture "comp_*", or a registered gesture) left unmarked: an example of that gesture,
  labelled with its key. It becomes a class of the model once `new_min` examples exist; until then its uses wait in the log.
- A command the person marked as "not meant" (F, or pausing right after): the stretch that set it off is "none". A person said so,
  but did not pick a label: VALIDATED_PSEUDO, not a correction.
- A rule command left unmarked whose gesture the model already knows: a weak example (thinned out in a round, WEAK_STRIDE).
- Sequences, drawn shapes and motions take longer than the model's half-second window: left in the log.
Nobody checked the unmarked ones (PSEUDO_CANDIDATE); a wrong command that was not marked is in there too.
The quiet time between commands is NOT taken as "none": the rules miss many real gestures, and those would be taught as nothing.

Sample ids come from the log file and the event number, so importing twice adds nothing. `state` (data/online/use_import.json)
remembers which events of each file were taken.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from src.hand_direction import SEP, of_frames, split
from src.online.samples import PSEUDO_CANDIDATE, VALIDATED_PSEUDO, SampleStore
from src.use_log import INDEX_SUFFIX

STATE_FILE = "use_import.json"
NONE_LABEL = "none"
NEW_MIN = 20                 # uses of a taught gesture before the model gets a class for it
CONTEXT_SECONDS = 1.0        # history before the labelled stretch (the model looks back half a second)
BEFORE_MARKED = .5           # labelled stretch before a marked command: what set it off
BEFORE_RULE = .15            # ... before a rule command: the moment of the pinch
BEFORE_TAUGHT = .4           # ... before a taught gesture's command: the shape was held to give it
AFTER = .15
MIN_HAND = .5                # share of the labelled stretch that must have the hand


CLICK_ACTIONS = ("left_click", "right_click")


DOUBLE = "double"            # click kind: the second tap of a double click (a quick re-pinch right after a click)
DOUBLE_SECONDS = .7          # a left click this soon after the one before is that second tap (qt_runtime.DOUBLE_TAP)
# which way of clicking a model label belongs to (qt_runtime.USE_LABELS / USE_LABELS_VIRTUAL): the mode is part of the key
CLICK_GESTURES = {"thumb_index": ("가상 손", "엄지+검지"), "thumb_index_middle": ("가상 손", "엄지+검지+중지"),
                  "thumb_middle": ("손바닥 모드", "엄지+중지"), "thumb_ring": ("손바닥 모드", "엄지+약지")}


def click_key(source: str, key: str, label: str, kind: str = "") -> str:
    """The checking model's key of a left / right click made by a hand gesture, or "":

        "<action>:<model label>"          e.g. left_click:thumb_index (the virtual hand's thumb + index click)
        "<action>:<model label>:double"   the second tap of a double click (2026-11-11: "어떤 모드의, 어떤 식의 좌클릭인지도
                                          세부 분류"): its half second before holds the first click, not a hand at rest

    The label differs by mode (thumb_middle with the rules, thumb_index with the virtual hand), so the mode is in the key
    (the same key as src/use_gate.py for the plain click).
    2026-11-11, the person's decision: clicks set off by a pinch that only LOOKS closed from the camera's angle are to be
    stopped by a model that sees the half second before the click, learned from the person's own clicks (and the ones they
    marked as not meant) - like the taught gestures (src/online/verifier.py)."""
    if not (source == "rule" and key in CLICK_ACTIONS and label and label != NONE_LABEL):
        return ""
    return f"{key}:{label}" + (f":{DOUBLE}" if kind == DOUBLE and key == "left_click" else "")


def click_parts(key: str):
    """(action, model label, kind) of a click's key; ("", "", "") for anything else."""
    parts = str(key).split(":")
    if len(parts) < 2 or parts[0] not in CLICK_ACTIONS:
        return "", "", ""
    return parts[0], parts[1], (parts[2] if len(parts) > 2 else "")


def click_base(key: str) -> str:
    """The plain click's key of a kind's key (left_click:thumb_index:double -> left_click:thumb_index)."""
    action, label, _ = click_parts(key)
    return f"{action}:{label}" if action else key


def click_name(key: str) -> str:
    """What the screen calls a click's checking model: which click, in which mode, made how, of which kind."""
    action, label, kind = click_parts(key)
    if not action:
        return str(key)
    mode, fingers = CLICK_GESTURES.get(label, ("", label))
    name = ("좌클릭" if action == "left_click" else "우클릭") + (f" · {mode} ({fingers})" if mode else f" ({fingers})")
    return name + (" · 더블클릭의 두 번째" if kind == DOUBLE else "")


def click_kinds(events) -> Dict[int, str]:
    """{event id: kind} for the left clicks of one log file's events (dicts with "id", "key", "t", in the file's order): the
    kind the app logged ("click_kind"), else worked out from the time since the left click before (logged before the kind was)."""
    out: Dict[int, str] = {}
    last: Optional[float] = None
    for ev in events:
        if ev.get("key") != "left_click" or ev.get("source") != "rule":
            continue
        t = float(ev.get("t", 0.0))
        kind = ev.get("click_kind")
        if kind is None:
            kind = DOUBLE if last is not None and 0 <= t - last <= DOUBLE_SECONDS else ""
        out[ev["id"]] = str(kind)
        last = t
    return out


def learnable(source: str, key: str) -> bool:
    """A command given by a taught hand shape that fits the model's window: one the TCN can get a class for."""
    return source == "registered" or (source == "binding" and str(key).startswith("comp_"))


def event_direction(ev: Dict[str, Any]) -> str:
    """Which way the hand pointed when a logged command ran (src/hand_direction.py): the "dir" the app logged with it, else
    worked out from its frames (uses logged before 2026-11-11 have none)."""
    d = str(ev.get("dir") or "")
    if d:
        return d
    t = ev.get("t")
    return of_frames(ev.get("frames") or [], float(t) if t is not None else None)


DIRS_FILE = "use_dirs.json"       # (online root) per log file: size and {event id: direction} for the uses logged without one


def _file_directions(path: Path, root: Path, ids: set) -> Dict[int, str]:
    """Directions of the taught uses `ids` of one log file that were logged without one: read once from the full file and
    remembered in DIRS_FILE (the index has no joints)."""
    cache_path = Path(root) / DIRS_FILE
    cache = _state(cache_path)
    entry = cache.get(path.name) or {}
    size = path.stat().st_size if path.is_file() else -1
    known = {int(k): v for k, v in (entry.get("dirs") or {}).items()} if entry.get("size") == size else {}
    missing = ids - set(known)
    if missing and path.is_file():
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if '"type": "event"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("id") in missing:
                    known[int(rec["id"])] = event_direction(rec)
        cache[path.name] = {"size": size, "dirs": {str(k): v for k, v in known.items()}}
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(cache), encoding="utf-8")
            tmp.replace(cache_path)
        except OSError:
            pass
    return known


def split_taught_labels(store: SampleStore) -> int:
    """Stored uses of taught gestures labelled before the direction was part of the label get it now (from their own frames:
    the labelled stretch after the context). Returns how many were relabelled."""
    n = 0
    for s in store.samples(sources=[PSEUDO_CANDIDATE]):
        extra = s.extra or {}
        if not extra.get("taught") or SEP in s.label:
            continue
        frames = store.frames(s.sample_id)
        d = of_frames(frames[int(extra.get("context_frames", 0)):], None)
        if d:
            store.set_label(s.sample_id, split(s.label, d), s.label_source, approved=s.approved)
            n += 1
    return n


def _file_click_kinds(path: Path) -> Dict[int, str]:
    """{event id: click kind} of one log file, from its small index (the full file when there is none)."""
    index = path.with_suffix(INDEX_SUFFIX)
    events = []
    try:
        with (index if index.is_file() else path).open(encoding="utf-8") as fh:
            for line in fh:
                if '"left_click"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("type") == "event":
                    events.append({k: rec.get(k) for k in ("id", "key", "t", "source", "click_kind") if k in rec})
    except OSError:
        return {}
    return click_kinds(events)


def split_click_kinds(store: SampleStore, folder: Path | str) -> int:
    """Stored clicks from before the kind was kept get it now, from the log they came from (sample id = use-<file>-<event>).
    A click whose log file is gone stays a plain click. Returns how many were given a kind."""
    todo: Dict[str, List[Any]] = {}
    for s in store.samples(sources=[PSEUDO_CANDIDATE, VALIDATED_PSEUDO]):
        extra = s.extra or {}
        if extra.get("origin") == "use_event" and extra.get("key") == "left_click" and "kind" not in extra \
                and s.sample_id.startswith("use-"):
            stem, _, eid = s.sample_id[4:].rpartition("-")
            if eid.isdigit():
                todo.setdefault(stem, []).append((s, int(eid)))
    n = 0
    for stem, items in todo.items():
        kinds = _file_click_kinds(Path(folder) / f"{stem}.jsonl")
        for s, eid in items:
            s.extra = {**(s.extra or {}), "kind": kinds.get(eid, "")}
            n += 1
    if n:
        with store._lock:
            store._rewrite_index()
    return n


def _cut(ev: Dict[str, Any], before: float) -> Optional[Dict[str, Any]]:
    t = float(ev["t"])
    start, first = t - before - CONTEXT_SECONDS, t - before
    frames = [{"t": f["t"], "lm": f.get("lm"), "world": f.get("world")} for f in ev.get("frames") or []
              if start <= f["t"] <= t + AFTER]
    context = sum(f["t"] < first for f in frames)
    target = frames[context:]
    if len(target) < 3 or sum(f["lm"] is not None and f["world"] is not None for f in target) < MIN_HAND * len(target):
        return None
    return {"frames": frames, "context": context}


def label_for(ev: Dict[str, Any], classes: Sequence[str]) -> Optional[str]:
    """The training label of one logged command; None when it teaches nothing. A taught gesture's label is its key, whether or
    not the model has that class yet (import_events decides when it gets one)."""
    if ev.get("marked"):
        return NONE_LABEL if NONE_LABEL in classes else None
    source, key = str(ev.get("source", "")), str(ev.get("key", ""))
    if learnable(source, key):
        return split(key, event_direction(ev))       # each way the hand pointed is its own label (2026-11-11)
    label = ev.get("label") or (key if source == "binding" else "")
    if click_key(source, key, str(label)):
        return str(label)                          # a click is kept whether or not the model has a class for its gesture
    return label if label and label != NONE_LABEL and label in classes else None


def _state(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def import_events(store: SampleStore, folder: Path | str, classes: Sequence[str], *, new_min: int = NEW_MIN) -> Dict[str, Any]:
    """Adds the commands logged since the last import. Returns {"negatives", "weak", "taught", "waiting", "skipped", "new_classes"}:
    `taught` = uses of taught gestures taken, `waiting` = uses of taught gestures still short of `new_min`."""
    folder = Path(folder)
    state_path = store.root / STATE_FILE
    state = _state(state_path)
    counts: Dict[str, Any] = {"negatives": 0, "weak": 0, "taught": 0, "waiting": 0, "skipped": 0, "new_classes": []}
    split_taught_labels(store)                     # uses stored before the direction was part of the label
    split_click_kinds(store, folder)               # clicks stored before the kind (single / double's second tap) was kept
    have: Dict[str, int] = {}                      # examples already stored per label
    for s in store.samples(sources=[PSEUDO_CANDIDATE]):
        have[s.label] = have.get(s.label, 0) + 1
    ready: List[Dict[str, Any]] = []               # cut and labelled, not stored yet
    done_by_file: Dict[str, set] = {}
    for path in sorted(folder.glob("*.jsonl")):
        size = path.stat().st_size
        seen = state.get(path.name) or {}
        done = done_by_file[path.name] = set(seen.get("ids") or [])
        if seen.get("size") == size and not seen.get("waiting") and seen.get("clicks"):
            continue
        # ("clicks": files read before clicks were kept for their checking models are read once more - the clicks of a
        # gesture the model has no class for, the virtual hand's right click, were dropped then)
        again = not seen.get("clicks")
        events: Dict[int, Dict[str, Any]] = {}
        marks: Dict[int, str] = {}
        meta: Dict[str, Any] = {}
        kinds = _file_click_kinds(path)                # single click or the second tap of a double click, per event
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("type") == "session":
                    meta = rec
                elif rec.get("type") == "event" and rec.get("id") not in done:
                    events[rec["id"]] = rec
                elif (rec.get("type") == "event" and again
                      and click_key(str(rec.get("source", "")), str(rec.get("key", "")), str(rec.get("label") or ""))
                      and store.get(f"use-{path.stem}-{rec['id']}") is None):
                    events[rec["id"]] = rec            # a click dropped by the earlier reading
                elif rec.get("type") == "mark":
                    marks[rec["id"]] = str(rec.get("reason") or "f_key")
        for eid, ev in events.items():
            ev["marked"] = marks.get(eid, "")
            label = label_for(ev, classes)
            taught = not ev["marked"] and learnable(str(ev.get("source", "")), str(ev.get("key", "")))
            before = BEFORE_MARKED if ev["marked"] else BEFORE_TAUGHT if taught else BEFORE_RULE
            cut = _cut(ev, before) if label is not None else None
            if cut is None:
                done.add(eid)
                counts["skipped"] += 1
                continue
            ready.append({"file": path, "id": eid, "label": label, "taught": taught, "cut": cut, "meta": meta,
                          "marked": ev["marked"], "source": ev.get("source", ""), "key": ev.get("key", ""),
                          "suggested": str(ev.get("label") or ev.get("key") or ""), "virtual": bool(ev.get("virtual")),
                          "kind": kinds.get(eid, "")})
    fresh: Dict[str, int] = {}
    for item in ready:
        if item["taught"]:
            fresh[item["label"]] = fresh.get(item["label"], 0) + 1
    waiting_files: set = set()
    for item in ready:
        label = item["label"]
        if item["taught"] and label not in classes and have.get(label, 0) + fresh.get(label, 0) < new_min:
            counts["waiting"] += 1                 # not enough uses of this gesture yet: it stays in the log
            waiting_files.add(item["file"].name)
            continue
        path = item["file"]
        done_by_file[path.name].add(item["id"])
        sample = store.add_frames(
            item["cut"]["frames"], label=label, label_source=VALIDATED_PSEUDO if item["marked"] else PSEUDO_CANDIDATE,
            session=f"use-{path.stem}", sample_id=f"use-{path.stem}-{item['id']}", pc=str(item["meta"].get("pc", "")),
            camera=str(item["meta"].get("camera", "")), suggested_label=item["suggested"],
            extra={"origin": "use_event", "context_frames": item["cut"]["context"], "source": item["source"],
                   "key": item["key"], "marked": item["marked"], "virtual": item["virtual"], "taught": item["taught"],
                   "kind": item["kind"],
                   "click": bool(not item["marked"] and click_key(item["source"], item["key"], label))})
        if sample is None:
            counts["skipped"] += 1
        elif item["marked"]:
            counts["negatives"] += 1
        elif item["taught"]:
            counts["taught"] += 1
            if label not in classes and label not in counts["new_classes"]:
                counts["new_classes"].append(label)
        else:
            counts["weak"] += 1
    for path in folder.glob("*.jsonl"):
        state[path.name] = {"size": path.stat().st_size, "ids": sorted(done_by_file.get(path.name, ())),
                            "waiting": path.name in waiting_files, "clicks": True}
    for name in [n for n in state if not (folder / n).is_file()]:
        del state[name]                            # the log dropped that file (its size limit)
    tmp = state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    tmp.replace(state_path)
    return counts


def pending_counts(folder: Path | str, root: Path | str) -> Dict[str, int]:
    """Per taught gesture: its unmarked uses in the log that no learning round has taken yet. Reads the small index files only."""
    folder = Path(folder)
    state = _state(Path(root) / STATE_FILE)
    out: Dict[str, int] = {}
    for path in sorted(folder.glob("*.jsonl")):
        index = path.with_suffix(INDEX_SUFFIX)
        if not index.is_file():
            continue
        done = set((state.get(path.name) or {}).get("ids") or [])
        events: Dict[int, str] = {}
        marked: set = set()
        no_dir: set = set()
        kinds = _file_click_kinds(path)
        for line in index.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("type") != "event" or rec.get("id") in done:
                if rec.get("type") == "mark":
                    marked.add(rec.get("id"))
                continue
            source, key = str(rec.get("source", "")), str(rec.get("key", ""))
            if learnable(source, key):
                events[rec["id"]] = split(key, str(rec.get("dir") or ""))      # counted per direction (2026-11-11)
                if not rec.get("dir"):
                    no_dir.add(rec["id"])
            elif click_key(source, key, str(rec.get("label") or "")):
                events[rec["id"]] = click_key(source, key, str(rec.get("label") or ""), kinds.get(rec["id"], ""))
        if no_dir:                                     # logged before the direction was: from the full file, once
            dirs = _file_directions(path, Path(root), no_dir - marked)
            for eid in no_dir:
                events[eid] = split(events[eid], dirs.get(eid, ""))
        for eid, key in events.items():
            if eid not in marked:
                out[key] = out.get(key, 0) + 1
    return out


def use_sources(weak: bool = True) -> List[str]:
    return [VALIDATED_PSEUDO] + ([PSEUDO_CANDIDATE] if weak else [])
