"""How the hand's commands went in everyday use, and what the watching models would have done, from logs/use_events.

    uv run --locked --extra qt --extra train --extra llm python scripts/use_event_report.py [--folder logs/use_events]

Per PC (never mixed) and per command: how often it ran and how many the person marked as "not meant" (F within 5 s, or pausing
right after). Then, for the rule commands a model knows, per watching model (the trained TCN / the model learned from this person):
how many marked ones it would have stopped and how many unmarked ones it would have stopped by mistake, and whether that earns it
the right to stop that command (src/use_gate.py; the app decides this by itself, with the model files in use). A wrong command
that was not marked counts as a meant one, so "stopped by mistake" is an upper bound and the marked share a lower bound.
The log itself is written by src/use_log.py.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import use_gate  # noqa: E402
from src.use_log import read_events  # noqa: E402

SOURCES = {"rule": "기본 동작", "binding": "연결한 명령", "registered": "등록한 동작", "pointer": "검지 포인터"}
MODELS = {"tcn": "기존 모델(TCN)", "online": "내 모델"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--folder", type=Path, default=ROOT / "logs" / "use_events")
    args = ap.parse_args(argv)
    events = read_events(args.folder, frames=False)
    if not events:
        print(f"아직 기록이 없어요: {args.folder}")
        print("앱을 쓰다가 원하지 않은 동작이 실행되면 바로 F를 누르세요 (5초 안).")
        return 0
    limits = use_gate.Limits()
    by_pc = defaultdict(list)
    for ev in events:
        by_pc[ev["pc"]].append(ev)
    for pc, items in sorted(by_pc.items()):
        files = sorted({ev["file"] for ev in items})
        marked = sum(bool(ev["marked"]) for ev in items)
        print(f"\n== {pc}  (기록 파일 {len(files)}개, 실행 {len(items)}번, 원하지 않음 표시 {marked}번)")
        counts = defaultdict(lambda: [0, 0])
        for ev in items:
            row = counts[(ev.get("source", ""), ev.get("key", ""))]
            row[0] += 1
            row[1] += bool(ev["marked"])
        print(f"  {'종류':8s} {'동작':28s} {'실행':>5s} {'표시':>5s}")
        for (source, key), (n, m) in sorted(counts.items(), key=lambda kv: -kv[1][0]):
            print(f"  {SOURCES.get(source, source):8s} {key:28s} {n:5d} {m:5d}")
        for kind, rows in use_gate.tally(items).items():       # every model version together: the app counts the current file only
            if not rows:
                continue
            print(f"  -- {MODELS[kind]}가 막았을 것 (표시한 것 / 표시 안 한 것)")
            for key, r in sorted(rows.items()):
                verdict = "→ 막을 자격 있음" if use_gate.earned(r, limits) else ""
                print(f"     {key:34s} {r['stop_marked']}/{r['marked']}  /  {r['stop_meant']}/{r['meant']}  {verdict}")
    current = use_gate.load(args.folder / "gate.json")
    print(f"\n자격 기준: 표시 {limits.min_marked}번 이상·표시 안 한 것 {limits.min_meant}번 이상, 표시한 것의 "
          f"{limits.min_stop_marked:.0%} 이상을 막고 표시 안 한 것은 {limits.max_stop_meant:.0%} 이하만 막을 것.")
    if current:
        print("지금 앱이 막고 있는 동작: " + ", ".join(f"{k} ({MODELS.get(v.get('model'), v.get('model'))})" for k, v in current.items()))
    else:
        print("지금 앱이 막고 있는 동작: 없음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
