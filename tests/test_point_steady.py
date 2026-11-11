"""Pointing mode: the cursor and the drawn hand do not jump when the middle finger comes out or folds, nor when the
mode ends (2026-11-11: "이 자세에서 중지를 폈다 접었다 하면 가상손이 크게 튄다")."""
import dataclasses
import math
import time
from types import SimpleNamespace as NS

from tests.test_point_mode import gun
from tests.test_virtual_hand import box_runtime


def _set(rt, lm):
    rt.tracker.hand[:] = [type(rt.tracker.hand[0])(p.x, p.y, getattr(p, "z", 0.0)) for p in lm]


def _half():
    a, b = gun(middle="folded"), gun(middle="together")
    return [NS(x=(p.x + q.x) / 2, y=(p.y + q.y) / 2, z=0.0) for p, q in zip(a, b)]


def _run(rt, lm, frames):
    _set(rt, lm)
    out = []
    for _ in range(frames):
        time.sleep(1 / 60)
        rt._step()
        out.append((tuple(rt.mouse.last_screen_pos), rt.point.active, rt.point.kind if rt.point.active else ""))
    return out


def _steps(rows):
    return [math.dist(a[0], b[0]) for a, b in zip(rows, rows[1:])]


def test_the_middle_finger_coming_out_and_folding_does_not_move_the_cursor(tmp_path):
    rt = box_runtime(tmp_path)
    rt.ui = dataclasses.replace(rt.ui, stage="main", point_mode=True)
    rt._step()
    rows = _run(rt, gun(middle="folded"), 14)
    assert rows[-1][1] and rows[-1][2] == "double"
    rows += _run(rt, _half(), 6) + _run(rt, gun(middle="together"), 14)
    assert rows[-1][2] == "right"                                    # the shape did change ...
    rows += _run(rt, _half(), 6) + _run(rt, gun(middle="folded"), 14)
    assert rows[-1][2] == "double"
    assert max(_steps(rows[14:])) < 12, _steps(rows[14:])            # ... and the cursor stayed with the index tip


def test_the_cursor_stays_where_it_is_when_pointing_ends(tmp_path):
    rt = box_runtime(tmp_path)
    rt.ui = dataclasses.replace(rt.ui, stage="main", point_mode=True)
    rt._step()
    rows = _run(rt, gun(middle="folded"), 14)
    assert rows[-1][1]
    # the tip travels: the cursor leaves the place the palm would give it
    moved = [NS(x=p.x + .1, y=p.y, z=0.0) for p in gun(middle="folded")]
    rows = _run(rt, moved, 10)
    there = rows[-1][0]
    rt.ui = dataclasses.replace(rt.ui, point_mode=False)            # pointing ends (here: switched off; the hand stays)
    after = _run(rt, moved, 20)
    assert not after[-1][1]
    assert max(_steps([(there, 0, 0)] + after)) < 12, _steps([(there, 0, 0)] + after)   # no jump to the palm's place
    # ... and the difference is given back as the hand moves on
    further = [NS(x=p.x - .1, y=p.y, z=0.0) for p in moved]
    gone = _run(rt, further, 20)
    palm_x = rt._snap.virtual_hand["screen"][0]
    assert abs(gone[-1][0][0] - palm_x) <= 2


def test_while_pointing_the_drawn_index_tip_is_on_the_cursor(tmp_path):
    """2026-11-11 report: "포인팅 모드가 한번 되더니 그 이후로 안된다" - the drawn hand's index tip was on the file, the
    cursor (and the ring) half a hand away from it: the hand was drawn with its thumb-index point on the cursor."""
    rt = box_runtime(tmp_path)
    rt.ui = dataclasses.replace(rt.ui, stage="main", point_mode=True)
    rt._step()
    before = dict(rt._snap.virtual_hand)
    rows = _run(rt, gun(middle="folded"), 14)
    assert rows[-1][1]
    vh = rt._snap.virtual_hand
    tip = [vh["pts"][16], vh["pts"][17]]
    assert vh["anchor"] == tip and vh["anchor"] != before["anchor"]          # the fingertip, not the thumb-index point
    assert vh["screen"] == list(rt.mouse.last_screen_pos) and not vh["lost"]
    assert math.dist(tip, before["anchor"]) > 20                             # (they are well apart on the drawn hand)


