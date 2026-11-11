"""The uses collected by themselves, shown in the training center's simulator (src/use_sim.py; no camera)."""
import time

import pytest

from src.use_log import UseLog
from src.use_sim import PREFIX, is_use_file, list_gestures, read_uses, simulate
from tests.test_use_learning import write_log


def test_the_selector_lists_taught_gestures_with_their_uses_and_marks(tmp_path):
    pytest.importorskip("torch")
    from tests.test_online_update import frames
    write_log(tmp_path / "use", frames, n_marked=1, n_meant=2, n_taught=5)      # rule commands and a sequence are not listed
    log = UseLog(tmp_path / "use", background=False)
    log._path = tmp_path / "use" / "20261112-000001-pc.jsonl"
    log.event("registered", "잘라내기", 1.0)
    log.event("binding", "comp_new", 2.0)
    log.mark_last(2.1)
    log.close()
    rows = list_gestures(tmp_path / "use", tmp_path / "online", {"comp_new": "옆따봉 유지"}.get)
    assert [(r["key"], r["uses"], r["marked"]) for r in rows] == [("comp_new", 6, 1), ("잘라내기", 1, 0)]
    assert rows[0]["file"] == PREFIX + "comp_new" and is_use_file(rows[0]["file"]) and not is_use_file("a.jsonl.gz")
    assert rows[0]["combo_label"] == "옆따봉 유지 · 사용 6번 (원하지 않음 1번) · 모으는 중"
    assert list_gestures(tmp_path / "none", tmp_path / "online") == []


def test_the_uses_play_as_repetitions_with_the_learning_stretch_and_the_marks(tmp_path):
    pytest.importorskip("torch")
    from tests.test_online_update import frames
    write_log(tmp_path / "use", frames, n_marked=0, n_meant=1, n_taught=4)
    log = UseLog(tmp_path / "use", background=False)
    log._path = next((tmp_path / "use").glob("*.jsonl"))
    log._next_id = 100
    log.frame(50.0, None)
    log.event("binding", "comp_new", 50.0, extra={"forced": True})
    log.mark_last(50.5)
    log.close()
    assert len(read_uses(tmp_path / "use", "comp_new")) == 5 and len(read_uses(tmp_path / "use", "comp_new", limit=2)) == 2
    res = simulate("comp_new", tmp_path / "use", tmp_path / "online", "옆따봉 유지")
    assert res["file"] == "use:comp_new" and res["use_view"] and not res["has_model"]
    assert "사용 사례 5번 (원하지 않음 표시 1번)" in res["summary"] and "확인 모델은 아직 없어요" in res["summary"]
    reps = res["reps"]
    assert [r["rep"] for r in reps] == [1, 2, 3, 4, 5] and reps[-1]["marked"] and not reps[-1]["rule_ok"]
    assert "원하지 않음 표시" in reps[-1]["name"] and "세 번째 시도" in reps[-1]["name"] and reps[0]["rule_ok"]
    frames_out = res["playback_frames"]
    assert len(frames_out) == res["frames"] > 100 and frames_out[0]["task_name"] == "옆따봉 유지"
    first = reps[0]
    inside = frames_out[first["start_frame"]]
    assert inside["zone"] == "judgment" and "정답" in inside["zone_ko"] and inside["event_text"] == "명령 실행 · 옆따봉 유지"
    assert inside["rep"] == 1 and len(inside["lm"]) == 21 and inside["target_name"].startswith("사용 #1")
    before = frames_out[first["start_frame"] - 5]
    assert before["zone"] == "transition" and before["zone_ko"] == "앞뒤 맥락" and "초 전" in before["phase_ko"]
    times = [f["t"] for f in frames_out]
    assert times == sorted(times)                                    # one clock for the player, use after use
    assert {b["zone"] for b in res["timeline"]} == {"judgment", "transition"} and res["gestures"][0]["reps"] == 4
    empty = simulate("comp_other", tmp_path / "use", tmp_path / "online")
    assert empty["frames"] == 0 and "아직 기록되지 않았어요" in empty["summary"]


def test_with_a_checking_model_its_probability_is_the_model_line(tmp_path):
    pytest.importorskip("torch")
    from src.online.verifier import train_verifiers
    from tests.test_online_update import fast, frames, make_root
    root, store = make_root(tmp_path)
    write_log(tmp_path / "use", frames, n_marked=0, n_meant=0, n_taught=20, name="20261111-000001-pc.jsonl")
    write_log(tmp_path / "use", frames, n_marked=0, n_meant=0, n_taught=6, name="20261112-000001-pc.jsonl")
    fast(root, use_events=tmp_path / "use")
    assert train_verifiers(root)["comp_new@down"]["status"] == "saved"
    rows = list_gestures(tmp_path / "use", root)
    assert rows[0]["uses"] == 26 and rows[0]["combo_label"].endswith("확인 모델 있음 (방향 1개)")
    res = simulate("comp_new", tmp_path / "use", root, "새 자세")
    assert res["has_model"] and "확인 모델(기준" in res["summary"] and res["gestures"][0]["trained"]
    assert sum(r["model_ok"] for r in res["reps"]) >= 20 and max(r["peak_prob"] for r in res["reps"]) > .9
    hit = res["playback_frames"][res["reps"][0]["end_frame"]]
    assert hit["model_cls"] == "comp_new" and hit["model_name"] == "새 자세" and 0 <= hit["model_prob"] <= 1


def test_the_training_center_lists_and_plays_them(tmp_path):
    pytest.importorskip("torch")
    from tests.test_online_runtime import dashboard as dashboard_fixture   # noqa: F401
    from tests.test_online_update import frames
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication

    from src.qt_dashboard import QtDashboard
    app = QApplication.instance() or QApplication([])
    QQuickStyle.setStyle("Basic")
    board = QtDashboard(dry_run=True)
    assert board.engine.rootObjects(), "dashboard.qml did not load"
    write_log(tmp_path / "use", frames, n_marked=0, n_meant=0, n_taught=3)
    board.auto_learn((0, str(tmp_path / "use")))                     # the runtime tells where its log is
    board.online_root = tmp_path / "online"
    board.refreshUseGestures()
    assert board.useGestures == []                                   # no such gesture (deleted): its old uses are not listed
    from src.action_bindings import get_action_registry
    get_action_registry().composite_gestures["comp_new"] = {"key": "comp_new", "name": "새 자세"}
    board.refreshUseGestures()
    assert [(g["key"], g["name"]) for g in board.useGestures] == [("comp_new", "새 자세")]
    board.runSimulation("use:comp_new", True)                        # the simulator's own buttons end up here too
    end = time.time() + 20
    while (board.training_busy or board.simPlaybackCount == 0) and time.time() < end:
        app.processEvents()
        time.sleep(.02)
    assert board.simPlaybackCount > 100 and board.simulationResult["use_view"] and board.selectedSimFile == "use:comp_new"
    assert len(board.simulationReps) == 3 and "사용 사례 3번" in board.simulationSummary
    assert board.getSimPlaybackFrame(10)["task_name"]
    app.processEvents()
