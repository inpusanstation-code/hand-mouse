"""The TCN-alone watch (src/tcn_solo.py): moments the model confirms and the rules did not act on, sorted by what followed."""
from __future__ import annotations

import json

from scripts import tcn_solo_report
from src.tcn_solo import SoloWatch
from src.use_log import UseLog

FPS = 30.0


class FakeWatcher:
    """Confirms `label` while `now` is inside one of `spans`."""

    def __init__(self, spans, label="thumb_index"):
        self.classes = ["none", "thumb_index", "thumb_middle"]
        self.disabled_gestures = set()
        self.last = [0.1, 0.8, 0.1]
        self.last_rejection_reason = ""
        self.spans = spans
        self.label = label

    def confirmed(self, label, now):
        return label == self.label and any(a <= now < b for a, b in self.spans)


def run(watch, watcher, seconds, rules=(), virtual=True, busy=None):
    out = []
    rules = sorted(rules)
    frames = []
    n = int(seconds * FPS)
    for i in range(n):
        t = i / FPS
        while rules and rules[0] <= t:
            watch.rule(rules.pop(0), "thumb_index")
        frames.append({"t": t})
        frames = [f for f in frames if t - f["t"] <= 3.0]
        watch.step(t, watcher, frames, hand=True, virtual=virtual, busy=(busy(t) if busy else ()))
    watch.close(n / FPS)
    return out


def collect():
    recs = []
    return recs, recs.append


def test_a_moment_the_rules_also_caught_is_only_counted():
    recs, put = collect()
    watch = SoloWatch(put)
    run(watch, FakeWatcher([(2.0, 2.4)]), 8.0, rules=[1.9])
    assert [r for r in recs if r["type"] == "solo"] == []
    minute = [r for r in recs if r["type"] == "minute"][-1]
    assert minute["counts"]["virtual:thumb_index"] == {"both": 1}


def test_the_rules_catching_it_seconds_later_is_a_retry_with_its_delay():
    recs, put = collect()
    watch = SoloWatch(put)
    run(watch, FakeWatcher([(2.0, 2.3)]), 9.0, rules=[4.0])
    solo = [r for r in recs if r["type"] == "solo"]
    assert len(solo) == 1 and solo[0]["outcome"] == "retry"
    assert abs(solo[0]["rule_dt"] - 2.0) < 0.05
    # the joints around it are kept: 3 s before (as far as there were frames) and 2 s after
    ts = [f["t"] for f in solo[0]["frames"]]
    assert min(ts) <= 0.05 and 3.9 <= max(ts) <= 4.05


def test_nothing_following_is_alone():
    recs, put = collect()
    watch = SoloWatch(put)
    run(watch, FakeWatcher([(2.0, 2.3)]), 9.0)
    solo = [r for r in recs if r["type"] == "solo"]
    assert [s["outcome"] for s in solo] == ["alone"]


def test_the_model_seeing_a_grab_that_goes_on_is_not_a_new_moment():
    recs, put = collect()
    watch = SoloWatch(put)
    # a drag from 1.0 to 6.0; the model lets go and catches it again in the middle of it
    run(watch, FakeWatcher([(1.0, 3.0), (3.5, 6.0)]), 12.0, rules=[0.9],
        busy=lambda t: {"thumb_index"} if 0.95 <= t < 6.0 else set())
    assert [r for r in recs if r["type"] == "solo"] == []


def test_a_short_let_go_is_the_same_moment():
    recs, put = collect()
    watch = SoloWatch(put)
    run(watch, FakeWatcher([(2.0, 2.3), (2.35, 2.6)]), 9.0)
    assert len([r for r in recs if r["type"] == "solo"]) == 1


def test_palm_mode_watches_its_own_gestures_only():
    recs, put = collect()
    watch = SoloWatch(put)
    run(watch, FakeWatcher([(2.0, 2.3)], label="thumb_middle"), 9.0, virtual=True)
    assert [r for r in recs if r["type"] == "solo"] == []          # thumb + middle is not a virtual hand gesture
    recs2, put2 = collect()
    watch2 = SoloWatch(put2)
    run(watch2, FakeWatcher([(2.0, 2.3)], label="thumb_middle"), 9.0, virtual=False)
    solo = [r for r in recs2 if r["type"] == "solo"]
    assert len(solo) == 1 and solo[0]["label"] == "thumb_middle" and solo[0]["virtual"] is False


