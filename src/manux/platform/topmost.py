"""Keep a small always-on-top window shown (Windows): the virtual hand drawn on the screen.

2026-11-10 '바탕화면 보기로 내리면 간헐적으로 가상손이 자꾸 사라진다': "show desktop" (Win+D, also the virtual hand's
own gesture bound to it) hides top-level windows, the click-through always-on-top hand included, and Qt still thinks the
window is visible, so nothing brings it back. The hand-mouse virtual-hand branch put the hand back on top 4 times a
second while the task switcher was open; this does the same whenever the hand should be shown: if Windows has the
window minimised or hidden, show it without taking focus, and put it back at the top of the always-on-top band.
Not Windows: does nothing.
"""
from __future__ import annotations

import sys

SW_SHOWNOACTIVATE = 4
HWND_TOPMOST = -1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x1, 0x2, 0x10, 0x40


def reassert(win_id: int) -> bool:
    """True when the window had been hidden or minimised by Windows and was shown again."""
    if sys.platform != "win32" or not win_id:
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = ctypes.c_void_p(int(win_id))
        hidden = bool(user32.IsIconic(hwnd)) or not bool(user32.IsWindowVisible(hwnd))
        if hidden:
            user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        user32.SetWindowPos(hwnd, ctypes.c_void_p(HWND_TOPMOST), 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)
        return hidden
    except Exception:            # never let the drawing helper break the UI
        return False
