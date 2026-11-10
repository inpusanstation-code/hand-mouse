"""Adding a new gesture from a few demonstrations (ported from virtual-hand-20261110 `src/online/registration.py`).

Frame by frame, on the frame thread; the caller keeps OS input off while it runs (SetBusy "enrolling").
prep -> do -> rest for each demonstration; a lost hand stops the clock. Then every demonstration is checked against a
class made from the others, and the rest frames must not fire it. Only the person's approval adds the class.
Changes from the source: no sample store (the caller saves `demo_frames()`); the slot the gesture fires as is chosen
here (`custom_pose.slot1..8`).
"""
from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Mapping, Optional

import numpy as np

from manux.perception.pose_memory import RUN_FRAMES, USER_SOURCE, PoseMemory, pose_features

EVENT_CLASS_ADDED = "class_added"
CONTEXT_FRAMES = 15
SKIP_DO_FRAMES = 10          # the clock starts on the schedule, the hand arrives a moment later
MIN_FRAMES = 25
MIN_GOOD_DEMOS = 3
CONFUSED_SHARE = .3
SLOTS = tuple(f"slot{i}" for i in range(1, 9))


@dataclass
class RegistrationConfig:
    demos: int = 5
    prep_seconds: float = 1.5
    do_seconds: float = 2.0
    rest_seconds: float = 1.0
    run_frames: int = RUN_FRAMES
    required_self_hits: float = .6


class RegistrationError(ValueError):
    pass


def free_slot(memory: PoseMemory) -> str:
    used = {e.extra.get("slot") for e in memory.registered()}
    for slot in SLOTS:
        if slot not in used:
            return slot
    raise RegistrationError(f"동작은 {len(SLOTS)}개까지 등록할 수 있어요. 하나를 지우고 다시 해 주세요")


def check_name(name: str, memory: PoseMemory) -> str:
    name = (name or "").strip()
    if not name:
        raise RegistrationError("동작 이름을 입력해 주세요")
    if len(name) > 30:
        raise RegistrationError("이름은 30자까지 쓸 수 있어요")
    if name.lower() in ("none", "unknown") or name in memory.classes:
        raise RegistrationError(f"'{name}' 이름은 이미 있어요")
    return name


def has_run(hit: np.ndarray, run: int) -> bool:
    count = 0
    for value in hit:
        count = count + 1 if value else 0
        if count >= run:
            return True
    return False


