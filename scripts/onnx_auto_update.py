"""A candidate for models/gesture_tcn.onnx, trained from the guided recordings AND the uses collected while the app was
used (src/use_training.py). The app starts this by itself now and then (2026-11-12: "앱이 켜졌을 때 틈틈이 onnx를 …
자동으로 모은 수집 데이터를 가지고 알아서 학습"); nothing the app is using is touched: the candidate and a comparison
go to models/candidate/, and the person decides in the app whether it replaces the model ("내가 확인 후 교체").

  models/candidate/gesture_tcn.onnx, gesture_tcn.json   the candidate
  models/candidate/summary.json                         old and new model on the uses kept out of training, the
                                                        candidate's own held-out posture, classes, how long it took
  models/candidate/train.log                            what the training printed
  models/candidate_baseline/                            the same training WITHOUT the collected uses, checked the same
                                                        way: what the uses changed (kept while the recordings and the
                                                        training code stay the same, so it is trained once)

프로젝트 폴더에서:  .venv\\Scripts\\python.exe scripts/onnx_auto_update.py --use-events logs/use_events
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[0] = str(ROOT)   # scripts/profile.py would hide the standard profile module that torch imports

CANDIDATE_DIR = ROOT / "models" / "candidate"
SUMMARY = "summary.json"
RUNNING = "running.json"
BASELINE_DIR = ROOT / "models" / "candidate_baseline"
BASELINE_KEY = "key.json"


def baseline_key(mode: str, recordings: Path = ROOT / "recordings") -> dict:
    """What a baseline was trained from: the same recordings, training code and mode give the same baseline again."""
    from src.fold_cache import code_hash, recordings_key
    from src.recorder import finished_recordings
    return {"mode": mode, "code": code_hash(), "recordings": recordings_key(finished_recordings(recordings)[0])}


def baseline_ready(folder: Path, key: dict) -> bool:
    try:
        return ((folder / "gesture_tcn.onnx").is_file() and (folder / "gesture_tcn.json").is_file()
                and json.loads((folder / BASELINE_KEY).read_text(encoding="utf-8")) == json.loads(json.dumps(key)))
    except (OSError, ValueError):
        return False


def make_baseline(folder: Path, mode: str, run=subprocess.run) -> dict:
    """The model the same training gives without the collected uses, in `folder`. {"ok", "reused", "seconds"}.
    Not resumed (--resume would throw away the candidate's finished folds: one fold cache, one key)."""
    key = baseline_key(mode)
    if baseline_ready(folder, key):
        return {"ok": True, "reused": True, "seconds": 0.0}
    t0 = time.perf_counter()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / BASELINE_KEY).unlink(missing_ok=True)       # a half-trained baseline is never taken for a whole one
    command = [sys.executable, "-u", str(ROOT / "scripts" / "train_tcn.py"), "--mode", mode, "--output-dir", str(folder)]
    with open(folder / "train.log", "w", encoding="utf-8") as log:
        code = run(command, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
                   env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"}).returncode
    ok = not code and (folder / "gesture_tcn.onnx").is_file() and (folder / "gesture_tcn.json").is_file()
    if ok:
        (folder / BASELINE_KEY).write_text(json.dumps(key), encoding="utf-8")
    return {"ok": bool(ok), "reused": False, "seconds": round(time.perf_counter() - t0, 1)}


def _model_row(path: Path, items) -> dict:
    """One model for the summary: when it was trained, its classes, and how it does on the held-out uses."""
    from src.gesture_models import load_single
    from src.tcn_features import FEATURE_VERSION
    from src.use_training import score
    predict, info = load_single(path, FEATURE_VERSION)
    row = {"trained": str(info.get("trained", "")), "classes": list(info.get("classes") or []),
           "training_mode": str(info.get("training_mode", "")), "uses": score(predict, info, items)}
    gestures = {}
    for name, g in (info.get("per_gesture") or {}).items():
        if name == "none":
            row["misfires_per_min"] = g.get("misfires_per_min")
            row["rules_misfires_per_min"] = g.get("rules_misfires_per_min")
        elif g.get("zero_shot_total"):
            gestures[name] = {"rate": g.get("zero_shot_rate"), "total": g.get("zero_shot_total"), "rules_rate": g.get("rules_rate")}
    row["held_out_posture"] = gestures
    return row


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--progress", action="store_true")
    ap.add_argument("--use-events", default=str(ROOT / "logs" / "use_events"))
    ap.add_argument("--root", default="", help="online root (data/online): where the count of uses already trained on is kept")
    ap.add_argument("--out", default=str(CANDIDATE_DIR))
    ap.add_argument("--mode", default="fast")
    ap.add_argument("--baseline-dir", default=str(BASELINE_DIR))
    ap.add_argument("--no-baseline", action="store_true", help="do not train/compare the model without the collected uses")
    ap.add_argument("--compare-only", action="store_true", help="the candidate in --out is there already: only compare")
    a = ap.parse_args(argv)

    def emit(event, **info):
        if a.progress:
            print(json.dumps({"event": event, **info}, ensure_ascii=False), flush=True)
        else:
            print(event, info, flush=True)

    t0 = time.perf_counter()
    out = Path(a.out)
    try:
        from src.gesture_catalog import CLASSES
        from src.gesture_gate import DEFAULT_MODEL
        from src.online.samples import DEFAULT_ROOT
        from src.use_training import collect, counts, write_state
        root = Path(a.root) if a.root else DEFAULT_ROOT
        out.mkdir(parents=True, exist_ok=True)
        (out / SUMMARY).unlink(missing_ok=True)            # a half-made candidate is never offered
        # a mark while this runs: a training cut off by closing the app is started again with the app, and goes on
        # from the parts it had finished (QtRuntime._onnx_auto)
        (out / RUNNING).write_text(json.dumps({"pid": __import__("os").getpid(), "started": time.strftime("%Y-%m-%d %H:%M:%S")}),
                                   encoding="utf-8")
        used = counts(a.use_events, CLASSES)
        emit("onnx", stage="train", uses=used)
        command = [sys.executable, "-u", str(ROOT / "scripts" / "train_tcn.py"), "--mode", a.mode,
                   "--use-events", str(a.use_events), "--output-dir", str(out),
                   "--resume"]      # the parts an earlier, cut-off run finished are reused (logs/fold_cache)
        code = 0
        if not a.compare_only:
            with open(out / "train.log", "w", encoding="utf-8") as log:
                code = subprocess.run(command, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
                                      env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"}).returncode
        if code or not (out / "gesture_tcn.onnx").is_file():
            tail = (out / "train.log").read_text(encoding="utf-8", errors="replace").strip().splitlines()[-1:]
            emit("error", message="손짓 모델 후보 학습이 끝나지 못했어요" + (f": {tail[0][:200]}" if tail else ""))
            (out / RUNNING).unlink(missing_ok=True)      # a failure of its own: shown, not tried over and over
            return 1
        baseline = None
        if not a.no_baseline:
            # the same training without the collected uses: the only numbers of the held-out posture that can be put
            # next to the candidate's (the model in use was checked another way)
            if not a.compare_only or not baseline_ready(Path(a.baseline_dir), baseline_key(a.mode)):
                emit("onnx", stage="baseline")
            try:
                baseline = make_baseline(Path(a.baseline_dir), a.mode)
            except Exception as exc:
                baseline = {"ok": False, "reused": False, "seconds": 0.0, "error": f"{type(exc).__name__}: {exc}"}
        emit("onnx", stage="compare")
        candidate_info = json.loads((out / "gesture_tcn.json").read_text(encoding="utf-8"))
        items = collect(a.use_events, list(candidate_info.get("classes") or CLASSES))
        summary = {
            "created": time.strftime("%Y-%m-%d %H:%M:%S"), "seconds": round(time.perf_counter() - t0, 1),
            "uses": used, "trained_on": sum(not i["held"] for i in items), "held_out": sum(bool(i["held"]) for i in items),
            "candidate": _model_row(out / "gesture_tcn.onnx", items),
            "current": _model_row(Path(DEFAULT_MODEL), items) if Path(DEFAULT_MODEL).is_file() else None,
            "baseline": None,
        }
        if baseline is not None and baseline.get("ok"):
            summary["baseline"] = {**_model_row(Path(a.baseline_dir) / "gesture_tcn.onnx", items),
                                   "reused": bool(baseline["reused"]), "seconds": baseline["seconds"]}
        elif baseline is not None:
            summary["baseline_failed"] = baseline.get("error") or "training did not finish (models/candidate_baseline/train.log)"
        tmp = out / (SUMMARY + ".tmp")
        tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(out / SUMMARY)
        (out / RUNNING).unlink(missing_ok=True)
        write_state(root, {"events": int(sum(used.values())), "when": time.time(), "created": summary["created"]})
        emit("done", status="onnx_candidate", seconds=summary["seconds"], held_out=summary["held_out"])
        return 0
    except Exception as exc:
        emit("error", message=f"{type(exc).__name__}: {exc}")      # (the app closed: this fails too and the mark stays)
        (out / RUNNING).unlink(missing_ok=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
