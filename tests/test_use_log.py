"""Joints around every command and the TCN's shadow verdict (src/use_log.py, no camera)."""
import json
from types import SimpleNamespace

import numpy as np

from src.use_log import MARK_SECONDS, POST_SECONDS, PRE_SECONDS, UseLog, read_events, shadow_verdict


def hand():
    return SimpleNamespace(landmarks=[SimpleNamespace(x=.5, y=.5, z=0)] * 21, world=[[0.0, 0.0, 0.0]] * 21)


def feed(log, start, stop, probs=None):
    for i in range(int(start * 30), int(stop * 30)):
        log.frame(i / 30, hand(), probs)


def test_an_event_keeps_the_joints_before_and_after_it(tmp_path):
    log = UseLog(tmp_path, pc="pc-test", background=False)
    feed(log, 0, 5, [.1, .9])
    at = 149 / 30                                              # the last frame fed
    eid = log.event("rule", "right_click", at, label="thumb_ring", shadow={"would_pass": True})
    assert read_events(tmp_path) == []                         # still collecting what the hand does next
    feed(log, 5, 8, [.8, .2])
    (ev,) = read_events(tmp_path)
    ts = [f["t"] for f in ev["frames"]]
    assert ev["id"] == eid and ev["pc"] == "pc-test" and ev["marked"] == ""
    assert PRE_SECONDS - .05 <= at - ts[0] <= PRE_SECONDS + 1e-3
    assert POST_SECONDS - .05 <= ts[-1] - at <= POST_SECONDS + 1e-3
    assert ev["frames"][0]["p"] == [.1, .9] and ev["frames"][-1]["p"] == [.8, .2] and "world" in ev["frames"][0]
    assert json.loads(next(tmp_path.glob("*.jsonl")).read_text(encoding="utf-8").splitlines()[0])["type"] == "session"


def test_f_marks_only_the_last_recent_event_once_even_before_it_is_written(tmp_path):
    log = UseLog(tmp_path, background=False)
    feed(log, 0, 1)
    log.event("binding", "comp_a", .9)
    log.event("rule", "left_click", .95)
    assert log.mark_last(1.0, "f_key")["key"] == "left_click" and log.mark_last(1.1) is None
    assert log.mark_last(.95 + MARK_SECONDS + 1) is None
    log.close()                                               # the events come after the mark in the file
    marks = {ev["key"]: ev["marked"] for ev in read_events(tmp_path)}
    assert marks == {"comp_a": "", "left_click": "f_key"}


def test_the_worker_thread_writes_and_close_flushes(tmp_path):
    log = UseLog(tmp_path)
    feed(log, 0, 1)
    log.event("registered", "cut", .9)
    log.close()
    assert [ev["key"] for ev in read_events(tmp_path)] == ["cut"] and not log.dropped


def test_old_files_go_when_the_folder_is_over_its_size(tmp_path):
    (tmp_path / "20200101-000000-pc.jsonl").write_text("x" * 2_000_000, encoding="utf-8")
    log = UseLog(tmp_path, max_mb=1, background=False)
    log.event("rule", "left_click", 0.0)
    log.close()
    assert [p.name[:8] != "20200101" for p in tmp_path.glob("*.jsonl")] == [True]


class Gate:
    classes = ["none", "thumb_ring"]
    disabled_gestures = set()

    def __init__(self, ok):
        self.last = np.array([.3, .7])
        self.ok = ok
        self.quality_withheld = self.spatial_vetoed = self.ood_vetoed = self.spatial_boosted = 0
        self.last_rejection_reason, self.last_ood = "before", None

    def confirmed(self, name, now):
        self.quality_withheld += 1
        self.last_rejection_reason = "" if self.ok else "below_threshold"
        return self.ok


def test_the_shadow_verdict_leaves_the_gate_as_it_was():
    gate = Gate(ok=False)
    v = shadow_verdict(gate, "thumb_ring", 1.0)
    assert v["would_pass"] is False and v["reason"] == "below_threshold" and v["p"] == .7 and v["top"] == "thumb_ring"
    assert gate.quality_withheld == 0 and gate.last_rejection_reason == "before"
    assert "would_pass" not in shadow_verdict(gate, "comp_a", 1.0)      # a gesture the model does not know
    gate.last = None
    assert shadow_verdict(gate, "thumb_ring", 1.0) is None


def test_the_runtime_logs_a_shape_click_with_the_shadow_and_f_marks_it(tmp_path):
    from tests.test_virtual_hand import box_runtime, pinch_hand
    rt = box_runtime(tmp_path)

    class Shadow(Gate):
        classes = ["none", "thumb_index"]

        def step(self, now, hand, aspect):
            pass

        def reset(self):
            pass

    rt._watchers["tcn"] = Shadow(ok=False)
    rt._step()
    opened = pinch_hand(rt)
    rt._step(); rt._step()
    rt.tracker.hand[:] = opened
    rt._step()
    rt.post("key", ord("f"))
    rt._step()
    rt.use_log.close()
    (ev,) = read_events(tmp_path / "use_events")
    assert (ev["source"], ev["key"], ev["label"], ev["marked"]) == ("rule", "left_click", "thumb_index", "f_key")
    assert ev["virtual"] and not ev["gate_on"] and ev["shadow"]["would_pass"] is False
    assert ev["shadow"]["model"].startswith("tcn:") and ev["enforced"] == ""      # only watched: the click went out
    assert ev["frames"] and ev["frames"][-1]["p"] == [.3, .7]
    (light,) = read_events(tmp_path / "use_events", frames=False)                 # the index next to the file: no joints
    assert "frames" not in light and light["marked"] == "f_key" and light["shadow"] == ev["shadow"]


def test_the_report_counts_what_the_shadow_would_have_stopped(tmp_path, capsys):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("uer", Path(__file__).resolve().parents[1] / "scripts" / "use_event_report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    log = UseLog(tmp_path, pc="pc-test", background=False)
    log.frame(0.0, hand())
    log.event("rule", "right_click", .1, label="thumb_ring", shadow={"label": "thumb_ring", "would_pass": False})
    log.mark_last(.2)
    log.event("rule", "right_click", .3, label="thumb_ring", shadow={"label": "thumb_ring", "would_pass": True})
    log.event("binding", "comp_a", .4, shadow={"top": "none"})
    log.close()
    assert mod.main(["--folder", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "pc-test" in out and "right_click:thumb_ring" in out and "1/1  /  0/1" in out and "comp_a" in out
    assert "막고 있는 동작: 없음" in out
