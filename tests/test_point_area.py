"""Pointing mode waits on the file / folder at or around the fingertip, not on one spot (2026-11-11).

"완전 아무런 떨림도 없이 1초동안 유지해야 하는거 같은데 그건 사실상 불가능하니까 검지, 검지중지 끝부분의 주변을 기준으로
영역을 잡아서 그 영역에 포함된 파일, 폴더가 더블클릭 판정을 받도록 바꿔줘. 손이 완전 정지상태가 되는건 사실상 불가능"."""
import math
import random

from src.point_mode import AREA_PX, FileTargetProbe, PointMode, area_points

FOLDER = ("arduino", (100, 200, 180, 290))          # name, rectangle on the screen
OTHER = ("sources", (100, 300, 180, 390))


def _mode(kind="double"):
    pm = PointMode()
    pm.active, pm.kind = True, kind
    return pm


def test_a_trembling_fingertip_on_or_around_the_item_still_clicks_it_once():
    rng = random.Random(1)
    pm, t, fired = _mode(), 0.0, []
    for _ in range(45):                               # 1.5 s, the tip shaking 60 px around (it had to stay within 24 px)
        cur = (140 + rng.uniform(-60, 60), 245 + rng.uniform(-60, 60))
        k = pm.dwell(t, cur, True, item=FOLDER)
        if k:
            fired.append(round(t, 2))
        t += 1 / 30
    assert len(fired) == 1 and 0.95 <= fired[0] <= 1.1      # once, after the 1 s wait
    for _ in range(90):                               # still pointing at it: not again
        assert pm.dwell(t, (140, 245), True, item=FOLDER) == ""
        t += 1 / 30
    for _ in range(15):                               # pointed away (nothing near) for half a second ...
        assert pm.dwell(t, (600, 600), False, item=None) == ""
        t += 1 / 30
    again = ""
    for _ in range(40):                               # ... and back: it can be opened again
        again = again or pm.dwell(t, (140, 245), True, item=FOLDER)
        t += 1 / 30
    assert again == "double"


def test_a_short_slip_off_the_item_does_not_start_over_and_another_item_starts_its_own_wait():
    pm, t = _mode("right"), 0.0
    for _ in range(18):                               # 0.6 s on the folder
        assert pm.dwell(t, (140, 245), True, item=FOLDER) == ""
        t += 1 / 30
    for _ in range(6):                                # the check comes back empty for 0.2 s (the tip slipped off)
        assert pm.dwell(t, (300, 245), None, item=None) == ""
        t += 1 / 30
    fired = ""
    for _ in range(8):                                # back on it: the wait went on (1 s since it began)
        fired = fired or pm.dwell(t, (140, 245), True, item=FOLDER)
        t += 1 / 30
    assert fired == "right"
    pm, t = _mode(), 0.0
    for _ in range(25):
        pm.dwell(t, (140, 245), True, item=FOLDER)
        t += 1 / 30
    for _ in range(25):                               # moved on to the next item before the second was over
        assert pm.dwell(t, (140, 345), True, item=OTHER) == ""
        t += 1 / 30
    assert 0.7 < pm.progress < 0.95                    # that item's own wait, not the first one's


def test_the_item_is_found_around_the_fingertip_and_stays_the_target_while_the_tip_is_near_it():
    assert area_points(500, 500)[0] == (500, 500) and len(area_points(500, 500)) == 17
    assert max(math.dist(p, (500, 500)) for p in area_points(500, 500)) <= AREA_PX + 1
    p = FileTargetProbe(probe_factory=lambda: (lambda x, y: FOLDER))
    p._have = ((190, 300), FOLDER)                    # what the probe found for a tip just outside the item's corner
    assert p.target(190, 300) == FOLDER and p.name == "arduino"
    assert p.target(100 - AREA_PX + 1, 245) == FOLDER and p.target(140, 290 + AREA_PX - 1) == FOLDER
    assert p.target(100 - AREA_PX - 5, 245) is None and p.target(400, 245) is None
    p._have = ((190, 300), "arduino")                 # a probe that gives names only: no item, the old spot rule applies
    assert p.target(190, 300) is None and p.answer(190, 300) is True and p.name == "arduino"
    p._have = ((190, 300), "")
    assert p.target(190, 300) is None and p.answer(190, 300) is False


def test_the_app_clicks_the_item_the_shaking_finger_points_around(tmp_path):
    from tests.test_point_mode import _runtime, gun
    rt = _runtime(tmp_path)
    rt.point_probe.ask = lambda x, y: None
    rt.point_probe.target = lambda x, y: FOLDER       # the folder is within reach of the fingertip all along
    rng = random.Random(2)
    import time
    end = time.perf_counter() + 1.6
    while time.perf_counter() < end:
        hand = gun(at=(.55 + rng.uniform(-.02, .02), .62 + rng.uniform(-.02, .02)))     # a hand that cannot hold still
        rt.tracker.hand[:] = [type(rt.tracker.hand[0])(p.x, p.y, p.z) for p in hand]
        rt._step()
    assert rt.mouse.event_log.count("double_click") == 1
    assert rt._point_view["name"] == "arduino" and rt._point_view["screen"] == [140, 245]     # the ring sits on the item