def test_a_no_file_answer_is_asked_again_while_the_fingertip_rests(tmp_path):
    """2026-11-11 report: "아무리 오래 파일에 검지끝을 두어도 포인팅모드 더블클릭이 작동을 안한다". One "no file here" (the
    item could not be read that moment) used to stand for as long as the cursor stayed within a few pixels."""
    import sys
    import pytest
    from src.point_mode import FileTargetProbe
    if sys.platform != "win32":
        pytest.skip("the file check runs on Windows")
    answers = [""]                                           # the first look fails ...
    item = ("a.txt", (90, 90, 150, 150))

    def factory(radius_of=None):
        def probe(x, y):
            return answers.pop(0) if answers else item       # ... every later one finds the file
        return probe

    probe = FileTargetProbe(factory)
    try:
        end = time.time() + 3
        states = []
        while time.time() < end and probe.target(120, 120) is None:
            probe.ask(120, 120)                              # the fingertip rests on the same spot
            states.append(probe.state(120, 120))
            time.sleep(.03)
        assert probe.target(120, 120) == item, states[-5:]
        assert "none" in states and probe.answered >= 2      # it did say "no" first, and was asked again
    finally:
        probe.shutdown()


def test_a_file_is_found_among_its_windows_own_items_when_something_lies_over_it():
    """2026-11-11, from the app's own trace: UI Automation said "a document" for a point on a desktop file - another
    program's full-screen transparent overlay lay over the desktop. The item is then looked up among the items of the
    window the mouse would reach."""
    from src.point_mode import item_at, window_under
    items = [("a.txt", (988, 290, 1063, 376)), ("b", (10, 10, 80, 90))]
    assert item_at(items, 1029, 341) == ("a.txt", (988, 290, 1063, 376))
    assert item_at(items, 1029, 500) == "" and item_at([], 5, 5) == ""
    assert item_at(items, 1063, 341) == ""                       # the right edge is outside
    hwnd, cls = window_under(5, 5)
    assert isinstance(hwnd, int) and isinstance(cls, str)        # (0, "") where Windows cannot be asked


def test_the_nearest_item_within_reach_counts_and_the_shared_user32_is_left_alone():
    """2026-11-12, from the app's trace: after four clicks every file check failed with "argument 2 ... 'c_long' object
    cannot be interpreted as an integer" - this module had set argument types on the user32 the uiautomation package
    shares. It has its own handle now; and one check is one look at the window's items, not 17 questions."""
    import ctypes
    import sys
    import pytest
    from src.point_mode import item_near, window_parents, window_under
    items = [("a.txt", (988, 290, 1063, 376)), ("b", (988, 480, 1063, 566))]
    assert item_near(items, 1029, 341, 40) == items[0]                    # on it
    assert item_near(items, 1029, 400, 40) == items[0]                    # 25 px under it: within reach
    assert item_near(items, 1029, 425, 40) == ""                          # 50 px from either
    assert item_near(items, 1029, 450, 40) == items[1]                    # nearer the one below
    assert item_near(items, 1029, 400, 0) == "" and item_near([], 1, 1, 40) == ""
    if sys.platform != "win32":
        pytest.skip("Windows only")
    shared = ctypes.windll.user32.GetAncestor
    before = (getattr(shared, "argtypes", None), shared.restype)
    hwnd, cls = window_under(5, 5)
    assert window_parents(hwnd)[0] == hwnd
    assert (getattr(shared, "argtypes", None), shared.restype) == before  # what uiautomation calls is untouched
