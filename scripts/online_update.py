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
    a = ap.parse_args(argv)

    def emit(event, **info):
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
        result = run_update(root, emit=emit, augment=lambda x: augment(x),
                            use_events=Path(a.use_events) if a.use_events else None, weak=not a.no_weak)
        if a.use_events:
            # each taught gesture's own checking model, from its uses (the production model above is not touched by this)
            from src.online.verifier import train_verifiers
            result["verifiers"] = train_verifiers(root, emit=emit)
        emit("done", **result)
        return 0
    except Exception as exc:     # the app shows it; production is untouched by a crash before submit
        emit("error", message=f"{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
