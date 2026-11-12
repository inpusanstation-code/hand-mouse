"""A dial on the other hand for YouTube's playback speed (2026-11-12, "노즐 컨트롤 형식 … 엄지검지 탭하면 손위로 호(곡선)
모양의 게이지가 손을 따라 나오고 손을 돌리는 각도에 따라 배속을 조절").

  on     a thumb + index pinch of the other hand held HOLD s
  turn   every STEP_DEG of turn (wrist -> middle knuckle on the screen) counter-clockwise is one speed step (.25x)
         faster, clockwise one slower (DIRECTION; the other way round until 2026-11-12), MIN .. MAX_SPEED; it opens on the speed it was closed on (`known_speed`)
  off    a fist (FIST_FRAMES frames), only that (2026-11-12, user: "주먹을 쥐면 종료 … 주먹으로 종료하기 전까지는 게이지가
         이유없이 없어지지 않게"): not the hand out of view, not idling, not the hand moving aside, not the pinch again

On the control hand a thumb + index tap is the left click, so the dial is the other hand's (src/other_hand_motion.py).
Speeds (user, 2026-11-12: "배속은 0.75~2.5까지"): YouTube's keys (Shift+> / Shift+<) go .25 .. 2 in .25 steps and stop at 2,
so the dial runs .75 .. 2 (2.25 / 2.5 cannot be reached by keys). YouTube does not tell its speed: on the first turn of a
dial session the caller presses "slower" down to .25 and then "faster" up to the dial's speed (`sync_keys`); from then on
the speed shown is the real one.
Pure logic: the caller sends the keys (only to a YouTube window) and draws the gauge (dashboard.qml `otherHandWindow`).

A second kind (same day, "엄지중지 pinch하면 이제 같은 호밸브에 -+5 -+10 씩 조절"): `SpeedDial("seek")` opens on a
thumb + middle tap and every STEP_DEG is SEEK_STEP seconds from where the hand was at the tap, SEEK_MIN .. SEEK_MAX steps.
Turning only sets the amount; a thumb + index pinch while it is open sends it, each pinch again (user: "특정 숫자에 놓고
엄지검지를 pinch하면 해당 숫자만큼 … 연속으로 pinch하면 연속으로 실행", QtRuntime._speed_dial_step).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

from src.motion_mode import hand_features
from src.virtual_hand import ShapePinch

TAP_MAX = .45       # s from closing to opening that makes a tap (the seek dial's "go")
HOLD = .4           # s a pinch is held to open or close a dial (2026-11-12: a tap opened the seek dial 1.6 times a minute
                    # in passing - touches of .03-.2 s - a .4 s hold once in 15 minutes; user chose the hold)
STEP_DEG = 12.0     # degrees of turn per step (20 until 2026-11-12, "게이지가 너무 넓어서 번거로우니까 길이를 줄여"): the
                    # speed dial's whole range is 60 degrees of wrist turn (was 100), the seek dial's 96 (was 160)
HYST = .35          # of a step: a step is taken past the middle between two steps by HYST/2 (no flicker at an edge)
BASE = 1.0          # the speed at the dial's zero
SPEED_STEP = .25    # YouTube's step
MIN_SPEED, MAX_SPEED = .75, 2.0
YT_FLOOR, YT_TOP = .25, 2.0   # what YouTube's keys reach
SEEK_STEP = 5       # seconds per step of the seek dial
SEEK_MIN, SEEK_MAX = -4, 4    # -20 s .. +20 s
MIN_STEPS = round((MIN_SPEED - BASE) / SPEED_STEP)   # -1
MAX_STEPS = round((MAX_SPEED - BASE) / SPEED_STEP)   # +4
FIST = 1.1          # a fist closes a dial: every finger's curl (motion_mode.hand_features) under this ...
FIST_FRAMES = 5     # ... this many frames running (that day's left-hand logs: 495 of 19,582 frames under 1.1)
TURN_FREEZE = 3     # fingers curled under OK_FINGERS: the hand is closing into the fist, its turn is not read
UNDO_S = .4         # s before a closing fist whose steps are given back (the hand turns a little as it curls) ...
CURLING = 1.45      # ... taken with at least TURN_FREEZE fingers under this curl (left-hand logs: 4-10 % of OK-like
                    # hands with three fingers out are under it; 1.6 caught 17 %)
OK_FINGERS = 1.2    # the tap is an OK sign: middle, ring and little finger out (curl ratio, motion_mode.hand_features)
TRAVEL = .12        # frame widths the palm moves within TRAVEL_S without a step: a swipe begun, the dial gives way
TRAVEL_S = .4
# Accidental openings: the .4 s hold (HOLD) opened a dial about once in 15 minutes of that day's left hand. Such a dial now
# stays until a fist (it used to close itself after 3 s or when the hand moved aside); opening sends nothing.


def tilt(landmarks: Sequence[Any], width: int, height: int) -> float:
    """The hand's tilt on the screen, degrees clockwise from straight up (wrist -> middle knuckle)."""
    w, m = landmarks[0], landmarks[9]
    dx, dy = (m.x - w.x) * width, (m.y - w.y) * height
    return math.degrees(math.atan2(dx, -dy))


