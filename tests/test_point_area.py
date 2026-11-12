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


def test_a_menu_entry_of_a_web_page_under_the_fingertip_is_tapped_once(tmp_path):
    """2026-11-12 ("포인팅 모드에서 이런 웹페이지 메뉴들도 선택할 수 있게", a YouTube side menu): what the check finds
    under the fingertip in a window that is not a file window - a link, a button, a menu entry, with its rectangle -
    is waited on like a file and clicked ONCE, on the element."""
    import time
    from src import point_mode as pmod
    from tests.test_point_mode import _runtime, gun
    entry = ("나중에 볼 동영상", (20, 430, 230, 470), pmod.TAP, "링크")
    assert pmod.is_tap(entry) and not pmod.is_tap(FOLDER) and not pmod.is_tap(None)
    assert pmod.tap_point(entry, (120.0, 455.0)) == (120, 455)                # on it: where the fingertip is
    assert pmod.tap_point(entry, (260.0, 500.0)) == (227, 467)                # beside it: the nearest spot inside
    rt = _runtime(tmp_path)
    rt.point_probe.ask = lambda x, y: None
    rt.point_probe.target = lambda x, y: entry
    rng = random.Random(3)
    end = time.perf_counter() + 1.6
    while time.perf_counter() < end:
        hand = gun(at=(.55 + rng.uniform(-.02, .02), .62 + rng.uniform(-.02, .02)))
        rt.tracker.hand[:] = [type(rt.tracker.hand[0])(p.x, p.y, p.z) for p in hand]
        rt._step()
    assert rt.mouse.event_log.count("left_click") == 1 and "double_click" not in rt.mouse.event_log
    assert "나중에 볼 동영상" in rt._point_view["why"] or rt._point_view["why"].startswith("방금")
    # switched off: neither a tap nor a double click on it
    rt2 = _runtime(tmp_path / "b")
    rt2.engine.config["point_tap_links"] = False
    rt2.point_probe.ask = lambda x, y: None
    rt2.point_probe.target = lambda x, y: entry
    rt2.point_probe.answer = lambda x, y: True
    end = time.perf_counter() + 1.5
    while time.perf_counter() < end:
        rt2.tracker.hand[:] = [type(rt2.tracker.hand[0])(p.x, p.y, p.z) for p in gun(at=(.55, .62))]
        rt2._step()
    assert not [e for e in rt2.mouse.event_log if "click" in e]


def test_the_clickable_element_is_found_by_walking_down_the_windows_tree():
    """The tree is walked from the window into the children whose rectangle holds the point (the "what is at this
    point" question stops at a transparent window on top); the smallest clickable element holding it wins."""
    from types import SimpleNamespace as NS
    from src import point_mode as pmod

    def node(kind, rect, name="", children=()):
        return NS(ControlTypeName=kind, Name=name, BoundingRectangle=NS(left=rect[0], top=rect[1], right=rect[2], bottom=rect[3]),
                  GetChildren=lambda: list(children))

    link = node("HyperlinkControl", (20, 430, 230, 470), "나중에 볼 동영상", [node("TextControl", (60, 440, 200, 460), "나중에 볼 동영상")])
    other = node("HyperlinkControl", (20, 480, 230, 520), "좋아요 표시한 동영상")
    page = node("DocumentControl", (0, 100, 1000, 900), "", [node("GroupControl", (0, 100, 240, 900), "", [link, other]),
                                                              node("GroupControl", (240, 100, 1000, 900), "", [
                                                                  node("ButtonControl", (300, 200, 2000, 900), "너무 큰 것")])])
    hidden = node("PaneControl", (0, 0, 0, 0), "", [page])                      # a holder without a size is looked into
    auto = NS(ControlFromHandle=lambda hwnd: node("WindowControl", (0, 0, 1000, 900), "", [hidden]))
    found = pmod.uia_tap_at(auto, 1, 120, 450)
    assert found == ("나중에 볼 동영상", (20, 430, 230, 470), pmod.TAP, "링크")
    assert pmod.uia_tap_at(auto, 1, 120, 475, 0) is None                        # between the two entries: nothing
    assert pmod.uia_tap_at(auto, 1, 120, 477, 10)[0] == "좋아요 표시한 동영상"   # ... but the nearer one within reach
    assert pmod.uia_tap_at(auto, 1, 500, 500) is None                           # a "button" as large as the page is none
