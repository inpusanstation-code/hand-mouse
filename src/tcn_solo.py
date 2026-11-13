"""What the TCN would catch on its own: a watch, nothing acts on it (2026-11-13).

Today the TCN only checks what the rules want to do (src/gesture_gate.py): a gesture the rules miss is never carried out, however
sure the model is. Before letting the model fire by itself ("rule OR model"), this counts in everyday use what that would add:

- each time the watching TCN confirms a hand gesture (its own rising edge, the same test the checker uses: `confirmed`),
- and the rules did not start that gesture's command around it (BOTH_BEFORE before to BOTH_AFTER after),

that moment is written with its joints to logs/tcn_solo/ (logs/ is not in git). After RETRY_SECONDS it gets an outcome:

- "retry": the rules started that gesture's command a little later (the person tried again: likely a miss the model would have
  caught earlier),
- "alone": nothing followed (either a miss the person gave up on, or a misfire of the model alone: the log cannot tell which; the
  joints are kept so they can be looked at).

Moments the rules also caught ("both") are only counted. A "minute" record every minute keeps how long the hand was watched, so
scripts/tcn_solo_report.py can give rates per minute. Mouse control off (paused), guided recording and the index pointer are not
watched: the rules do not act then, so every model moment would look like a miss.

Two more things are collected here for training a TCN per hand mode from everyday use (2026-11-13, user: "안내 녹화 자료를
실사용하는 동안에 앱이 자동으로 수집"):

- "quiet": every QUIET_EVERY seconds at most, QUIET_LEN seconds of a hand that only moves the cursor - the hand is seen, the rules
  act on it normally (no motion / pointing mode, no sign), no command and no model moment from QUIET_GUARD before to QUIET_AFTER
  after, no fingertip near the thumb and no fist. These are clean "none" examples (label_source "auto"). Quiet stretches used to
  be left out because a gesture the rules missed can hide in them: the guards above leave those out.
- "retry" moments wait for the person's review (src/use_review.py verdicts in logs/tcn_solo/reviews.json, the same 통과 / 오탐지
  window as the uses): passed = an example of that gesture the rules missed, the only kind of data that can raise recognition.

Every record keeps the rules that judged it and where its label came from (src/label_meta.py).

Nothing here changes what the mouse does.
"""
from __future__ import annotations

import json
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional, Tuple

from src.use_log import shadow_verdict

BOTH_BEFORE = 1.0       # a rule start this long before the model's moment: the rules caught it first
BOTH_AFTER = 0.6        # ... or this long after: the same moment, the rules were only a little later
RETRY_SECONDS = 4.0     # a rule start of the same gesture within this: the person tried again
POST_SECONDS = 2.0      # joints kept after the moment (the use log keeps 3 s before)
OFF_SECONDS = 0.2       # the model must let go this long before the same gesture counts as a new moment
MINUTE = 60.0
QUIET_EVERY = 15.0      # a quiet stretch at most this often (about 60 KB each)
QUIET_LEN = 1.2         # its length (the model looks at 0.5 s: a few windows each)
QUIET_GUARD = 1.5       # nothing before it for this long
QUIET_AFTER = 1.5       # ... and after it (it is written this late; the use log keeps 3 s of frames)
QUIET_PINCH = 0.5       # every fingertip this far from the thumb tip (hand sizes; a click closes at .25)
QUIET_FIST = 1.1        # mean fingertip-wrist distance under this (hand sizes) is a fist: not taken
SOLO_KEY = "solo"       # review keys: "solo:<virtual|palm>:<label>"

# the model labels the rules start commands for (src/qt_runtime.py USE_LABELS / USE_LABELS_VIRTUAL); V sign and thumbs up have
# their own detectors and are left out
PALM_LABELS = ("thumb_middle", "thumb_ring", "thumb_index", "thumb_pinky", "palm_side")
VIRTUAL_LABELS = ("thumb_index",)