def test_pausing_drops_open_moments():
    recs, put = collect()
    watch = SoloWatch(put)
    watcher = FakeWatcher([(1.0, 1.3)])
    for i in range(int(1.5 * FPS)):
        watch.step(i / FPS, watcher, [], hand=True, virtual=True)
    watch.pause(1.5)
    for i in range(int(1.5 * FPS), int(9 * FPS)):
        watch.step(i / FPS, watcher, [], hand=True, virtual=True)
    watch.close(9.0)
    assert [r for r in recs if r["type"] == "solo"] == []


def test_the_report_reads_the_log(tmp_path, capsys):
    log = UseLog(tmp_path, pc="testpc", background=False)
    watch = SoloWatch(log.put)
    run(watch, FakeWatcher([(2.0, 2.3), (12.0, 12.3), (20.0, 20.3)]), 70.0, rules=[4.0, 19.9])
    log.close()
    idx = next(tmp_path.glob("*.idx")).read_text(encoding="utf-8")
    assert "frames" not in idx                                   # the index has no joints
    assert all(json.loads(line) for line in idx.splitlines())
    tcn_solo_report.main(["--folder", str(tmp_path)])
    out = capsys.readouterr().out
    assert "PC testpc" in out and "가상 손" in out
    row = next(line for line in out.splitlines() if line.strip().startswith("엄지+검지"))
    assert row.split()[1:4] == ["1", "1", "1"]                  # both, retry, alone


# ---------------------------------------------------------------------- quiet stretches, rule versions, the review of retries
import math

from src import label_meta, tcn_solo, use_review


def open_hand(x=0.5, y=0.6):
    """A flat open hand: fingertips far from the thumb tip, not a fist (screen coordinates of a 1280x720 frame)."""
    lm = [[x, y, 0.0]] * 21
    lm = [list(p) for p in lm]
    size = 0.12
    lm[0] = [x, y, 0]
    for finger, ang in zip(range(5), (-60, -20, 0, 20, 40)):
        a = math.radians(ang - 90)
        for j in range(1, 5):
            r = size * (0.5 + 0.45 * j)
            lm[1 + finger * 4 + j - 1] = [x + r * math.cos(a), y + r * math.sin(a) / (720 / 1280), 0]
    lm[9] = [x, y - size / (720 / 1280), 0]       # middle finger root straight up, one hand size
    return lm


def pinching_hand():
    lm = open_hand()
    lm[8] = list(lm[4])                            # index tip on the thumb tip
    return lm


def quiet_run(watch, seconds, hand=open_hand, normal=lambda t: True, commands=(), spans=()):
    frames = []
    commands = sorted(commands)
    watcher = FakeWatcher(list(spans))
    for i in range(int(seconds * FPS)):
        t = i / FPS
        while commands and commands[0] <= t:
            watch.command(commands.pop(0))
        frames.append({"t": t, "lm": hand() if callable(hand) else hand})
        frames = [f for f in frames if t - f["t"] <= 3.0]
        watch.normal(t, False)
        watch.normal(t, normal(t))                 # the rules' word for this frame replaces the placeholder
        watch.step(t, watcher, frames, hand=True, virtual=True)
    watch.close(seconds)


def test_a_hand_only_moving_the_cursor_gives_quiet_none_stretches():
    recs, put = collect()
    watch = SoloWatch(put, rules={"code": "c", "config": "k"})
    quiet_run(watch, 40.0)
    quiet = [r for r in recs if r["type"] == "quiet"]
    assert len(quiet) == 3                                         # 15 s apart at most
    q = quiet[0]
    assert q["label"] == "none" and q["label_source"] == "auto" and q["rules"] == {"code": "c", "config": "k"}
    assert abs((q["end"] - q["t"]) - tcn_solo.QUIET_LEN) < 0.05
    assert all(q["t"] - 0.01 <= f["t"] <= q["end"] + 0.01 for f in q["frames"])


def test_no_quiet_stretch_near_a_command_a_pinch_a_model_moment_or_another_mode():
    for kwargs in ({"commands": [t * 1.0 for t in range(0, 40)]},              # a command every second
                   {"hand": pinching_hand},                                     # fingertip on the thumb
                   {"normal": lambda t: False},                                 # motion / pointing mode, a drag...
                   {"spans": [(t, t + 0.3) for t in range(0, 40, 2)]}):         # the model sees a gesture all along
        recs, put = collect()
        quiet_run(SoloWatch(put), 40.0, **kwargs)
        assert [r for r in recs if r["type"] == "quiet"] == [], kwargs


