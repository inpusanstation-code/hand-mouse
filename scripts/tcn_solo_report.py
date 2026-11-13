"""What the TCN would add if it could fire on its own ("rule OR model"), from the watch in logs/tcn_solo (src/tcn_solo.py).

    uv run --locked --extra qt --extra train --extra llm python scripts/tcn_solo_report.py [--folder logs/tcn_solo]

Per PC (never mixed), per hand mode and per gesture: how long the hand was watched with control on, how often the model confirmed
the gesture when the rules did too ("both"), when the rules caught it only a little later ("retry": the person tried again, so a
likely miss the model would have caught earlier, by `rule_dt` seconds), and when nothing followed ("alone": a miss the person gave
up on, or a misfire of the model alone; the log cannot tell them apart, so "alone" per minute is the upper bound of what firing on
its own would add as misfires). Nothing in the app acts on these numbers.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

NAMES = {"thumb_index": "엄지+검지", "thumb_middle": "엄지+중지", "thumb_ring": "엄지+약지", "thumb_pinky": "엄지+새끼",
         "palm_side": "손날"}
MODES = {"virtual": "가상 손", "palm": "손바닥"}


def read(folder: Path):
    """(minutes, solos, quiet stretches per mode) per PC. Reads the small index next to each file (no joints)."""
    minutes = defaultdict(list)
    solos = defaultdict(list)
    quiet = defaultdict(lambda: defaultdict(int))
    for path in sorted(Path(folder).glob("*.jsonl")):
        idx = path.with_suffix(".idx")
        source = idx if idx.is_file() else path
        pc = ""
        for line in source.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            kind = rec.get("type")
            if kind == "session":
                pc = rec.get("pc", "")
            elif kind == "minute":
                minutes[pc].append(rec)
            elif kind == "solo":
                solos[pc].append({**rec, "file": path.name})
            elif kind == "quiet":
                quiet[pc]["virtual" if rec.get("virtual") else "palm"] += 1
    return minutes, solos, quiet


def summary(minutes, solos):
    """{mode:label: {"both", "retry", "alone", "rule_dt": [...], "hand_s"}} for one PC, and hand seconds per mode."""
    rows = defaultdict(lambda: {"both": 0, "retry": 0, "alone": 0, "rule_dt": []})
    hand = defaultdict(float)
    for m in minutes:
        mode = "virtual" if m.get("virtual") else "palm"
        hand[mode] += float(m.get("hand_s") or 0.0)
        for key, counts in (m.get("counts") or {}).items():
            rows[key]["both"] += int(counts.get("both", 0))
    for s in solos:
        key = f"{'virtual' if s.get('virtual') else 'palm'}:{s.get('label')}"
        outcome = s.get("outcome")
        if outcome in ("retry", "alone"):
            rows[key][outcome] += 1
        if outcome == "retry" and s.get("rule_dt") is not None:
            rows[key]["rule_dt"].append(float(s["rule_dt"]))
    return rows, hand


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--folder", type=Path, default=ROOT / "logs" / "tcn_solo")
    args = ap.parse_args(argv)
    from src import use_review
    minutes, solos, quiet = read(args.folder)
    reviews = use_review.load(args.folder)
    if not minutes and not solos:
        print(f"아직 기록이 없어요: {args.folder}")
        print("마우스 제어를 켠 채 앱을 쓰면 TCN이 혼자 잡은 순간이 쌓여요(마우스 동작은 바뀌지 않음).")
        return 0
    for pc in sorted(set(minutes) | set(solos)):
        rows, hand = summary(minutes.get(pc, []), solos.get(pc, []))
        print(f"\n=== PC {pc or '?'} ===")
        for mode in ("virtual", "palm"):
            keys = sorted(k for k in rows if k.startswith(mode + ":"))
            mins = hand.get(mode, 0.0) / 60.0
            if not keys and mins <= 0:
                continue
            print(f"\n[{MODES[mode]} 모드] 손이 보인 시간 {mins:.1f}분")
            print(f"  {'동작':<8} {'함께':>5} {'다시 시도':>8} {'혼자':>5} {'다시/분':>7} {'혼자/분':>7} {'늦음(중앙)':>9}")
            for key in keys:
                r = rows[key]
                label = key.split(":", 1)[1]
                per = (lambda n: f"{n / mins:.2f}" if mins > 0 else "-")
                late = f"{statistics.median(r['rule_dt']):.2f}초" if r["rule_dt"] else "-"
                print(f"  {NAMES.get(label, label):<8} {r['both']:>5} {r['retry']:>8} {r['alone']:>5} "
                      f"{per(r['retry']):>7} {per(r['alone']):>7} {late:>9}")
            print(f"  모은 '아무것도 아님' (커서만 움직인 구간): {quiet.get(pc, {}).get(mode, 0)}개")
        retry = [s for s in solos.get(pc, []) if s.get("outcome") == "retry"]
        verdicts = [use_review.verdict(reviews, s["file"], s.get("id")) for s in retry]
        print(f"\n  다시 시도 검토: 통과 {verdicts.count('ok')} · 오탐지 {verdicts.count('bad')} · 안 봄 {verdicts.count('')}")
        print("\n  함께 = 규칙도 같은 순간에 실행 (TCN이 더해 주는 것 없음)")
        print("  다시 시도 = 규칙이 0.6~4초 뒤에야 실행: 놓쳤다가 다시 해서 된 것으로 보임 (TCN이 그만큼 먼저 잡았을 것)")
        print("  혼자 = 뒤에 아무것도 없음: 포기한 놓침이거나 TCN 단독의 오작동 (기록으로는 못 가름, 오작동의 상한)")
        if any(s.get("virtual") for s in solos.get(pc, [])):
            print("  가상 손: 이동 중 집기는 일부러 클릭이 아니라서, 그런 순간도 '혼자'로 잡혀요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
