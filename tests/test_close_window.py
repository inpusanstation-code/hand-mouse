"""Closing the window in front: asked of the window itself, watched, and said when it stayed (2026-11-11 report:
"'창닫기 보냄'이라고는 하는데 창을 닫지 않는 경우가 잦다")."""

from __future__ import annotations

import time

import src.mouse_controller as mc
from src.mouse_controller import MouseController


class FakeUser32:
    """One window (handle 77) in front. `takes`: it closes on the posted request; `keys_close`: on Alt+F4 keys."""

    def __init__(self, takes=True, asks=False):
        self.open, self.front, self.takes, self.asks, self.posted = True, 77, takes, asks, []

    def PostMessageW(self, hwnd, msg, wparam, lparam):
        self.posted.append((hwnd, msg, wparam))
        if self.takes:
            self.open = False
        if self.asks:
            self.front = 78                      # a "save?" question came to the front
        return 1

    def IsWindow(self, hwnd):
        return int(self.open)

    def IsWindowVisible(self, hwnd):
        return int(self.open)

    def GetForegroundWindow(self):
        return self.front


def controller(monkeypatch, user32, keys_close=False):
    m = MouseController(dry_run=True, screen_size=(1920, 1080))
    m.dry_run = False
    m.CLOSE_WAIT = .15
    keys = []
    monkeypatch.setattr(mc.sys, "platform", "win32")
    monkeypatch.setattr(mc, "_user32", lambda: user32)
    monkeypatch.setattr(m, "foreground_info", lambda: {"cls": "Notepad", "title": "메모", "process": "notepad.exe",
                                                       "own": False, "ok": True, "hwnd": 77})

    def hotkey(*k, **kw):
        keys.append(k)
        if keys_close:
            user32.open = False

    monkeypatch.setattr(mc.pyautogui, "hotkey", hotkey)
    return m, keys


def outcome(m):
    end = time.perf_counter() + 3
    while m.close_outcome is None and time.perf_counter() < end:
        time.sleep(.01)
    return m.close_outcome


def test_the_window_is_asked_directly_and_no_keys_are_needed(monkeypatch):
    u = FakeUser32(takes=True)
    m, keys = controller(monkeypatch, u)
    assert m.send_motion_action("close_window") is True
    assert u.posted == [(77, 0x0112, 0xF060)]                    # WM_SYSCOMMAND, SC_CLOSE
    out = outcome(m)
    assert out["result"] == "closed" and out["how"] == "message" and out["title"] == "메모" and keys == []


def test_a_window_that_ignores_the_request_gets_the_keys_once(monkeypatch):
    u = FakeUser32(takes=False)
    m, keys = controller(monkeypatch, u, keys_close=True)
    assert m.close_foreground_window() is True
    out = outcome(m)
    assert keys == [("alt", "f4")] and out["result"] == "closed" and out["how"] == "message+keys"


def test_a_window_that_stays_is_reported_and_a_question_is_not_a_failure(monkeypatch):
    u = FakeUser32(takes=False)
    m, keys = controller(monkeypatch, u)
    m.close_foreground_window()
    assert outcome(m)["result"] == "still" and len(keys) == 1
    u = FakeUser32(takes=False, asks=True)                       # "save changes?": no keys into the question
    m, keys = controller(monkeypatch, u)
    m.close_foreground_window()
    assert outcome(m)["result"] == "changed" and keys == []


def test_the_desktop_and_this_app_are_refused(monkeypatch):
    u = FakeUser32()
    m, keys = controller(monkeypatch, u)
    monkeypatch.setattr(m, "foreground_info", lambda: {"cls": "Progman", "title": "", "own": False, "ok": False, "hwnd": 5})
    assert m.close_foreground_window() is False and u.posted == [] and keys == []
    assert m.send_motion_action("close_window") is False


def test_a_gesture_bound_to_alt_f4_closes_the_same_way(monkeypatch, tmp_path):
    from src.action_bindings import ActionBindingRegistry
    u = FakeUser32(takes=True)
    m, keys = controller(monkeypatch, u)
    reg = ActionBindingRegistry(tmp_path / "b.json")
    ok, badge = reg.execute_resolved_action({"action_type": "hotkey", "action_value": "alt+f4"}, mouse_controller=m)
    assert ok and u.posted and keys == [] and outcome(m)["result"] == "closed"


def test_the_screen_says_when_the_window_stayed(tmp_path):
    from tests.test_qt_runtime import runtime
    rt = runtime(tmp_path)
    rt.mouse.close_outcome = {"result": "still", "how": "message+keys", "title": "메모", "process": "notepad.exe"}
    rt._close_result(time.perf_counter())
    assert "닫히지 않았어요" in rt._close_notice and "메모" in rt._close_notice
    rt._close_notice = ""
    rt._close_result(time.perf_counter())                        # told once
    assert rt._close_notice == ""
    rt.mouse.close_outcome = {"result": "closed", "how": "message", "title": "메모"}
    rt._close_result(time.perf_counter())
    assert rt._close_notice == ""
