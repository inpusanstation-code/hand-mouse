"""Training center: advice per gesture, training progress parsing, focused recording, export package."""
import json
import zipfile

from src import training_center as tc
from src.guided_recording import TASKS, GuidedSession, tasks_for


def summary(reps=45, postures=3, minutes=9.5, newest=0.0):
    per = {k: {"reps": reps, "postures": {str(i): reps // postures for i in range(postures)}, "minutes": 0.0}
           for k in ("thumb_index", "thumb_ring")}
    per["none"] = {"reps": 0, "postures": {}, "minutes": minutes}
    return {"files": [], "per_gesture": per, "newest": newest}


def report(rate=0.9, misfires=0.2, mtime=100.0):
    g = {"rate": rate, "rules_rate": 0.5, "recognised": 27, "total": 30, "train_accuracy": 0.95}
    return {"mtime": mtime, "per_gesture": {
        "thumb_index": dict(g), "thumb_ring": dict(g),
        "none": {"misfires_per_min": misfires, "rules_misfires_per_min": 3.0, "train_accuracy": 0.99}}}


def rows_by_key(s, r):
    return {row["key"]: row for row in tc.gesture_rows(s, r)}


def test_enough_data_and_good_scores_say_ok():
    rows = rows_by_key(summary(), report())
    assert all(r["level"] == "ok" for r in rows.values())
    assert rows["thumb_ring"]["score_text"].startswith("인식 90%")


def test_low_recognition_asks_for_focused_recording():
    rows = rows_by_key(summary(), report(rate=0.6))
    assert rows["thumb_ring"]["level"] == "need"
    assert "집중 녹화" in rows["thumb_ring"]["advice"]


def test_little_data_and_one_posture_are_flagged():
    rows = rows_by_key(summary(reps=10, postures=1, minutes=2), None)
    assert rows["thumb_index"]["level"] == "need"
    assert "부족" in rows["thumb_index"]["advice"] and "자세" in rows["thumb_index"]["advice"]
    assert "부족" in rows["none"]["advice"]
    assert rows["thumb_index"]["score_text"] == "아직 평가 없음"


def test_many_misfires_ask_for_more_half_fist_moving():
    rows = rows_by_key(summary(), report(misfires=2.0))
    assert rows["none"]["level"] == "need"


def test_recordings_newer_than_the_model_ask_to_retrain():
    rows = rows_by_key(summary(newest=200.0), report(mtime=100.0))
    assert all(r["level"] == "retrain" for r in rows.values())


def test_training_progress_lines_move_the_bar():
    job = tc.TrainingJob()
    job.state = {"running": True, "fold": 0, "folds": 0, "epoch": 0, "epochs": 10, "progress": 0.0}
    job._apply({"event": "loaded", "folds": 3, "windows": 1000})
    job._apply({"event": "fold_start", "fold": 2, "folds": 3, "posture": 1})
    job._apply({"event": "epoch", "epoch": 5, "epochs": 10, "loss": 0.4})
    s = job.snapshot()
    assert 0.3 < s["progress"] < 0.5 and s["losses"] == [0.4] and "2/3" in s["stage"]
    job._apply({"event": "done", "per_gesture": {}})
    assert job.snapshot()["progress"] == 1.0


def test_focused_recording_has_only_that_gesture():
    assert tasks_for("thumb_ring") == tuple(t for t in TASKS if t.key == "thumb_ring")
    assert tasks_for("") == TASKS and tasks_for("unknown") == TASKS
    g = GuidedSession(tasks=tasks_for("thumb_ring"))
    assert {t.key for _, t in g.sets} == {"thumb_ring"} and len(g.sets) == 3   # one set per posture


def test_export_package_has_model_code_example_and_zip(tmp_path, monkeypatch):
    model = tmp_path / "gesture_tcn.onnx"
    model.write_bytes(b"onnx")
    model.with_suffix(".json").write_text(json.dumps({
        "trained": "2026-11-05", "classes": ["none", "thumb_index", "thumb_ring"], "window": 15, "features": 133,
        "feature_version": "local3d-v1", "threshold": 0.7, "frames_in_a_row": 3, "data": [],
        "per_gesture": report()["per_gesture"]}), encoding="utf-8")
    monkeypatch.setattr(tc, "MODEL", model)
    out = tc.export_package(tmp_path / "exports", with_dataset=False)
    names = {p.name for p in out.iterdir()}
    assert {"gesture_tcn.onnx", "gesture_tcn.json", "tcn_features.py", "example_use.py", "README.md"} <= names
    compile((out / "example_use.py").read_text(encoding="utf-8"), "example_use.py", "exec")
    with zipfile.ZipFile(str(out) + ".zip") as z:
        assert "example_use.py" in z.namelist()