def test_a_frame_the_rules_did_not_look_at_breaks_the_quiet_stretch():
    recs, put = collect()
    # every 0.5 s one frame without the rules' word (the placeholder stays): never a full quiet stretch
    quiet_run(SoloWatch(put), 40.0, normal=lambda t: int(round(t * FPS)) % 15 != 0)
    assert [r for r in recs if r["type"] == "quiet"] == []


def test_records_keep_the_rules_and_where_the_label_came_from():
    recs, put = collect()
    watch = SoloWatch(put, rules=label_meta.rules_version({"a": 1}))
    run(watch, FakeWatcher([(2.0, 2.3)]), 9.0, rules=[4.0])
    solo = [r for r in recs if r["type"] == "solo"][0]
    assert solo["label_source"] == "model" and set(solo["rules"]) == {"code", "config"}
    assert label_meta.config_hash({"a": 1}) != label_meta.config_hash({"a": 2})
    assert label_meta.code_hash() == label_meta.code_hash()


def test_retry_moments_wait_for_a_review_and_a_verdict_takes_them_off(tmp_path):
    log = UseLog(tmp_path, pc="testpc", background=False)
    watch = SoloWatch(log.put)
    run(watch, FakeWatcher([(2.0, 2.3), (12.0, 12.3), (22.0, 22.3)]), 30.0, rules=[4.0, 14.0])
    log.close()
    key = tcn_solo.review_key(True, "thumb_index")
    assert watch.retries == {key: 2}
    assert tcn_solo.waiting_reviews(tmp_path) == {key: 2}                     # the "alone" one is not reviewed
    moments = tcn_solo.retry_moments(tmp_path, key)
    assert len(moments) == 2 and moments[0]["frames"]
    use_review.set_verdicts(tmp_path, [(moments[0]["file"], moments[0]["id"], use_review.OK)])
    assert tcn_solo.waiting_reviews(tmp_path) == {key: 1}
    assert tcn_solo.parse_key(key) == (True, "thumb_index")
    assert tcn_solo.parse_key("left_click:thumb_index") == (None, "")


_ALIVE = []     # dashboards kept to the end (one garbage-collected while the next test's QML runs crashes Qt on Windows)


def test_the_review_window_shows_retry_moments_and_writes_verdicts_beside_them(tmp_path):
    import os
    import time as _time
    pytest = __import__("pytest")
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication
    from src.qt_dashboard import QtDashboard
    solo_dir = tmp_path / "logs" / "tcn_solo"
    log = UseLog(solo_dir, pc="testpc", background=False)
    watch = SoloWatch(log.put)
    watcher = FakeWatcher([(2.0, 2.3), (12.0, 12.3)])
    rules = [4.0, 14.0]
    frames = []
    for i in range(int(20 * FPS)):
        t = i / FPS
        while rules and rules[0] <= t:
            watch.rule(rules.pop(0), "thumb_index")
        frames = [f for f in frames + [{"t": t, "lm": open_hand()}] if t - f["t"] <= 3.0]
        watch.step(t, watcher, frames, hand=True, virtual=True)
    watch.close(20.0)
    log.close()
    key = tcn_solo.review_key(True, "thumb_index")
    app = QApplication.instance() or QApplication([])
    QQuickStyle.setStyle("Basic")
    ui = QtDashboard(dry_run=True)
    _ALIVE.append(ui)
    ui.use_log_folder = str(tmp_path / "logs" / "use_events")
    ui.openUseReview(key, "놓친 것 같은 엄지+검지")
    end = _time.time() + 10
    while ui.useCases.get("loading") and _time.time() < end:
        _time.sleep(.02)
        app.processEvents()
    cases = ui.useCases
    assert cases["review"] and cases["note"] and len(cases["items"]) == 2 and cases["items"][0]["frames"]
    ui.judgeUseCase(0, "ok")
    ui.judgeUseCase(1, "bad")
    saved = use_review.load(solo_dir)
    assert sorted(v for ids in saved.values() for v in ids.values()) == ["bad", "ok"]
    assert not (tmp_path / "logs" / "use_events" / use_review.FILE).exists()     # the use log's verdicts are not touched
    assert tcn_solo.waiting_reviews(solo_dir) == {}
