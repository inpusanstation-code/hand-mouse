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
