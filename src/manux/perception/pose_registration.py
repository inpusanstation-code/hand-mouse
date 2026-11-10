"""Adding a new gesture: a block of resting hands, then the pose held a few times, then a small classifier learns it.

Frame by frame, on the frame thread; the caller keeps OS input off while it runs (SetBusy "enrolling").
`rest` (REST block: the person moves their hand naturally, open and relaxed) -> `prep` -> `do` (the pose held) x
`demos` -> `training` -> `review`. A lost hand stops the clock. Only the person's approval adds the class.

2026-11-10 ('쉬는 자세 / 명령 자세를 섞지 말고 따로 찍고 AI가 섞으면 안 되나', '정적인 사인은 MLP로 몇 초 안에 학습').
The earlier way (5 x prep / do / rest, then "is a frame within the demonstrations' distance spread") never learned what
the person's resting hands look like. Measured on the person's 42 recordings (7 static poses, 18 trials, registration
data from one recording, scored on recordings not used), recall at the same false-fire rate in not-gesture time:

| way                                                        | <= 1/min | <= 2/min | <= 5/min |
| distance to 5 demonstrations (before)                      | 0%       | 0%       | 20%      |
| classifier: 5 demonstrations vs a rest block               | 0%       | 12%      | 38%      |
| classifier: 5 demonstrations vs rest block + past data     | 24%      | 35%      | 51%      |
| classifier: 3 x 1 s holds + jitter vs rest + past data     | 23%      | 34%      | 46%      |

(One snapshot, with or without jitter, recognised under 6%.) So: a REST block, three short holds with jittered copies,
and as negatives the rest block, not-gesture frames of the person's earlier recordings (`negatives`, optional) and the
gestures already registered. The threshold is the lowest score that keeps the expected false fires on held-out earlier
frames at or under TARGET_FIRES a minute. Each hold is then checked by a classifier trained without it.
Changes from the source: no sample store (the caller saves `demo_frames()`); the slot is chosen here.
"""
from __future__ import annotations

import threading
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Mapping, Optional, Sequence

import numpy as np

from manux.perception.pose_memory import RUN_FRAMES, USER_SOURCE, PoseMemory, pose_features
from manux.perception import small_mlp

EVENT_CLASS_ADDED = "class_added"
CONTEXT_FRAMES = 15
SKIP_DO_FRAMES = 8           # the clock starts on the schedule, the hand arrives a moment later
SKIP_REST_SECONDS = .5       # the hand is still arriving / settling at the start of the rest block
MIN_FRAMES = 15              # usable frames a hold needs
MIN_GOOD_DEMOS = 2
MIN_REST_FRAMES = 30
TARGET_FIRES = 2.0           # expected false fires a minute (held-out earlier not-gesture frames) the threshold allows
# 2026-11-10 ('지나가는 동작에도 너무 금방 반응한다'): the hold the gesture must last is chosen too: the shortest of
# HOLD_CHOICES that keeps the hands merely passing through (earlier not-gesture frames) at or under HOLD_TARGET_FIRES
# a minute while each demonstrated hold still lasts long enough to be recognised. The person can change it.
HOLD_CHOICES = (.2, .3, .4, .5, .6, .7, .8, 1.0)
HOLD_TARGET_FIRES = .5
DEFAULT_AUTO_HOLD = .4       # no earlier data to measure with
AUGMENT = 3                  # jittered copies per held frame
EXAMPLES_KEPT = 150          # pose rows kept with a registered class (the next registrations learn against them)
CONFUSED_SHARE = .3
SLOTS = tuple(f"slot{i}" for i in range(1, 9))
FINGERS = ((1, 2, 3, 4), (5, 6, 7, 8), (9, 10, 11, 12), (13, 14, 15, 16), (17, 18, 19, 20))


@dataclass
class RegistrationConfig:
    demos: int = 3
    rest_seconds: float = 5.0
    prep_seconds: float = 1.2
    do_seconds: float = 1.5
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


