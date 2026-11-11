"""Pointing mode (src/point_mode.py, 2026-11-11): the finger-gun hand moves the cursor with the index tip and a 1 s rest on a
file / folder double-clicks it (index + middle together: right click)."""
import dataclasses
import math
import time
from types import SimpleNamespace

import pytest

from src.point_mode import FileTargetProbe, PointMode, shape

ASPECT = 720 / 1280


def _rot(v, deg):
    a = math.radians(deg)
    return (v[0] * math.cos(a) - v[1] * math.sin(a), v[0] * math.sin(a) + v[1] * math.cos(a))


def gun(tilt=45.0, middle="folded", thumb="up", together=True, scale=.12, at=(.55, .62)):
    """A right hand in the mirrored preview: palm up the screen, thumb on the left. Index (and middle) lean `tilt`
    degrees to the left of straight up. Points in a square space, turned into frame coordinates (y / aspect)."""
    up, right = (0.0, -1.0), (1.0, 0.0)
    pts = [None] * 21
    pts[0] = (0.0, 0.0)
    knuckles = {5: -.28, 9: -.08, 13: .1, 17: .26}
    d = _rot(up, -tilt)                                 # leaning left (counter-clockwise on the screen)
    for mcp, side in knuckles.items():
        base = (side, -1.0 + abs(side) * .25)
        pts[mcp] = base
        finger = {5: "out", 9: middle, 13: "folded", 17: "folded"}[mcp]
        if finger == "out" or (finger == "together"):
            dd = d
            if mcp == 9 and together:                   # beside the index, same way
                base = (pts[5][0] + .14 * math.cos(math.radians(tilt)), pts[5][1] - .14 * math.sin(math.radians(tilt)))
                pts[9] = base
            elif mcp == 9:
                dd = _rot(up, 5)                        # the middle up and away from the index
            for i, k in enumerate((.45, .75, 1.0)):
                pts[mcp + 1 + i] = (base[0] + dd[0] * k, base[1] + dd[1] * k)
        else:                                           # curled into the palm
            pts[mcp + 1] = (base[0], base[1] - .25)
            pts[mcp + 2] = (base[0] - .02, base[1] - .12)
            pts[mcp + 3] = (base[0] - .02, base[1] + .08)
    if thumb == "up":
        t = _rot(up, 15)
        cmc = (-.35, -.3)
        segs = (.4, .35, .35)                           # stuck out: .65-1.2 palm lengths in the recordings
    else:                                               # folded across the palm
        t = (1.0, -.2)
        cmc = (-.3, -.35)
        segs = (.12, .1, .1)
    pts[1] = cmc
    x, y = cmc
    for i, s in enumerate(segs):
        x, y = x + t[0] * s, y + t[1] * s
        pts[2 + i] = (x, y)
    return [SimpleNamespace(x=at[0] + p[0] * scale, y=at[1] + p[1] * scale / ASPECT, z=0.0) for p in pts]


def test_the_finger_gun_shapes():
    assert shape(gun(), ASPECT) == "double"
    assert shape(gun(middle="out"), ASPECT) == "right"                     # index and middle out, side by side
    assert shape(gun(middle="out", together=False), ASPECT) == ""          # apart: not the right-click shape
    assert shape(gun(tilt=0), ASPECT) == ""                                # straight up: not diagonal
    assert shape(gun(tilt=88), ASPECT) == ""                               # flat
    assert shape(gun(thumb="folded"), ASPECT) == ""                        # the thumb has to be up
    assert shape(None, ASPECT) == "" and shape(gun()[:20], ASPECT) == ""


def test_the_mode_needs_the_shape_held_and_survives_a_dropped_frame():
    pm = PointMode()
    hand = gun()
    t = 0.0
    for i in range(PointMode.ENTER - 1):
        assert not pm.step(t, hand, ASPECT)
        t += 1 / 30
    assert pm.step(t, hand, ASPECT) and pm.started and pm.kind == "double"
    t += 1 / 30
    assert pm.step(t, None, ASPECT) and not pm.started                     # one lost frame does not end it
    t += PointMode.LEAVE + .05
    assert not pm.step(t, None, ASPECT)                                    # gone longer: over


