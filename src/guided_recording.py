"""
Guided recording (2026-11-05): the app tells the user what to do, so every frame gets a clean label.

First pilot set - the gestures that misfired most in the 2026-11-04 logs:
- thumb + ring (right click) and thumb + index (scroll grab): repeated `reps` times per set as
  "get ready" (label "transition", not used for training) -> "do it" (label = the gesture) -> "rest" (label "none");
- moving the cursor with a half fist and opening the hand now and then: one long stretch labelled "none" - the
  scenes those two misfired in.
Each set is done in every posture of `CONDITIONS` (camera angle / seated position), posture by posture, so the model
sees several angles. Before each set the session waits for the user ("start"), so they can settle into the posture.

Pure logic: `advance(now)` starts the next set, `update(now)` moves through the steps, `label(now)` is the label of
the current frame, `view(now)` what the screen shows.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

DEFAULTS: Dict[str, float] = {
    "rec_reps": 15.0,          # repetitions per set
    "rec_prep": 1.0,           # s "get ready"
    "rec_do": 1.6,             # s "do it"
    "rec_rest": 1.6,           # s "rest"
    "rec_free_seconds": 180.0,  # s of a free (unlabelled-gesture) stretch per posture
}

CONDITIONS = (
    "평소 자세",
    "몸을 뒤로 기대거나 옆으로 돌린 자세",
    "폰 높이나 위치를 바꾼 자세",
)


@dataclass(frozen=True)
class Task:
    key: str          # the label of its "do it" frames
    name: str
    do: str           # what to do, on screen
    free: bool = False


TASKS = (
    Task("thumb_ring", "엄지+약지 (우클릭)", "엄지를 약지 끝에 붙였다 떼세요"),
    Task("thumb_index", "엄지+검지 (스크롤 잡기)", "엄지와 검지로 집어서 위나 아래로 조금 끌고 놓으세요"),
    Task("none", "반주먹 이동 (아무 동작 아님)", "반주먹으로 커서를 이리저리 움직이고, 가끔 손을 폈다 다시 쥐세요", free=True),
)


def tasks_for(focus: str = ""):
    """All tasks, or only the one gesture the training center asked to record more of ("focused recording")."""
    picked = tuple(t for t in TASKS if t.key == focus)
    return picked or TASKS


class GuidedSession:
    def __init__(self, config: Optional[Dict[str, Any]] = None, tasks=TASKS, conditions=CONDITIONS) -> None:
        self.config: Dict[str, float] = dict(DEFAULTS)
        if config:
            self.config.update({k: float(v) for k, v in config.items() if k in DEFAULTS})
        self.sets: List[Tuple[int, Task]] = [(c, t) for c in range(len(conditions)) for t in tasks]
        self.conditions = conditions
        self.index = 0                 # current set
        self.running = False           # False = waiting for "start"
        self._t0 = 0.0
        self.done = False

    def cfg(self, key: str) -> float:
        return float(self.config[key])

    @property
    def current(self) -> Optional[Tuple[int, Task]]:
        return self.sets[self.index] if self.index < len(self.sets) else None

    def advance(self, now: float) -> None:
        """Start the waiting set (the user pressed start)."""
        if not self.done and not self.running:
            self.running = True
            self._t0 = now

    def _set_length(self, task: Task) -> float:
        if task.free:
            return self.cfg("rec_free_seconds")
        return self.cfg("rec_reps") * (self.cfg("rec_prep") + self.cfg("rec_do") + self.cfg("rec_rest"))

    def update(self, now: float) -> bool:
        """Move on when the running set is over. True when a set just finished."""
        cur = self.current
        if cur is None or not self.running:
            return False
        if now - self._t0 >= self._set_length(cur[1]):
            self.running = False
            self.index += 1
            self.done = self.index >= len(self.sets)
            return True
        return False

    def _step(self, now: float) -> Tuple[str, int, float]:
        """(phase, repetition 1.., progress of the set 0..1)."""
        cond, task = self.current
        elapsed = now - self._t0
        total = self._set_length(task)
        if task.free:
            return "free", 0, min(1.0, elapsed / total)
        cycle = self.cfg("rec_prep") + self.cfg("rec_do") + self.cfg("rec_rest")
        rep = int(elapsed // cycle)
        inner = elapsed - rep * cycle
        phase = "prep" if inner < self.cfg("rec_prep") else "do" if inner < self.cfg("rec_prep") + self.cfg("rec_do") else "rest"
        return phase, rep + 1, min(1.0, elapsed / total)

    def label(self, now: float) -> Dict[str, Any]:
        cur = self.current
        if cur is None or not self.running:
            return {"target": "idle", "phase": "waiting"}
        cond, task = cur
        phase, rep, _ = self._step(now)
        target = {"prep": "transition", "do": task.key, "rest": "none", "free": task.key}[phase]
        return {"target": target, "task": task.key, "phase": phase, "rep": rep, "condition": self.conditions[cond],
                "condition_index": cond, "set": self.index}

    def view(self, now: float) -> Dict[str, Any]:
        """Big prompt, smaller line, progress of the set, progress of everything, waiting for start?"""
        overall = self.index / len(self.sets) if self.sets else 1.0
        if self.done:
            return {"prompt": "녹화 끝! 수고하셨어요", "sub": "", "progress": 1.0, "overall": 1.0, "waiting": False}
        cond, task = self.current
        head = f"[{self.index + 1}/{len(self.sets)}] {self.conditions[cond]} · {task.name}"
        if not self.running:
            return {"prompt": f"{self.conditions[cond]}로 앉은 뒤 [시작]을 누르세요", "sub": head,
                    "progress": 0.0, "overall": overall, "waiting": True}
        phase, rep, progress = self._step(now)
        if phase == "free":
            prompt = task.do
            sub = f"{head} · 남은 시간 {max(0, int(self._set_length(task) - (now - self._t0)))}초"
        else:
            prompt = {"prep": "준비…", "do": task.do, "rest": "쉬세요 (손을 편하게)"}[phase]
            sub = f"{head} · {rep}/{int(self.cfg('rec_reps'))}회"
        return {"prompt": prompt, "sub": sub, "progress": progress, "overall": overall + progress / len(self.sets),
                "waiting": False, "phase": phase}
