"""One background learning round: the person's confirmed/corrected samples -> candidate -> checks -> production or not.
With --progress it prints one JSON object per line for the app. --rollback puts the model before the last change back.

프로젝트 폴더에서 (GPU 환경이 있으면 그쪽 python):  python scripts/online_update.py
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[0] = str(ROOT)   # scripts/profile.py would hide the standard profile module that torch imports


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--progress", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    ap.add_argument("--root", default="")
    ap.add_argument("--use-events", default="", help="use log folder (logs/use_events): import its commands and learn from them too")
    ap.add_argument("--no-weak", action="store_true", help="with --use-events: only the commands marked as not meant")
    ap.add_argument("--require-review", action="store_true",
                    help="with --use-events: a taught gesture's use or a click is an example only once the person passed it")
    a = ap.parse_args(argv)

    from src.online import round_marker
    stages = round_marker.Stages()             # seconds per stage of this round (src/online/round_marker.py)

    def emit(event, **info):
        stage = round_marker.STAGE_OF_EVENT.get(event)
        if stage and stages.enter(stage) and a.use_events:
            round_marker.stage(root, stage)    # a round cut off later says where it was
        if a.progress:
            print(json.dumps({"event": event, **info}, ensure_ascii=False), flush=True)
        else:
            print(event, info, flush=True)

    from src.online.samples import DEFAULT_ROOT
    root = Path(a.root) if a.root else DEFAULT_ROOT
    try:
        if a.rollback:
            from src.online.versions import ModelManager
            emit("done", status="rolled_back" if ModelManager(root).rollback() else "nothing_to_roll_back")
            return 0
        from scripts.train_tcn import augment
        from src.online.update_job import run_update
        if a.use_events:
            # this round takes the collected uses out of the log first and saves only at its end: a mark says it is
            # under way, so a round cut off by closing the app is started again (src/online/round_marker.py)
            round_marker.begin(root)
        result = run_update(root, emit=emit, augment=lambda x: augment(x),
                            use_events=Path(a.use_events) if a.use_events else None, weak=not a.no_weak,
                            require_review=a.require_review)
        if a.use_events:
            # each taught gesture's own checking model, from its uses (the production model above is not touched by this)
            from src.online.verifier import train_verifiers
            if stages.enter("verifier"):
                round_marker.stage(root, "verifier")
            result["verifiers"] = train_verifiers(root, emit=emit)
            round_marker.end(root)             # everything is saved: finished, whether or not the app still listens
        timing = stages.result()               # where this round's time went (round_times.jsonl)
        round_marker.record(root, {**timing, "status": str(result.get("status", "")), "auto": bool(a.use_events)})
        result["timing"] = timing
        emit("done", **result)
        return 0
    except Exception as exc:     # the app shows it; production is untouched by a crash before submit
        # (the app closed = this print fails too: the mark stays and the round is started again with the app. A failure
        # of the round's own is shown by the app, and the mark goes so it is not tried over and over.)
        emit("error", message=f"{type(exc).__name__}: {exc}")
        if a.use_events:
            round_marker.end(root)
        round_marker.record(root, {**stages.result(), "status": "error", "auto": bool(a.use_events)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