def test_a_rest_on_a_file_clicks_once_and_only_on_a_file():
    pm = PointMode()
    for i in range(PointMode.ENTER):
        pm.step(i / 30, gun(), ASPECT)
    t = 1.0
    # resting, but not on a file: nothing
    for _ in range(40):
        assert pm.dwell(t, (500, 500), False) == ""
        t += 1 / 30
    # on a file, wobbling a little: fires after DWELL
    fired = []
    start = t
    while t - start < PointMode.DWELL + .2:
        k = pm.dwell(t, (800 + (t * 50) % 10, 400), True)
        if k:
            fired.append((k, t - start))
        t += 1 / 30
    assert [k for k, _ in fired] == ["double"] and fired[0][1] == pytest.approx(PointMode.DWELL, abs=.05)
    # staying there does not click again; moving away and back does
    for _ in range(60):
        assert pm.dwell(t, (803, 400), True) == ""
        t += 1 / 30
    pm.dwell(t, (900, 400), True)
    t += 1 / 30
    again = ""
    for _ in range(40):
        again = again or pm.dwell(t, (900, 400), True)
        t += 1 / 30
    assert again == "double"


def test_the_target_check_runs_in_its_own_thread():
    calls = []

    def factory():
        def probe(x, y):
            calls.append((x, y))
            return "보고서.docx" if x < 1000 else ""
        return probe

    p = FileTargetProbe(probe_factory=factory)
    p.available = True
    p._run_real = p._run

    def run():               # without UI Automation: the factory alone
        probe = p._factory()
        while not p._stop.is_set():
            p._wake.wait(.5)
            p._wake.clear()
            if p._want is not None:
                p._have = (p._want, probe(*p._want))
    p._run = run
    p.ask(500, 500)
    for _ in range(100):
        if p.answer(500, 500) is not None:
            break
        time.sleep(.01)
    assert p.answer(500, 500) is True and p.name == "보고서.docx"
    assert p.answer(1500, 500) is None                                     # far from the asked point: unknown
    p.ask(1500, 500)
    for _ in range(100):
        if p.answer(1500, 500) is not None:
            break
        time.sleep(.01)
    assert p.answer(1500, 500) is False
    p.shutdown()


def _runtime(tmp_path, point_mode=True):
    from tests.test_qt_runtime import runtime
    rt = runtime(tmp_path)
    rt.ui = dataclasses.replace(rt.ui, use_index_pointer=False, point_mode=point_mode)
    rt.paused = False
    rt.point_probe.ask = lambda x, y: None
    rt.point_probe.answer = lambda x, y: True                              # a file under the cursor
    return rt


def test_the_app_double_clicks_a_file_the_finger_gun_rests_on(tmp_path):
    rt = _runtime(tmp_path)
    rt.tracker.hand = gun()
    start = time.perf_counter()
    while time.perf_counter() - start < PointMode.DWELL + .6:
        rt._step()
        time.sleep(1 / 60)
    assert rt.point.active and rt._snap.point and rt._snap.point["kind"] == "double"
    assert rt.mouse.event_log.count("double_click") == 1
    assert "left_click" not in rt.mouse.event_log


def test_switched_off_in_the_settings_it_does_nothing(tmp_path):
    rt = _runtime(tmp_path, point_mode=False)
    rt.tracker.hand = gun()
    for _ in range(50):
        rt._step()
        time.sleep(1 / 60)
    assert not rt.point.active and rt._snap.point is None and "double_click" not in rt.mouse.event_log


# ---------------------------------------------------------------------------- the settings window's details (2026-11-11)
def test_settings_are_kept_in_range_and_change_the_mode():
    from src.point_mode import SETTINGS, clean_settings
    s = clean_settings({"dwell": 9, "area_px": -5, "tilt_min": 60, "tilt_max": 50, "enter_frames": "x", "right_click": 0})
    assert s["dwell"] == 3.0 and s["area_px"] == 0 and s["enter_frames"] == SETTINGS["enter_frames"][0]
    assert s["tilt_min"] <= s["tilt_max"] and s["right_click"] is False
    assert clean_settings(None) == {k: v[0] for k, v in SETTINGS.items()}
    pm = PointMode()
    pm.configure({"dwell": 2.0, "enter_frames": 2})
    assert pm.DWELL == 2.0 and pm.ENTER == 2 and PointMode.DWELL == 1.0          # the class default is untouched
    assert pm.step(0.0, gun(), ASPECT) is False and pm.step(1 / 30, gun(), ASPECT)   # on after 2 frames now


def test_the_tilt_range_and_the_right_click_switch_change_what_is_recognised():
    assert shape(gun(tilt=5), ASPECT) == ""                                    # nearly upright: outside 20-80
    assert shape(gun(tilt=5), ASPECT, (0.0, 80.0)) == "double"                 # allowed once the range starts at 0
    assert shape(gun(middle="out"), ASPECT, right=False) == ""                 # right-click shape switched off
    pm = PointMode()
    pm.configure({"right_click": False})
    for i in range(6):
        pm.step(i / 30, gun(middle="out"), ASPECT)
    assert not pm.active