class SoloWatch:
    """Fed every watched frame (`step`) and every rule command start (`rule`); writes through `put` (a UseLog's writer)."""

    def __init__(self, put, *, pc: str = "", model: str = "", rules: Optional[Dict[str, str]] = None) -> None:
        self.put = put
        self.pc = pc
        self.model = model
        self.rules = rules or {}
        self._commands: List[float] = []                     # recent starts of any command (rules, bindings, pointing...)
        self._moments: List[float] = []                      # recent model moments
        self._normal: Deque[Tuple[float, bool]] = deque()    # (frame time, the rules acted on the hand as usual)
        self._quiet_t = -1e9
        self.quiet = 0
        self.retries: Dict[str, int] = {}                    # retry moments written this run, per review key
        self._on: Dict[str, bool] = {}
        self._off_since: Dict[str, float] = {}
        self._rules: List[Tuple[float, str]] = []            # recent rule starts: (t, label)
        self._pending: List[Dict[str, Any]] = []
        self._next_id = 1
        self._minute_t: Optional[float] = None
        self._seen = 0.0
        self._hand = 0.0
        self._last_t: Optional[float] = None
        self._counts: Dict[str, Dict[str, int]] = {}
        self.virtual = False

    # ------------------------------------------------------------------ rules
    def rule(self, now: float, label: str) -> None:
        """The rules started the command of the hand gesture `label` (a model label) at `now`."""
        self.command(now)
        if not label:
            return
        self._rules.append((now, label))
        cut = now - RETRY_SECONDS - BOTH_BEFORE - 1.0
        self._rules = [r for r in self._rules if r[0] >= cut]

    def command(self, now: float) -> None:
        """Any command started at `now` (a quiet stretch must have none around it)."""
        self._commands.append(now)
        self._commands = [t for t in self._commands if t >= now - 10.0]

    def normal(self, now: float, ok: bool) -> None:
        """The rules looked at this frame's hand as usual (`ok`: and only moved the cursor or did nothing). A second word for
        the same frame replaces the first: the runtime says False when the frame starts and the rules say otherwise later."""
        if self._normal and self._normal[-1][0] == now:
            self._normal.pop()
        self._normal.append((now, bool(ok)))
        while self._normal and now - self._normal[0][0] > 10.0:
            self._normal.popleft()

    def _rule_near(self, label: str, lo: float, hi: float) -> Optional[float]:
        for t, lab in self._rules:
            if lab == label and lo <= t <= hi:
                return t
        return None

    # ------------------------------------------------------------------ frames
    def step(self, now: float, watcher: Any, frames: Iterable[Dict[str, Any]], *, hand: bool, virtual: bool,
             busy: Iterable[str] = (), aspect: float = 720 / 1280) -> None:
        """One watched frame. `watcher`: the TCN watching this frame (already stepped). `frames`: the use log's recent frames.
        `busy`: labels whose rule command is going on (a grab or a drag): the model seeing that gesture again is not new."""
        busy = set(busy)
        frames = list(frames)
        if self._last_t is not None and 0 < now - self._last_t < 0.5:
            self._seen += now - self._last_t
            if hand:
                self._hand += now - self._last_t
        self._last_t = now
        self.virtual = virtual
        if watcher is not None:
            classes = set(getattr(watcher, "classes", ()))
            for label in (VIRTUAL_LABELS if virtual else PALM_LABELS):
                if label not in classes:
                    continue
                verdict = shadow_verdict(watcher, label, now) if hand else None
                on = bool(verdict and verdict.get("would_pass"))
                was = self._on.get(label, False)
                if on and not was and now - self._off_since.get(label, -1e9) >= OFF_SECONDS and label not in busy:
                    self._moment(now, label, verdict or {}, frames, virtual)
                if not on and was:
                    self._off_since[label] = now
                if on or was:
                    self._on[label] = on
        self._settle(now, frames)
        self._quiet(now, frames, aspect)
        if self._minute_t is None:
            self._minute_t = now
        elif now - self._minute_t >= MINUTE:
            self._flush_minute(now)

    def _moment(self, now: float, label: str, verdict: Dict[str, Any], frames: List[Dict[str, Any]], virtual: bool) -> None:
        eid = self._next_id
        self._next_id += 1
        self._moments.append(now)
        self._moments = [t for t in self._moments if t >= now - 10.0]
        self._pending.append({"id": eid, "t": now, "label": label, "p": verdict.get("p"), "virtual": virtual,
                              "wall": time.strftime("%Y-%m-%d %H:%M:%S"), "pre": [f for f in frames if f.get("t", 0) <= now],
                              "post": None, "outcome": "", "rule_dt": None})

    def _settle(self, now: float, frames: List[Dict[str, Any]]) -> None:
        keep = []
        for m in self._pending:
            t, label = m["t"], m["label"]
            if not m["outcome"] and now - t >= BOTH_AFTER:
                if self._rule_near(label, t - BOTH_BEFORE, t + BOTH_AFTER) is not None:
                    m["outcome"] = "both"
            if m["post"] is None and now - t >= POST_SECONDS:
                m["post"] = [f for f in frames if t < f.get("t", 0) <= t + POST_SECONDS]
            if not m["outcome"]:
                later = self._rule_near(label, t + BOTH_AFTER, t + RETRY_SECONDS)
                if later is not None:
                    m["outcome"], m["rule_dt"] = "retry", round(later - t, 3)
                elif now - t >= RETRY_SECONDS:
                    m["outcome"] = "alone"
            if m["outcome"] and (m["outcome"] == "both" or m["post"] is not None):
                self._write(m)
            else:
                keep.append(m)
        self._pending = keep

    def _count(self, label: str, outcome: str) -> None:
        mode = "virtual" if self.virtual else "palm"
        row = self._counts.setdefault(f"{mode}:{label}", {})
        row[outcome] = row.get(outcome, 0) + 1

    def _write(self, m: Dict[str, Any]) -> None:
        self._count(m["label"], m["outcome"])
        if m["outcome"] == "both":
            return
        if m["outcome"] == "retry":
            key = review_key(m["virtual"], m["label"])
            self.retries[key] = self.retries.get(key, 0) + 1
        self.put({"type": "solo", "id": m["id"], "t": round(m["t"], 4), "wall": m["wall"], "label": m["label"],
                  "p": m["p"], "virtual": m["virtual"], "outcome": m["outcome"], "rule_dt": m["rule_dt"],
                  "model": self.model, "rules": self.rules, "label_source": "model",
                  "frames": m["pre"] + (m["post"] or [])})

    # ------------------------------------------------------------------ quiet stretches ("none" from everyday use)
    def _quiet(self, now: float, frames: List[Dict[str, Any]], aspect: float) -> None:
        end = now - QUIET_AFTER
        start = end - QUIET_LEN
        if now - self._quiet_t < QUIET_EVERY or not frames or frames[0].get("t", now) > start:
            return
        lo = start - QUIET_GUARD
        if any(lo <= t <= now for t in self._commands) or any(lo <= t <= now for t in self._moments):
            return
        if any(m["t"] >= lo for m in self._pending):
            return
        normal = [ok for t, ok in self._normal if lo <= t <= now]
        if not normal or not all(normal) or self._normal[0][0] > lo:
            return
        window = [f for f in frames if start <= f.get("t", 0) <= end]
        if len(window) < 10 or not all(_quiet_hand(f.get("lm"), aspect) for f in window):
            return
        self._quiet_t = now
        self.quiet += 1
        eid = self._next_id
        self._next_id += 1
        self.put({"type": "quiet", "id": eid, "t": round(start, 4), "end": round(end, 4),
                  "wall": time.strftime("%Y-%m-%d %H:%M:%S"), "label": "none", "virtual": self.virtual,
                  "model": self.model, "rules": self.rules, "label_source": "auto", "frames": window})

    def _flush_minute(self, now: float) -> None:
        if self._seen > 0:
            self.put({"type": "minute", "t": round(now, 4), "wall": time.strftime("%Y-%m-%d %H:%M:%S"),
                      "seen_s": round(self._seen, 2), "hand_s": round(self._hand, 2), "virtual": self.virtual,
                      "counts": self._counts, "model": self.model, "rules": self.rules})
        self._minute_t = now
        self._seen = self._hand = 0.0
        self._counts = {}

    def pause(self, now: float) -> None:
        self._normal.clear()
        self._pause(now)

    def _pause(self, now: float) -> None:
        """Watching stops (control off, recording, another stage): moments still open are dropped, not judged against rules
        that were not running, and the time so far is written."""
        self._pending = []
        self._on.clear()
        self._last_t = None
        if self._minute_t is not None:
            self._flush_minute(now)
            self._minute_t = None

    def close(self, now: float) -> None:
        self.pause(now)


