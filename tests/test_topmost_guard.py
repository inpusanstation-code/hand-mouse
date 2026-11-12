"""Win+D guard: a window of ANOTHER program that becomes "always on top" right after the app's Win+D is put back;
windows that were already on top, and the app's own windows, are left alone."""
import os
import time

from src import topmost_guard as tg


def test_only_new_windows_of_other_programs_count():
    own = os.getpid()
    assert tg.newly_topmost({1}, {1: 50, 2: 60, 3: own}, own) == [2]


def test_guard_clears_what_appeared_after_the_key(monkeypatch):
    own = os.getpid()
    state = {10: 77}                       # a window that was on top before: stays
    cleared = []
    monkeypatch.setattr(tg.sys, "platform", "win32")
    monkeypatch.setattr(tg, "_topmost_windows", lambda: dict(state))
    monkeypatch.setattr(tg, "_clear", lambda hs: cleared.extend(hs))
    monkeypatch.setattr(tg, "CHECKS", (0.05, 0.1))
    notes = []

    def send():
        state[20] = 88                     # another program's window picks up "always on top"
        state[30] = own                    # one of the app's own overlays: stays

    tg.guard(send, log=notes.append)
    time.sleep(0.4)
    assert cleared == [20]
    assert len(notes) == 1


def test_the_main_window_is_looked_at_once_a_second_and_its_flag_taken_off(monkeypatch):
    """2026-11-11: the app's main window carried "always on top" (set by Windows) and stayed above every program."""
    from types import SimpleNamespace
    import src.topmost_guard as tg
    from src.qt_dashboard import QtDashboard
    state = {"topmost": True, "cleared": 0}
    monkeypatch.setattr(tg.sys, "platform", "win32")
    monkeypatch.setattr(tg, "is_topmost", lambda hwnd: state["topmost"])

    def clear(hwnds):
        state["cleared"] += 1
        state["topmost"] = False

    monkeypatch.setattr(tg, "_clear", clear)
    assert tg.clear_if_topmost(77) is True and state["cleared"] == 1
    assert tg.clear_if_topmost(77) is False and state["cleared"] == 1       # an ordinary window is left alone
    assert tg.clear_if_topmost(0) is False
    board = SimpleNamespace(window=SimpleNamespace(winId=lambda: 77, isVisible=lambda: True, visibility=lambda: 2),
                            MAIN_TOPMOST_CHECK=QtDashboard.MAIN_TOPMOST_CHECK)
    looks = []
    monkeypatch.setattr(tg, "clear_if_topmost", lambda hwnd: looks.append(hwnd) or False)
    QtDashboard._keep_main_window_ordinary(board)
    QtDashboard._keep_main_window_ordinary(board)                           # within the second: not asked again
    assert looks == [77]