def test_the_dashboard_stores_the_settings_and_hands_them_to_the_runtime():
    import os
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication
    from src.qt_dashboard import QtDashboard
    QApplication.instance() or QApplication([])
    QQuickStyle.setStyle("Basic")
    ui = QtDashboard(dry_run=True)
    try:
        ui.setPointSetting("dwell", 1.7)
        ui.setPointSetting("tilt_min", 85)                                     # above the max: the max follows
        assert ui.pointSettings["values"]["dwell"] == pytest.approx(1.7)
        assert ui.pointSettings["values"]["tilt_max"] >= 45 and ui.pointSettings["values"]["tilt_min"] == 45
        assert ui.ui_state().point_settings["dwell"] == pytest.approx(1.7)
        assert "1.7" in str(ui.preferences.value("pointModeSettings"))
    finally:
        ui.resetPointSettings()
    assert ui.pointSettings["values"]["dwell"] == 1.0

def _short_thumb(k):
    """The finger gun with its thumb drawn `k` times as long (pointing partly at the camera, it looks short)."""
    hand = gun()
    base = hand[1]
    for i in (2, 3, 4):
        hand[i] = SimpleNamespace(x=base.x + (hand[i].x - base.x) * k, y=base.y + (hand[i].y - base.y) * k, z=0.0)
    return hand


def test_a_thumb_that_looks_short_still_points_and_the_shape_may_loosen_once_the_mode_is_on():
    """2026-11-11 report: "포인팅모드 더블클릭 판정도 너무 엄격한 거 같다. 이 정도에도 판정이 안 떨어지네" - on the person's logs
    71 % of the pointing hands that were not read had a straight, upward thumb that only looked short."""
    from src.motion_mode import hand_features
    from src.point_mode import KEEP, THUMB_LEN
    medium, short = _short_thumb(.74), _short_thumb(.57)
    assert THUMB_LEN <= hand_features(medium)["thumb_len"] < .6                  # refused until now (the limit was .6)
    assert KEEP["thumb_len"] <= hand_features(short)["thumb_len"] < THUMB_LEN
    assert shape(medium, ASPECT) == "double"
    assert shape(short, ASPECT) == "" and shape(short, ASPECT, keep=True) == "double"
    assert shape(gun(thumb="folded"), ASPECT, keep=True) == ""                  # a folded thumb is still not the shape
    assert shape(gun(tilt=14), ASPECT) == "" and shape(gun(tilt=14), ASPECT, keep=True) == "double"
    # the looser hand cannot start the mode, but it keeps a mode that is on
    pm = PointMode()
    t = 0.0
    for _ in range(PointMode.ENTER + 3):
        assert not pm.step(t, short, ASPECT)
        t += 1 / 30
    for _ in range(PointMode.ENTER):
        pm.step(t, gun(), ASPECT)
        t += 1 / 30
    assert pm.active
    for _ in range(45):                                                          # 1.5 s of the relaxed hand: still on
        assert pm.step(t, short, ASPECT)
        t += 1 / 30


def test_loosely_curled_fingers_are_folded_next_to_a_straight_index():
    """2026-11-11, the person again ("이 정도도 되어야 하는 거 아니냐"): the folded fingers of their finger gun measured
    1.43 at the median, over the limit; folded is now "short, and clearly shorter than the index"."""
    from src.pose_probe import _finger_ratios
    from src.point_mode import FOLD_2D
    loose = gun()
    for mcp in (9, 13, 17):                       # the curled fingers' tips come out a little (not tucked into the palm)
        base = loose[mcp]
        loose[mcp + 3] = SimpleNamespace(x=base.x - .004, y=base.y - .048 / ASPECT, z=0.0)
    r = _finger_ratios(loose)
    assert all(1.3 < v <= FOLD_2D for v in r[1:]) and r[0] - max(r[1:]) >= .3
    assert shape(loose, ASPECT) == "double"
    # the same fingers next to an index that is hardly longer are not "folded": that hand is not pointing
    stubby = gun()
    for mcp in (9, 13, 17):
        base = stubby[mcp]
        stubby[mcp + 3] = SimpleNamespace(x=base.x - .004, y=base.y - .048 / ASPECT, z=0.0)
    for i, k in ((6, .2), (7, .34), (8, .45)):    # the index only half out
        b = stubby[5]
        stubby[i] = SimpleNamespace(x=b.x + (gun()[8].x - b.x) * k, y=b.y + (gun()[8].y - b.y) * k, z=0.0)
    assert shape(stubby, ASPECT) == ""
