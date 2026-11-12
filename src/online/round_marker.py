"""A learning round from the use log that did not reach its end (2026-11-11, "앱을 끄면 학습 멈췄다가 다시 켜면 … 다시 학습
시작하는 거지?").

A round takes the collected uses out of the log at its very start (src/online/use_import.py marks them as taken) and saves
what it learned only at its end. Closing the app in between left the uses in the sample store with nothing learned from
them, and nothing asked for another round until the gesture had been used twenty more times.

The round now leaves a mark while it runs (<online root>/round_running.json: when it started, its process, how many times
it was tried) and takes it away when it has finished - also when it failed for a reason of its own, which the app shows.
A mark found when the app starts, whose process is gone, means a round was cut off: the app asks for one more round
(QtRuntime._use_auto), which learns from the samples already taken. It starts from the beginning of the round, not from
the middle: nothing is saved in between. After MAX_TRIES cut-off rounds in a row the app stops asking.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict

FILE = "round_running.json"
MAX_TRIES = 3


def read(root: Path | str) -> Dict[str, Any]:
    try:
        doc = json.loads((Path(root) / FILE).read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def begin(root: Path | str) -> None:
    root = Path(root)
    tries = int(read(root).get("tries", 0)) + 1
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / (FILE + ".tmp")
    now = time.time()
    tmp.write_text(json.dumps({"started": time.strftime("%Y-%m-%d %H:%M:%S"), "pid": os.getpid(), "tries": tries,
                               "t0": now, "at": now, "stage": "import"}), encoding="utf-8")
    tmp.replace(root / FILE)


def end(root: Path | str) -> None:
    try:
        (Path(root) / FILE).unlink()
    except OSError:
        pass


def _alive(pid: int) -> bool:
    """Is that process still running? (Windows; elsewhere a signal 0.)"""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            handle = k.OpenProcess(0x1000, False, int(pid))          # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return False
            try:
                code = ctypes.c_ulong(0)
                return bool(k.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259      # STILL_ACTIVE
            finally:
                k.CloseHandle(handle)
        except Exception:
            return False
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def unfinished(root: Path | str) -> bool:
    """A round was cut off and is worth one more try: its mark is there, its process is gone, and it was not tried
    MAX_TRIES times already."""
    mark = read(root)
    if not mark:
        return False
    return int(mark.get("tries", 0)) < MAX_TRIES and not _alive(int(mark.get("pid", 0) or 0))


# ---------------------------------------------------------------------------- how long a round takes, stage by stage
# 2026-11-11 ("소요 시간 기록 넣어 줘. 그리고 중간 저장이 필요하다는 판단도 앱이 하게 해줘"). Whether saving in the middle of
# a round would help depends on where its time goes, and nothing had measured that:
#   import   taking the collected uses out of the log
#   prepare  loading the recordings and the person's samples (done again after any restart)
#   update   the model's update steps            } the only stages a saved middle could shorten
#   verifier each taught gesture's checking model }
#   check    old and new model compared on the held-out sessions (done again after any restart)
# Every round appends one line to <online root>/round_times.jsonl: finished ones with the seconds of each stage, cut-off
# ones (noticed when the app starts again) with the stage they were in and how long they had run.
TIMES_FILE = "round_times.jsonl"
STAGES = ("import", "prepare", "update", "check", "verifier")
STAGE_OF_EVENT = {"imported": "prepare", "loading": "prepare", "update": "update", "checking": "check", "verifier": "verifier"}
RESUMABLE = ("update", "verifier")
LOOK_BACK = 6            # rounds the judgement looks at
CUTS_NEEDED = 2          # cut-off rounds among them before anything is said
SHORT_ROUND = 90.0       # s: a round this short only needs the app left open that long
RESUMABLE_SHARE = .5     # of a round's time in the stages a saved middle could shorten: worth saving in the middle


class Stages:
    """Seconds spent in each stage of one round (a stage entered twice adds up)."""

    def __init__(self, clock=time.perf_counter) -> None:
        self.clock = clock
        self.started = clock()
        self.current, self.since = "import", self.started
        self.seconds: Dict[str, float] = {}

    def enter(self, stage: str) -> bool:
        """True when the stage changed."""
        if stage == self.current:
            return False
        now = self.clock()
        self.seconds[self.current] = self.seconds.get(self.current, 0.0) + now - self.since
        self.current, self.since = stage, now
        return True

    def result(self) -> Dict[str, Any]:
        now = self.clock()
        seconds = dict(self.seconds)
        seconds[self.current] = seconds.get(self.current, 0.0) + now - self.since
        return {"seconds": round(now - self.started, 1), "stages": {k: round(v, 1) for k, v in seconds.items()}}


def stage(root: Path | str, name: str) -> None:
    """The running round is in this stage now (kept in its mark, so a cut-off round says where it was)."""
    root = Path(root)
    mark = read(root)
    if not mark:
        return
    mark.update(stage=name, at=time.time())
    try:
        tmp = root / (FILE + ".tmp")
        tmp.write_text(json.dumps(mark), encoding="utf-8")
        tmp.replace(root / FILE)
    except OSError:
        pass


def record(root: Path | str, entry: Dict[str, Any]) -> None:
    try:
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        with (root / TIMES_FILE).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"when": time.strftime("%Y-%m-%d %H:%M:%S"), **entry}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def records(root: Path | str) -> list:
    out = []
    try:
        for line in (Path(root) / TIMES_FILE).read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict):
                out.append(rec)
    except OSError:
        pass
    return out


def note_cut(root: Path | str) -> bool:
    """A mark whose process is gone is a round that was cut off: written to the times file once (True then)."""
    root = Path(root)
    mark = read(root)
    if not mark or mark.get("noted") or _alive(int(mark.get("pid", 0) or 0)):
        return False
    ran = None
    if mark.get("at") and mark.get("t0"):
        ran = round(float(mark["at"]) - float(mark["t0"]), 1)
    record(root, {"cut": True, "stage": str(mark.get("stage") or "import"), "seconds": ran, "tries": int(mark.get("tries", 1))})
    mark["noted"] = True
    try:
        (root / FILE).write_text(json.dumps(mark), encoding="utf-8")
    except OSError:
        pass
    return True


def _median(values) -> float:
    values = sorted(values)
    return values[len(values) // 2] if values else 0.0


def advice(root: Path | str) -> Dict[str, Any]:
    """The app's own judgement from the last LOOK_BACK rounds: {} while fewer than CUTS_NEEDED of them were cut off, else
    {"kind", "text", ...} with kind

        "keep_open"   a round is short: leaving the app open that long is enough, no saving in the middle
        "checkpoint"  most of a round is update steps: saving in the middle would help
        "cache"       most of a round is preparing and checking, which a saved middle repeats anyway: keeping the
                      prepared data would help instead
        "unknown"     no round has finished yet, so where the time goes is not known

    The limits (SHORT_ROUND, RESUMABLE_SHARE, CUTS_NEEDED) are starting points, not measured."""
    everything = records(root)
    recent = everything[-LOOK_BACK:]
    cuts = [r for r in recent if r.get("cut")]
    if len(cuts) < CUTS_NEEDED:
        return {}
    done = [r for r in everything if not r.get("cut") and r.get("status") != "error" and isinstance(r.get("stages"), dict)]
    done = done[-LOOK_BACK:]
    out: Dict[str, Any] = {"cuts": len(cuts), "rounds": len(recent)}
    how_often = f"최근 {len(recent)}번 중 {len(cuts)}번"
    if not done:
        longest = max((float(c.get("seconds") or 0.0) for c in cuts), default=0.0)
        return {**out, "kind": "unknown",
                "text": f"TCN 학습이 끝나기 전에 앱이 꺼졌어요 ({how_often}, 가장 오래 간 것 {longest:.0f}초)."
                        " 아직 끝까지 간 학습이 없어 얼마나 걸리는지 몰라요. 첫 화면의 '자동 학습' 줄이 사라질 때까지 한 번만 켜 두세요."}
    total = _median([float(r.get("seconds") or 0.0) for r in done])
    part = {s: _median([float((r["stages"] or {}).get(s, 0.0)) for r in done]) for s in STAGES}
    resumable = sum(part[s] for s in RESUMABLE)
    out.update(seconds=round(total, 1), stages={k: round(v, 1) for k, v in part.items()}, resumable=round(resumable, 1))
    if total < SHORT_ROUND:
        return {**out, "kind": "keep_open",
                "text": f"TCN 학습이 끝나기 전에 앱이 꺼졌어요 ({how_often}). 한 번에 약 {total:.0f}초면 끝나니 중간 저장은 필요 없고,"
                        " 첫 화면의 '자동 학습' 줄이 사라질 때까지만 켜 두면 돼요."}
    if resumable >= RESUMABLE_SHARE * total:
        return {**out, "kind": "checkpoint",
                "text": f"TCN 학습 중간 저장이 필요해 보여요: 한 번에 약 {total:.0f}초가 걸리고 그중 {resumable:.0f}초가 이어서 할 수 있는"
                        f" 갱신 단계인데, {how_often}이 끝나기 전에 꺼졌어요."}
    return {**out, "kind": "cache",
            "text": f"TCN 학습이 자주 끊겨요 ({how_often}, 한 번에 약 {total:.0f}초). 시간의 대부분이 자료 준비·검사"
                    f"({total - resumable:.0f}초)라 중간 저장보다 준비한 자료를 저장해 두는 쪽이 맞아요."}