def _quiet_hand(lm: Any, aspect: float) -> bool:
    """A hand only moving the cursor: seen, no fingertip near the thumb tip, not a fist."""
    if not lm or len(lm) != 21:
        return False
    pts = [(float(p[0]), float(p[1]) * aspect) for p in lm]

    def d(a: int, b: int) -> float:
        return ((pts[a][0] - pts[b][0]) ** 2 + (pts[a][1] - pts[b][1]) ** 2) ** .5

    size = d(0, 9)
    if size <= 1e-6:
        return False
    if min(d(4, tip) for tip in (8, 12, 16, 20)) / size < QUIET_PINCH:
        return False
    return sum(d(0, tip) for tip in (8, 12, 16, 20)) / 4 / size >= QUIET_FIST


# ---------------------------------------------------------------------- the person's review of the retry moments
def review_key(virtual: bool, label: str) -> str:
    return f"{SOLO_KEY}:{'virtual' if virtual else 'palm'}:{label}"


def parse_key(key: str) -> Tuple[Optional[bool], str]:
    """(virtual, label) of a review key, (None, "") when it is not one."""
    parts = str(key or "").split(":")
    if len(parts) != 3 or parts[0] != SOLO_KEY or parts[1] not in ("virtual", "palm"):
        return None, ""
    return parts[1] == "virtual", parts[2]


