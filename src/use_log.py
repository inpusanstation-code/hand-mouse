"""What the hand did around every command it gave in everyday use, for training the TCN later (2026-11-11, step 1).

Whenever a hand command is carried out (a rule click or grab, a bound command, a registered gesture, an index pointer click) the
joints from PRE_SECONDS before it to POST_SECONDS after it are written: screen landmarks and 3D world landmarks, no image, no
window title, no command text. F within MARK_SECONDS (or pausing right after) adds a mark: "that was not meant".

The TCN runs alongside as a shadow: it never blocks anything here. Each event keeps what it would have said (`shadow`) and its
class probabilities per frame (`p`), so scripts/use_event_report.py can count, per gesture, how many marked commands it would have
stopped and how many unmarked ones it would have stopped by mistake.

One JSON line per record in logs/use_events/<date>-<time>-<pc>.jsonl (logs/ is not in git; the PC is the nickname from config
"pc_alias"). Writing happens on a worker thread behind a short queue; the camera never waits for the disk. The folder is kept under
`max_mb` by deleting the oldest files.
"""
from __future__ import annotations

import json
import queue
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

PRE_SECONDS = 3.0       # joints kept before each command (2 s until 2026-11-11; the person asked for 2-3 s of context each way:
POST_SECONDS = 2.0      # ... and after it. What is not logged cannot be learned from later; the models use .5 s of it today)
MARK_SECONDS = 5.0      # F this long after a command marks it
MAX_MB = 300.0
QUEUE_SIZE = 64
INDEX_SUFFIX = ".idx"

# GestureGate state that confirmed() changes; a shadow look puts it back
_GATE_STATE = ("quality_withheld", "spatial_vetoed", "ood_vetoed", "spatial_boosted", "last_rejection_reason", "last_ood")


def shadow_verdict(gate: Any, label: str, now: float) -> Optional[Dict[str, Any]]:
    """What the intent checker says about `label` right now, without changing its counters or what it shows.
    None before its first frame. `would_pass` is missing for a label the model was not trained on."""
    probs = getattr(gate, "last", None)
    if gate is None or probs is None:
        return None
    classes = list(gate.classes)
    values = [float(v) for v in probs]
    out: Dict[str, Any] = {"classes": classes}
    if values and len(values) == len(classes):
        top = max(range(len(values)), key=values.__getitem__)
        out["top"], out["top_p"] = classes[top], round(values[top], 4)
    if label and label in classes and label not in getattr(gate, "disabled_gestures", ()):
        saved = {k: getattr(gate, k, None) for k in _GATE_STATE}
        try:
            ok = bool(gate.confirmed(label, now))
            reason = str(gate.last_rejection_reason or "")
        finally:
            for k, v in saved.items():
                setattr(gate, k, v)
        out.update(label=label, p=round(values[classes.index(label)], 4), would_pass=ok, reason=reason)
    return out


