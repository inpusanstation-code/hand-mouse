"""The collected uses of one taught gesture, for the main screen's [사례 보기] viewer (2026-11-11, user: "clicking it should show
the collected data the banner talks about, not jump to the dataset simulator").

`cases(folder, key)` reads that gesture's logged uses (src/use_log.py, the same ones the banner counts) and gives each one as
a short clip: the hand joints of the seconds around the command fitted into a square, the frame where the command ran, when
it was, and whether it was marked "not meant" (F). Read only: nothing is written or trained."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

FPS = 15                  # pictures a second in the viewer (the log has ~30)
MAX_CASES = 40            # newest uses shown
MARKS = {"f_key": "F로 '원하지 않음' 표시", "pause": "바로 일시정지 ('원하지 않음')"}


def _clip(event: Dict[str, Any]) -> Dict[str, Any]:
    from src.gesture_preview import fit
    t_fire = float(event.get("t", 0.0))
    raw = [(float(f.get("t", 0.0)), f.get("lm")) for f in event.get("frames") or []]
    raw = [(t, lm) for t, lm in raw if lm and len(lm) == 21]
    if not raw:
        return {"frames": [], "fire": 0, "before": 0.0, "after": 0.0}
    step = max(1, round(30 / FPS))
    kept = raw[::step]
    aspect = 720 / 1280
    pts = [[(p[0], p[1] * aspect) for p in lm] for _, lm in kept]
    fire = max((i for i, (t, _) in enumerate(kept) if t <= t_fire), default=0)
    return {"frames": fit(pts), "fire": fire, "before": round(t_fire - kept[0][0], 1), "after": round(kept[-1][0] - t_fire, 1)}


def cases(folder: Path | str, key: str, limit: int = MAX_CASES) -> List[Dict[str, Any]]:
    """Newest first: {"id", "when", "marked", "mark_text", "enforced", "frames", "fire", "before", "after"}."""
    from src.hand_direction import base, name, of_key
    from src.online.use_import import event_direction
    from src.use_sim import MAX_USES, read_uses
    want = of_key(key)                         # one direction of a taught gesture (2026-11-11): only those uses
    events = read_uses(folder, base(key), MAX_USES * 8 if want else limit)
    if want:
        events = [ev for ev in events if event_direction(ev) == want][-limit:]
    from src import use_review
    reviews = use_review.load(folder)
    for ev in events:
        ev["review"] = use_review.verdict(reviews, str(ev.get("file") or ""), ev.get("id"))
    return rows(reversed(events))


def rows(events) -> List[Dict[str, Any]]:
    """Logged uses as the viewer's rows, in the order given. "review": the person's verdict ("", "ok", "bad")."""
    from src.hand_direction import name
    from src.online.use_import import event_direction
    out = []
    for ev in events:
        clip = _clip(ev)
        marked = str(ev.get("marked") or "")
        out.append({"id": ev.get("id"), "when": str(ev.get("wall") or ""), "marked": bool(marked),
                    "mark_text": MARKS.get(marked, "원하지 않음 표시" if marked else ""),
                    "enforced": str(ev.get("enforced") or ""), "file": str(ev.get("file") or ""),
                    "review": str(ev.get("review") or ""),
                    "direction": name(event_direction(ev)), **clip})
    return out


def review_cases(folder: Path | str, root: Path | str, key: str) -> List[Dict[str, Any]]:
    """The review session's rows (src/use_review.py): this gesture's uses no learning round has taken yet, oldest first."""
    from src.use_review import waiting
    return rows(waiting(folder, root, key))