FINGER_INDEX = {"index": 0, "middle": 1, "ring": 2, "pinky": 3}
# The dial's middle is the hand at 11 o'clock, not where the hand was at the tap (2026-11-12, user: "손을 위로 올렸을때
# 11시방향이 가운데 점이 되게 … 왼손이라 왼쪽으로 돌리긴 쉬운데, 오른쪽으로 손목을 돌리기가 힘들다"): the speed is where
# the hand points (11 o'clock = 1x); the seek dial counts from the tap but sits round 11 o'clock too.
CENTER_TILT = -30.0     # degrees from straight up (- = to the left): 11 o'clock
# Which way is "more" (2026-11-12, user: "왼손 다이얼 컨트롤 값 둘다를 좌우를 바꿔줘. 자주 쓰는 값을 왼쪽으로"): -1 = turning
# counter-clockwise (to the left, the easy way for the left hand) is faster / forward; clockwise slower / back. The
# ranges are lopsided the same way (speed -1 .. +4 steps), so the long side is now the easy side.
DIRECTION = -1


class SpeedDial:
    def __init__(self, kind: str = "speed") -> None:
        self.kind = kind
        self.finger = "middle" if kind == "seek" else "index"
        self.lo, self.hi = (SEEK_MIN, SEEK_MAX) if kind == "seek" else (MIN_STEPS, MAX_STEPS)
        self.pinch = ShapePinch(self.finger)
        self.active = False
        self.steps = 0
        self.synced = False           # this session's speed was set from YouTube's floor (sync_keys), so speed() is real
        self.turn = 0.0               # degrees from the dial's middle (CENTER_TILT), + = towards "more" (DIRECTION)
        self.origin = 0               # the steps the hand was at when the dial opened (the seek dial counts from there)
        # YouTube's speed when the app knows it (set by the caller): YouTube's seek keys move "10 s" x the playback speed
        # (checked on youtube.com 2026-11-12: L moved 10 s at 1x, 20 s at 2x, the overlay still "+10")
        self.rate_hint: Optional[float] = None
        self.known_speed: Optional[float] = None   # YouTube's speed when the app set it last: the speed dial opens there
        self._fist = 0                   # fist frames running
        self._recent: List = []          # (t, net steps) of the last UNDO_S: undone when a fist closes the dial
        self._resume = False             # the hand came back after a dropout: its turn starts again from here
        self._zero = 0.0
        self._last_tilt = 0.0
        self._down_at: Optional[float] = None
        self._held = False
        self._seen_at = -1e9
        self._changed_at = 0.0
        self._palms: List = []           # (t, palm x) of the last TRAVEL_S while on
        self._start_steps, self._used = 0, False   # the steps at opening, and whether it was used (turned or fired)

    def reset(self) -> None:
        self.__init__(self.kind)

    def close(self) -> None:
        self.active = False

    def touch(self, now: float) -> None:
        """Something was done with the dial (the seek dial fired): it does not close for IDLE from now."""
        self._changed_at = now
        self._used = True

    def seconds(self) -> int:
        """The seek dial's amount, where the hand points: 11 o'clock = 0 s (2026-11-12: it counted from where the hand was
        when the dial opened, so the big number and the arc's "+20초" end did not agree; nothing is sent until a pinch, so
        the hand's direction can be the amount)."""
        return self.steps * SEEK_STEP

    @property
    def changed_at(self) -> float:
        return self._changed_at

    def speed(self) -> float:
        return BASE + self.steps * SPEED_STEP

    def sync_keys(self) -> tuple:
        """(slower presses, faster presses) that put YouTube on this dial's speed whatever it was: down to the floor, up."""
        down = round((YT_TOP - YT_FLOOR) / SPEED_STEP)
        return down, round((self.speed() - YT_FLOOR) / SPEED_STEP)

    def view(self) -> Optional[Dict[str, Any]]:
        """What the gauge draws: the steps, the turn, the range, and its words."""
        if not self.active:
            return None
        base = {"kind": self.kind, "steps": self.steps, "turn": round(self.turn, 1), "step_deg": STEP_DEG,
                "min": self.lo, "max": self.hi}
        base["center"] = CENTER_TILT
        base["dir"] = DIRECTION
        base["from"] = self.origin if self.kind == "seek" else 0
        if self.kind == "seek":
            moved = self.seconds()
            caption = "돌려서 정하고 · 엄지+검지 집으면 이동"
            if moved and self.rate_hint and abs(self.rate_hint - 1.0) > 1e-6:
                caption = f"{self.rate_hint:g}배속이라 실제 {moved * self.rate_hint:+g}초 · 엄지+검지 집으면 이동"
            return {**base, "label": f"{moved:+d}초" if moved else "0초",
                    "caption": caption,
                    "lo_text": f"{self.lo * SEEK_STEP}초", "hi_text": f"+{self.hi * SEEK_STEP}초"}

        def fmt(v):
            return f"{v:g}×"
        return {**base, "label": fmt(self.speed()), "caption": "배속" if self.synced else "배속 · 돌리면 이 값으로 맞춰요",
                "lo_text": fmt(BASE + self.lo * SPEED_STEP), "hi_text": fmt(BASE + self.hi * SPEED_STEP)}

    def step(self, now: float, landmarks: Optional[Sequence[Any]], width: int = 1280, height: int = 720) -> List[str]:
        """Events of this frame: "on" (the pinch held HOLD s), "off" (a fist), "press" (the pinch closed: the seek dial's
        "go" when it comes from the thumb + index), "tap" (a short pinch, closed under TAP_MAX s), "faster", "slower"
        (one per step)."""
        out: List[str] = []
        if landmarks is None or len(landmarks) != 21:
            self.pinch.reset()
            self._down_at = None
            self._fist = 0
            self._resume = self.active          # the dial stays; the turn goes on from where the hand comes back
            return out
        self._seen_at = now
        a = tilt(landmarks, width, height)
        curl = hand_features(landmarks)["curl"]
        if self.active:
            self._fist = self._fist + 1 if max(curl) < FIST else 0
            if self._fist >= FIST_FRAMES:
                self.active, self._fist = False, 0
                self.pinch.reset()
                self._down_at = None
                # steps taken while the hand was closing (it turns a little as it curls) are given back first
                back = sum(k for t, k in self._recent if now - t <= UNDO_S)
                self._recent = []
                self.steps -= back
                return (["slower"] * back if back > 0 else ["faster"] * -back) + ["off"]
        ev = self.pinch.step(landmarks, width, height)
        tapped = False
        others = [c for i, c in enumerate(curl) if i != FINGER_INDEX[self.finger]] if ev == "down" else []
        if ev == "down" and min(others) < OK_FINGERS:
            self.pinch.reset()                     # thumb on index with the other fingers curled: not the OK-sign tap
            ev = None
        held = False
        if ev == "down":
            self._down_at, self._held = now, False
            out.append("press")
        elif ev == "up":
            tapped = self._down_at is not None and not self._held and now - self._down_at <= TAP_MAX
            self._down_at = None
        elif self.pinch.closed and self._down_at is not None and not self._held and now - self._down_at >= HOLD:
            held = self._held = True             # once per press: letting go afterwards does nothing
        if tapped:
            out.append("tap")
        if held and self.active:
            held = False                         # holding the pinch again does not close it (only a fist does)
        if held:
            self.active, self.synced, self._fist, self._resume = True, False, 0, False
            if self.kind == "seek":
                self.turn = DIRECTION * ((a - CENTER_TILT + 180.0) % 360.0 - 180.0)
                self.steps = max(self.lo, min(self.hi, round(self.turn / STEP_DEG)))   # where the hand points (no event)
            else:
                # the speed it was closed on (2026-11-12: "주먹으로 종료한 배속을 계속 적용"), turned from here; 1x until
                # the app has set one (then the first turn sets YouTube to the dial)
                known = self.known_speed
                self.steps = (max(self.lo, min(self.hi, round((known - BASE) / SPEED_STEP))) if known is not None else 0)
                self.synced = known is not None
                self.turn = self.steps * STEP_DEG
            self.origin = 0
            self._start_steps, self._used = self.steps, False
            self._zero = self._last_tilt = a
            self._changed_at = now
            self._palms = []
            return ["on"]
        if not self.active:
            return out
        if self._resume or sum(1 for c in curl if c < OK_FINGERS) >= TURN_FREEZE:
            # back after a dropout (the hand may have turned meanwhile), or closing into the fist: no step from this
            self._resume = False
            self._last_tilt = a
            return out
        # the turn from the zero, unwrapped (a hand turned past straight down does not jump by 360)
        d = DIRECTION * ((a - self._last_tilt + 180.0) % 360.0 - 180.0)
        self._last_tilt = a
        self.turn += d
        want = self.turn / STEP_DEG
        edge = .5 + HYST / 2          # past the middle between two steps by half of HYST: no flicker at the edge
        while self.steps < self.hi and want >= self.steps + edge:
            self.steps += 1
            out.append("faster")
        while self.steps > self.lo and want <= self.steps - edge:
            self.steps -= 1
            out.append("slower")
        if out:
            self._changed_at = now
            n = out.count("faster") - out.count("slower")
            # kept for the undo only when the fingers were already curling (a step turned on purpose, then a quick fist,
            # stays)
            if n and sum(1 for c in curl if c < CURLING) >= TURN_FREEZE:
                self._recent = [(t, k) for t, k in self._recent if now - t <= UNDO_S] + [(now, n)]
        return out