class UseLog:
    def __init__(self, folder: Path, pc: str = "", camera: str = "", max_mb: float = MAX_MB, background: bool = True) -> None:
        self.folder = Path(folder)
        self.pc = pc or "pc"
        self.camera = camera
        self.max_mb = float(max_mb)
        self._frames: Deque[Dict[str, Any]] = deque()
        self._open: List[Dict[str, Any]] = []                 # commands still collecting the frames after them
        self._path: Optional[Path] = None
        self._next_id = 1
        self.last: Optional[Dict[str, Any]] = None            # the latest command: id, t, source, key
        self._marked: set = set()
        self.events = 0
        self.marks = 0
        self.dropped = 0
        self.failed = ""
        self._queue: "Optional[queue.Queue[Optional[Dict[str, Any]]]]" = None
        self._worker: Optional[threading.Thread] = None
        if background:
            self._queue = queue.Queue(maxsize=QUEUE_SIZE)
            self._worker = threading.Thread(target=self._work, name="use-log", daemon=True)
            self._worker.start()

    # ------------------------------------------------------------------ every frame (camera thread)
    def frame(self, now: float, hand: Any, probs: Any = None) -> None:
        rec: Dict[str, Any] = {"t": round(now, 4)}
        if hand is not None:
            rec["lm"] = [[round(p.x, 5), round(p.y, 5), round(p.z, 5)] for p in hand.landmarks]
            world = getattr(hand, "world", None)
            if world:
                rec["world"] = [[round(float(v), 5) for v in (p if isinstance(p, (list, tuple)) else (p.x, p.y, p.z))]
                                for p in world]
        if probs is not None:
            rec["p"] = [round(float(v), 3) for v in probs]
        self._frames.append(rec)
        while self._frames and now - self._frames[0]["t"] > PRE_SECONDS:
            self._frames.popleft()
        still = []
        for ev in self._open:
            if now - ev["t"] > POST_SECONDS:
                self._put(ev)
            else:
                ev["frames"].append(rec)
                still.append(ev)
        self._open = still

    # ------------------------------------------------------------------ events
    def event(self, source: str, key: str, now: float, *, label: str = "", shadow: Optional[Dict[str, Any]] = None,
              extra: Optional[Dict[str, Any]] = None) -> int:
        """A command was carried out at `now`. `source`: rule | binding | registered | pointer. `key`: the action or binding key.
        `label`: the model label of that hand gesture, when there is one. The record is written once POST_SECONDS have passed."""
        eid = self._next_id
        self._next_id += 1
        rec = {"type": "event", "id": eid, "source": source, "key": key, "label": label, "t": round(now, 4),
               "wall": time.strftime("%Y-%m-%d %H:%M:%S"), "shadow": shadow, **(extra or {}), "frames": list(self._frames)}
        self._open.append(rec)
        self.last = {"id": eid, "t": now, "source": source, "key": key}
        self.events += 1
        return eid

    def mark_last(self, now: float, reason: str = "f_key") -> Optional[Dict[str, Any]]:
        """The latest command, if it was within MARK_SECONDS and not marked yet, was not meant. Returns it (id, source, key)."""
        last = self.last
        if last is None or now - last["t"] > MARK_SECONDS or last["id"] in self._marked:
            return None
        self._marked.add(last["id"])
        self.marks += 1
        self._put({"type": "mark", "id": last["id"], "t": round(now, 4), "reason": reason,
                   "wall": time.strftime("%Y-%m-%d %H:%M:%S")})
        return dict(last)

    def close(self, timeout: float = 5.0) -> None:
        """Write the commands still waiting for their frames, then stop the worker."""
        for ev in self._open:
            self._put(ev, wait=True)
        self._open = []
        if self._queue is not None and self._worker is not None:
            self._queue.put(None)
            self._worker.join(timeout)
            self._queue = self._worker = None

    # ------------------------------------------------------------------ file
    def _put(self, rec: Dict[str, Any], wait: bool = False) -> None:
        if self._queue is None:
            self._write(rec)
            return
        try:
            self._queue.put(rec, block=wait, timeout=2.0 if wait else None)
        except queue.Full:
            self.dropped += 1

    def _work(self) -> None:
        assert self._queue is not None
        while True:
            rec = self._queue.get()
            if rec is None:
                return
            self._write(rec)

    def _write(self, rec: Dict[str, Any]) -> bool:
        try:
            if self._path is None:
                self.folder.mkdir(parents=True, exist_ok=True)
                self._prune()
                self._path = self.folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{self.pc}.jsonl"
                head = {"type": "session", "pc": self.pc, "camera": self.camera, "wall": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "pre_seconds": PRE_SECONDS, "post_seconds": POST_SECONDS}
                for target in (self._path, self._path.with_suffix(INDEX_SUFFIX)):
                    with target.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(head, ensure_ascii=False) + "\n")
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            # the same record without its joints: what the report and the gate decision read (the full file is ~150 KB an event)
            with self._path.with_suffix(INDEX_SUFFIX).open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({k: v for k, v in rec.items() if k != "frames"}, ensure_ascii=False) + "\n")
            return True
        except Exception as exc:          # a full disk must not stop the hand
            self.failed = str(exc)
            return False

    def _prune(self) -> None:
        """Oldest files go first until the folder is under max_mb (file names start with the date)."""
        files = sorted(self.folder.glob("*.jsonl"))
        total = sum(f.stat().st_size for f in files)
        limit = self.max_mb * 1024 * 1024
        for f in files:
            if total <= limit:
                break
            size = f.stat().st_size
            try:
                f.unlink()
                total -= size
                f.with_suffix(INDEX_SUFFIX).unlink(missing_ok=True)
            except OSError:
                pass


def read_events(folder: Path, frames: bool = True) -> List[Dict[str, Any]]:
    """All commands under `folder`, each with "file", "pc" and "marked" ("" or the reason: f_key, user_cancelled).
    `frames=False` reads the small index next to each file (no joints), which is all the report and the gate decision need."""
    out: List[Dict[str, Any]] = []
    for path in sorted(Path(folder).glob("*.jsonl")):
        events: Dict[int, Dict[str, Any]] = {}
        marks: Dict[int, str] = {}
        pc = ""
        source = path.with_suffix(INDEX_SUFFIX) if not frames and path.with_suffix(INDEX_SUFFIX).is_file() else path
        for line in source.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue                  # a line cut off by a crash
            if rec.get("type") == "session":
                pc = rec.get("pc", "")
            elif rec.get("type") == "event":
                events[rec["id"]] = {**rec, "file": path.name, "pc": pc}
            elif rec.get("type") == "mark":
                marks[rec["id"]] = str(rec.get("reason") or "f_key")     # the mark can come before its event's record
        for eid, ev in events.items():
            ev["marked"] = marks.get(eid, "")
            out.append(ev)
    return out