def runs(hit: np.ndarray, run: int) -> int:
    """How many times `run` frames in a row start (a held pose counts once)."""
    count = fired = 0
    for value in hit:
        count = count + 1 if value else 0
        fired += count == run
    return fired


def augment(x: np.ndarray, copies: int, rng: np.random.Generator, noise: float = .02, bend: float = .08) -> np.ndarray:
    """Jittered copies of hand-frame poses (63 = 21 joints x 3, hand sizes): joint noise and fingers a little more or
    less bent. The 63 pose columns are the joints in the hand's own frame (perception.local3d)."""
    out = []
    for row in np.asarray(x, np.float32):
        q = row.reshape(21, 3)
        for _ in range(copies):
            a = q.copy()
            for finger in FINGERS:
                base, k = a[finger[0]].copy(), 1 + rng.normal(0, bend)
                for j in finger[1:]:
                    a[j] = base + (a[j] - base) * k
            out.append((a + rng.normal(0, noise, a.shape)).ravel())
    return np.array(out, np.float32).reshape(-1, x.shape[1] if len(x) else 63)


class RegistrationSession:
    def __init__(self, name: str, memory: PoseMemory, aspect: float, config: Optional[RegistrationConfig] = None,
                 negatives: Optional[Sequence[np.ndarray]] = None, threaded: bool = False) -> None:
        """`negatives`: not-gesture pose sequences from the person's earlier recordings ((n, 63) arrays, in time order);
        `threaded`: train on a background thread (the app) instead of inside update() (tests)."""
        self.name = check_name(name, memory)
        self.slot = free_slot(memory)
        self.memory, self.aspect = memory, aspect
        self.config = config or RegistrationConfig()
        self.negatives = [np.asarray(n, np.float32) for n in (negatives or ()) if len(n)]
        self.threaded = threaded
        self.session = "reg-" + uuid.uuid4().hex[:10]
        self.state = "rest"          # rest | prep | do | training | review | failed | done | cancelled
        self.demo = 0
        self._left = self.config.rest_seconds
        self._last_t: Optional[float] = None
        self._rest_t0: Optional[float] = None
        self.hand_seen = False
        self._ring: Deque[Dict[str, Any]] = deque(maxlen=CONTEXT_FRAMES)
        self._current: List[Dict[str, Any]] = []
        self._current_context = 0
        self._rest: List[Dict[str, Any]] = []
        self.demos: List[Dict[str, Any]] = []
        self.report: Optional[Dict[str, Any]] = None
        self.message = ""
        self._poses: List[np.ndarray] = []
        self._model: Optional[Dict[str, Any]] = None
        self.hold = DEFAULT_AUTO_HOLD
        self._thread: Optional[threading.Thread] = None

    @property
    def active(self) -> bool:
        return self.state in ("rest", "prep", "do", "training")

    def update(self, t: float, lm: Any, world: Any) -> None:
        if self.state == "training":
            if self._thread is not None and not self._thread.is_alive():
                self._thread = None
                self.state = "review" if self.report is not None else "failed"
            return
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
            self._rest_t0 = t if self._rest_t0 is None else self._rest_t0
            if t - self._rest_t0 >= SKIP_REST_SECONDS:
                self._rest.append(frame)
        if self.hand_seen:
            self._left -= dt                  # no hand: the clock waits
        if self.state != "do":
            self._ring.append(frame)
        if self._left > 0:
            return
        if self.state == "rest":
            self.state, self._left = "prep", self.config.prep_seconds
        elif self.state == "prep":
            self.state, self._left = "do", self.config.do_seconds
            self._current, self._current_context = [], 0
        elif self.state == "do":
            self.demos.append({"frames": self._current, "context": self._current_context})
            self._current = []
            self.demo += 1
            if self.demo >= self.config.demos:
                self._finish()
            else:
                self.state, self._left = "prep", self.config.prep_seconds

    def view(self) -> Dict[str, Any]:
        return {"state": self.state, "name": self.name, "slot": self.slot, "demo": min(self.demo + 1, self.config.demos),
                "demos": self.config.demos, "seconds": max(0.0, round(self._left, 1)), "hand": self.hand_seen,
                "message": self.message, "report": self.report}

    # ---------------------------------------------------------------- learning
    def _finish(self) -> None:
        good = [d for d in self.demos if len(d["frames"]) - SKIP_DO_FRAMES >= MIN_FRAMES]
        if len(good) < MIN_GOOD_DEMOS:
            self.state, self.message = "failed", "‘지금’ 동안 손이 잘 보이지 않았어요. 손 전체가 보이게 다시 해 주세요"
            return
        if len(self._rest) < MIN_REST_FRAMES:
            self.state, self.message = "failed", "‘쉬는 손’ 동안 손이 잘 보이지 않았어요. 다시 해 주세요"
            return
        self.demos = good
        self._poses = [pose_features(d["frames"], self.aspect)[SKIP_DO_FRAMES:] for d in good]
        self.state = "training"
        if self.threaded:
            self._thread = threading.Thread(target=self._train_safely, name="manux-pose-training", daemon=True)
            self._thread.start()
        else:
            self._train_safely()
            self.state = "review" if self.report is not None else "failed"

    def _train_safely(self) -> None:
        try:
            self._model, self.report = self.train(self._poses)
        except Exception as exc:                      # never leave the session stuck in "training"
            self.report, self.message = None, f"학습하지 못했어요: {exc}"

    def _negative_parts(self, rng: np.random.Generator):
        """(training negatives, held-out sequences for the threshold, minutes of held-out frames)."""
        rest = pose_features(self._rest, self.aspect)
        others = [np.asarray(e.mlp.get("examples") or e.prototypes, np.float32) if e.mlp else e.prototypes
                  for e in self.memory.registered()]
        train_seq, held = [], []
        for i, seq in enumerate(self.negatives):
            (held if i % 2 else train_seq).append(seq)
        past = np.concatenate(train_seq) if train_seq else np.zeros((0, rest.shape[1]), np.float32)
        if len(past) > 4000:
            past = past[rng.choice(len(past), 4000, replace=False)]
        neg = np.concatenate([rest] + [o for o in others if len(o)] + [past])
        minutes = sum(len(s) for s in held) / 30.0 / 60.0
        return neg, held, minutes

    def train(self, poses: List[np.ndarray]):
        rng = np.random.default_rng(0)
        neg, held, minutes = self._negative_parts(rng)
        pos = np.concatenate([np.concatenate([p, augment(p, AUGMENT, rng)]) for p in poses])
        model = small_mlp.train(pos, neg)
        threshold, fires = .5, None
        if held and minutes > 0:
            scores = [model.score(s) for s in held]
            for thr in np.round(np.arange(.5, .995, .02), 2):
                fires = sum(runs(s >= thr, self.config.run_frames) for s in scores) / minutes
                threshold = float(thr)
                if fires <= TARGET_FIRES:
                    break
        # each hold against a classifier trained without it (same threshold)
        recognised, held_hits = [], []
        for i, held_pose in enumerate(poses):
            rest_of = [p for j, p in enumerate(poses) if j != i]
            part = np.concatenate([np.concatenate([p, augment(p, AUGMENT, rng)]) for p in rest_of])
            m = small_mlp.train(part, neg, steps=200)
            held_hits.append(m.score(held_pose) >= threshold)
            recognised.append(has_run(held_hits[-1], self.config.run_frames))
        hold, hold_fires = self._choose_hold(model, threshold, held, minutes, held_hits)
        # does an already registered gesture take these holds?
        confused, total = {}, 0
        for pose in poses:
            index = self.memory.classify_arrays(pose)[0]
            total += len(pose)
            for c in index[index >= 0]:
                label = self.memory.labels[int(c)]
                if self.memory.classes[label].source == USER_SOURCE:
                    confused[label] = confused.get(label, 0) + 1
        top = max(confused, key=confused.get) if confused else ""
        if top and confused[top] < CONFUSED_SHARE * total:
            top = ""
        hits = int(sum(recognised))
        quiet = fires is None or fires <= TARGET_FIRES
        reliable = hits / len(poses) >= self.config.required_self_hits and quiet and not top
        examples = np.concatenate(poses)
        if len(examples) > EXAMPLES_KEPT:
            examples = examples[rng.choice(len(examples), EXAMPLES_KEPT, replace=False)]
        mlp = {"model": model.to_dict(), "threshold": threshold, "examples": np.round(examples, 5).tolist(),
               "version": "pose-mlp-v1"}
        self.hold = hold
        report = {"demos": len(poses), "recognised": hits, "reliable": bool(reliable), "hold": hold,
                  "fires_at_hold": None if hold_fires is None else round(float(hold_fires), 2),
                  "fires_per_min": None if fires is None else round(float(fires), 2),
                  "checked_minutes": round(minutes, 1), "threshold": threshold,
                  # too like the person's everyday hands: false fires stay high, or the threshold that quiets them loses
                  # the pose itself
                  "rest_fires": bool(not quiet or (threshold > .5 and hits / len(poses) < self.config.required_self_hits)),
                  "confused_with": top, "event": EVENT_CLASS_ADDED}
        return mlp, report

    def _choose_hold(self, model, threshold, held, minutes, held_hits):
        """(seconds, false fires a minute at that hold) or (DEFAULT_AUTO_HOLD, None) without earlier data."""
        if not held or minutes <= 0:
            return DEFAULT_AUTO_HOLD, None
        scores = [model.score(s) >= threshold for s in held]
        need = max(1, int(np.ceil(self.config.required_self_hits * len(held_hits))))
        best = (HOLD_CHOICES[-1], None)
        for hold in HOLD_CHOICES:
            frames = max(self.config.run_frames, int(round(hold * 30)))
            fires = sum(runs(s, frames) for s in scores) / minutes
            kept = sum(has_run(h, frames) for h in held_hits)
            if kept < need:                      # the demonstrated holds are not this long: stop at the last good one
                break
            best = (hold, fires)
            if fires <= HOLD_TARGET_FIRES:
                break
        return best

    # ---------------------------------------------------------------- the person decides
    def approve(self, hold: Optional[float] = None) -> Dict[str, Any]:
        """Adds the class to `memory` (prototypes, the classifier and its hold in seconds: `hold`, else the chosen one).
        The caller saves the memory and `demo_frames()`."""
        if self.state != "review":
            raise RegistrationError("확인할 시연이 없어요")
        ids = np.concatenate([np.full(len(z), j) for j, z in enumerate(self._poses)])
        entry = self.memory.add_class(self.name, np.concatenate(self._poses), demo_ids=ids, source=USER_SOURCE,
                                      extra={"event": EVENT_CLASS_ADDED, "session": self.session, "slot": self.slot,
                                             "hold": round(float(self.hold if hold is None else hold), 2)})
        entry.mlp = self._model
        self.state = "done"
        return {"event": EVENT_CLASS_ADDED, "label": entry.label, "slot": self.slot, "prototypes": len(entry.prototypes),
                "neural_weights_changed": False, "classifier": self._model is not None}

    def demo_frames(self) -> Dict[str, Any]:
        """Joints only (no pictures) of the kept demonstrations and the rest block, for later training."""
        def plain(frame: Mapping[str, Any]) -> Dict[str, Any]:
            return {"t": frame["t"], "lm": [list(map(float, p)) for p in frame["lm"]],
                    "world": [list(map(float, p)) for p in frame["world"]]}
        return {"schema": "manux-pose-demos/1", "label": self.name, "slot": self.slot, "session": self.session,
                "aspect": self.aspect, "label_source": "user_confirmed",
                "demos": [{"context": d["context"], "frames": [plain(f) for f in d["frames"]]} for d in self.demos],
                "rest": [plain(f) for f in self._rest]}

    def cancel(self) -> None:
        self.state, self.demos, self._rest = "cancelled", [], []