class RegistrationSession:
    def __init__(self, name: str, memory: PoseMemory, aspect: float, config: Optional[RegistrationConfig] = None) -> None:
        self.name = check_name(name, memory)
        self.slot = free_slot(memory)
        self.memory, self.aspect = memory, aspect
        self.config = config or RegistrationConfig()
        self.session = "reg-" + uuid.uuid4().hex[:10]
        self.state = "prep"          # prep | do | rest | review | failed | done | cancelled
        self.demo = 0
        self._left = self.config.prep_seconds
        self._last_t: Optional[float] = None
        self.hand_seen = False
        self._ring: Deque[Dict[str, Any]] = deque(maxlen=CONTEXT_FRAMES)
        self._current: List[Dict[str, Any]] = []
        self._current_context = 0
        self._rest: List[Dict[str, Any]] = []
        self.demos: List[Dict[str, Any]] = []
        self.report: Optional[Dict[str, Any]] = None
        self.message = ""
        self._poses: List[np.ndarray] = []

    @property
    def active(self) -> bool:
        return self.state in ("prep", "do", "rest")

    def update(self, t: float, lm: Any, world: Any) -> None:
        if not self.active:
            return
        dt = 0.0 if self._last_t is None else max(0.0, min(t - self._last_t, .25))
        self._last_t = t
        self.hand_seen = lm is not None and world is not None
        frame = {"t": float(t), "lm": lm, "world": world}
        if self.state == "do":
            if self.hand_seen:
                self._current.append(frame)
        elif self.state == "rest" and self.hand_seen:
            self._rest.append(frame)
        if self.hand_seen:
            self._left -= dt                  # no hand: the clock waits
        if self.state != "do":
            self._ring.append(frame)
        if self._left > 0:
            return
        if self.state == "prep":
            self.state, self._left = "do", self.config.do_seconds
            self._current = [f for f in self._ring if f["lm"] is not None and f["world"] is not None]
            self._current_context = len(self._current)
        elif self.state == "do":
            self.demos.append({"frames": self._current, "context": self._current_context})
            self._current = []
            self.state, self._left = "rest", self.config.rest_seconds
        else:
            self.demo += 1
            if self.demo >= self.config.demos:
                self._finish()
            else:
                self.state, self._left = "prep", self.config.prep_seconds

    def view(self) -> Dict[str, Any]:
        return {"state": self.state, "name": self.name, "slot": self.slot, "demo": min(self.demo + 1, self.config.demos),
                "demos": self.config.demos, "seconds": max(0.0, round(self._left, 1)), "hand": self.hand_seen,
                "message": self.message, "report": self.report}

    # ---------------------------------------------------------------- checks
    def _finish(self) -> None:
        good = [d for d in self.demos if len(d["frames"]) - d["context"] >= MIN_FRAMES]
        if len(good) < MIN_GOOD_DEMOS:
            self.state, self.message = "failed", "시연이 너무 짧거나 손이 잘 보이지 않았어요. 다시 해 주세요"
            return
        self.demos = good
        self._poses = [pose_features(d["frames"], self.aspect)[d["context"] + SKIP_DO_FRAMES:] for d in good]
        self.report = self.check(self._poses)
        self.state = "review"

    def check(self, poses: List[np.ndarray]) -> Dict[str, Any]:
        """Each demonstration against a class made from the others; then the rest frames must not fire it."""
        recognised, confused, total = [], {}, 0
        for i, held in enumerate(poses):
            trial = self.memory.copy()
            others = [z for j, z in enumerate(poses) if j != i]
            ids = np.concatenate([np.full(len(z), j) for j, z in enumerate(others)])
            trial.add_class(self.name, np.concatenate(others), demo_ids=ids)
            index = trial.classify_arrays(held)[0]
            own = trial.labels.index(self.name)
            recognised.append(has_run(index == own, self.config.run_frames))
            for c in index[(index >= 0) & (index != own)]:
                confused[trial.labels[int(c)]] = confused.get(trial.labels[int(c)], 0) + 1
            total += len(held)
        trial = self.memory.copy()
        ids = np.concatenate([np.full(len(z), j) for j, z in enumerate(poses)])
        trial.add_class(self.name, np.concatenate(poses), demo_ids=ids)
        rest_fires = False
        if self._rest:
            rest_index = trial.classify_arrays(pose_features(self._rest, self.aspect))[0]
            rest_fires = has_run(rest_index == trial.labels.index(self.name), self.config.run_frames)
        hits = int(sum(recognised))
        reliable = hits / len(poses) >= self.config.required_self_hits and not rest_fires
        top = max(confused, key=confused.get) if confused else ""
        if top and confused[top] < CONFUSED_SHARE * total:
            top = ""
        return {"demos": len(poses), "recognised": hits, "reliable": bool(reliable), "rest_fires": bool(rest_fires),
                "confused_with": top, "event": EVENT_CLASS_ADDED}

    # ---------------------------------------------------------------- the person decides
    def approve(self) -> Dict[str, Any]:
        """Adds the class to `memory` (prototypes only). The caller saves the memory and `demo_frames()`."""
        if self.state != "review":
            raise RegistrationError("확인할 시연이 없어요")
        ids = np.concatenate([np.full(len(z), j) for j, z in enumerate(self._poses)])
        entry = self.memory.add_class(self.name, np.concatenate(self._poses), demo_ids=ids, source=USER_SOURCE,
                                      extra={"event": EVENT_CLASS_ADDED, "session": self.session, "slot": self.slot})
        self.state = "done"
        return {"event": EVENT_CLASS_ADDED, "label": entry.label, "slot": self.slot, "prototypes": len(entry.prototypes),
                "neural_weights_changed": False}

    def demo_frames(self) -> Dict[str, Any]:
        """Joints only (no pictures) of the kept demonstrations, for later training."""
        def plain(frame: Mapping[str, Any]) -> Dict[str, Any]:
            return {"t": frame["t"], "lm": [list(map(float, p)) for p in frame["lm"]],
                    "world": [list(map(float, p)) for p in frame["world"]]}
        return {"schema": "manux-pose-demos/1", "label": self.name, "slot": self.slot, "session": self.session,
                "aspect": self.aspect, "label_source": "user_confirmed",
                "demos": [{"context": d["context"], "frames": [plain(f) for f in d["frames"]]} for d in self.demos]}

    def cancel(self) -> None:
        self.state, self.demos, self._rest = "cancelled", [], []