def retry_moments(folder, key: str, frames: bool = True, limit: int = 200) -> List[Dict[str, Any]]:
    """The retry moments of one review key, oldest first, each with "file", "review" ("", "ok", "bad") and (with `frames`)
    its joints. The newest `limit`."""
    from src import use_review
    virtual, label = parse_key(key)
    if virtual is None:
        return []
    folder = Path(folder)
    reviews = use_review.load(folder)
    out: List[Dict[str, Any]] = []
    for path in sorted(folder.glob("*.jsonl")):
        idx = path.with_suffix(".idx")
        source = idx if (not frames and idx.is_file()) else path
        with source.open(encoding="utf-8") as fh:
            for line in fh:
                if '"retry"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if (rec.get("type") != "solo" or rec.get("outcome") != "retry" or rec.get("label") != label
                        or bool(rec.get("virtual")) != virtual):
                    continue
                rec["file"] = path.name
                rec["marked"] = ""
                rec["review"] = use_review.verdict(reviews, path.name, rec.get("id"))
                out.append(rec)
    return out[-limit:]


def waiting_reviews(folder) -> Dict[str, int]:
    """Retry moments without a verdict yet, per review key (read from the small index files)."""
    folder = Path(folder)
    out: Dict[str, int] = {}
    if not folder.is_dir():
        return out
    for virtual in (True, False):
        for label in (VIRTUAL_LABELS if virtual else PALM_LABELS):
            key = review_key(virtual, label)
            n = sum(1 for m in retry_moments(folder, key, frames=False, limit=10 ** 6) if not m["review"])
            if n:
                out[key] = n
    return out
