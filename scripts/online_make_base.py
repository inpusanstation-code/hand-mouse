"""The base model that learning while using needs, made in one go: guided recordings -> data/online samples -> encoder.
(scripts/online_import.py, then scripts/online_train_base.py.) With --progress it prints one JSON object per line for the
app, which runs this by itself when a learning round is due and data/online has no base model (2026-11-11: in a fresh copy
of the project the card said "곧 학습" for good - data/ is not in git, so the base model made elsewhere was not there).

프로젝트 폴더에서:  .venv\\Scripts\\python.exe scripts/online_make_base.py
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[0] = str(ROOT)   # scripts/profile.py would hide the standard profile module that torch imports


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--progress", action="store_true")
    a = ap.parse_args(argv)

    def emit(event, **info):
        if a.progress:
            print(json.dumps({"event": event, **info}, ensure_ascii=False), flush=True)
        else:
            print(event, info, flush=True)

    t0 = time.perf_counter()
    try:
        from src.online.import_guided import import_recordings
        from src.online.samples import GUIDED_SCHEDULED, SampleStore
        from src.training_center import filter_selected_recording_paths
        emit("loading")
        paths = filter_selected_recording_paths([str(p) for p in sorted((ROOT / "recordings").glob("*.jsonl.gz"))])
        store = SampleStore()
        if paths:
            import_recordings(store, paths)
        guided = len(store.samples(sources=[GUIDED_SCHEDULED]))
        if not guided:
            emit("error", message="안내 녹화가 없어 기본 모델을 만들 수 없어요. 학습 센터에서 안내 녹화를 먼저 해 주세요.")
            return 1
        from scripts import online_train_base
        code = online_train_base.main()
        if code:
            emit("error", message="기본 모델 학습이 끝나지 못했어요.")
            return 1
        emit("done", status="base_built", samples=guided, seconds=round(time.perf_counter() - t0, 1))
        return 0
    except Exception as exc:
        emit("error", message=f"{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
