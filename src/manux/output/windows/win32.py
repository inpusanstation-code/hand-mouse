"""Real Windows input: ctypes `SendInput` / `SetCursorPos` / `GetCursorPos` (standard library only).

This is the only module of the app that sends real input. Importing it is safe on any OS; creating
`Win32Backend` outside Windows raises `OSError`. Calls that Windows refuses (SendInput returns 0, for
example when a higher-integrity window has focus) raise `OSError`; the sink turns that into
`OutputResult(False, "error:...")`.

Coordinates are whatever the process DPI awareness gives SetCursorPos; the app sets per-monitor DPI
awareness at start (platform/app concern, not this module's).
"""
from __future__ import annotations

import ctypes
import sys
from typing import Tuple

from manux.output.windows.backend import BUTTONS, KEY_NAMES

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002

VK = {
    "alt": 0x12, "ctrl": 0x11, "shift": 0x10, "win": 0x5B,
    **{c: ord(c.upper()) for c in "abcdefghijklmnopqrstuvwxyz0123456789"},
    **{f"f{n}": 0x6F + n for n in range(1, 25)},
    "enter": 0x0D, "space": 0x20, "backspace": 0x08, "tab": 0x09, "esc": 0x1B, "capslock": 0x14,
    "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "printscreen": 0x2C, "scrolllock": 0x91, "numlock": 0x90, "apps": 0x5D, "pause": 0x13,
    "hangul": 0x15, "hanja": 0x19,
    "volumemute": 0xAD, "volumedown": 0xAE, "volumeup": 0xAF, "medianext": 0xB0, "mediaprev": 0xB1,
    "mediastop": 0xB2, "playpause": 0xB3,
    "browserback": 0xA6, "browserforward": 0xA7, "browserrefresh": 0xA8, "browserhome": 0xAC,
    "semicolon": 0xBA, "equal": 0xBB, "comma": 0xBC, "minus": 0xBD, "period": 0xBE, "slash": 0xBF,
    "backquote": 0xC0, "bracketleft": 0xDB, "backslash": 0xDC, "bracketright": 0xDD, "quote": 0xDE,
    **{f"num{n}": 0x60 + n for n in range(10)},
    "multiply": 0x6A, "add": 0x6B, "subtract": 0x6D, "decimal": 0x6E, "divide": 0x6F,
}
# keys Windows wants with the extended flag (arrows and the editing block, Win/Menu, media and browser keys)
EXTENDED = frozenset({"left", "up", "right", "down", "win", "apps", "insert", "delete", "home", "end", "pageup",
                      "pagedown", "printscreen", "divide", "numlock", "volumemute", "volumedown", "volumeup",
                      "medianext", "mediaprev", "mediastop", "playpause", "browserback", "browserforward",
                      "browserrefresh", "browserhome"})
_BUTTON_FLAGS = {
    ("left", True): MOUSEEVENTF_LEFTDOWN, ("left", False): MOUSEEVENTF_LEFTUP,
    ("right", True): MOUSEEVENTF_RIGHTDOWN, ("right", False): MOUSEEVENTF_RIGHTUP,
}
assert set(VK) == set(KEY_NAMES) and {b for b, _ in _BUTTON_FLAGS} == set(BUTTONS)

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_int32), ("dy", ctypes.c_int32), ("mouseData", ctypes.c_int32),
                ("dwFlags", ctypes.c_uint32), ("time", ctypes.c_uint32), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_uint16), ("wScan", ctypes.c_uint16), ("dwFlags", ctypes.c_uint32),
                ("time", ctypes.c_uint32), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_uint32), ("wParamL", ctypes.c_uint16), ("wParamH", ctypes.c_uint16)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_uint32), ("u", _INPUTUNION)]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int32), ("y", ctypes.c_int32)]


def mouse_input(flags: int, data: int = 0) -> INPUT:
    inp = INPUT(type=INPUT_MOUSE)
    inp.mi = MOUSEINPUT(0, 0, int(data), flags, 0, 0)
    return inp


def key_input(name: str, down: bool) -> INPUT:
    flags = (0 if down else KEYEVENTF_KEYUP) | (KEYEVENTF_EXTENDEDKEY if name in EXTENDED else 0)
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.ki = KEYBDINPUT(VK[name], 0, flags, 0, 0)
    return inp


class Win32Backend:
    """InputBackend over user32. One instance per app."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("Win32Backend needs Windows")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SendInput.argtypes = (ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int)
        user32.SendInput.restype = ctypes.c_uint
        user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
        user32.SetCursorPos.restype = ctypes.c_int
        user32.GetCursorPos.argtypes = (ctypes.POINTER(POINT),)
        user32.GetCursorPos.restype = ctypes.c_int
        self._user32 = user32

    def _send(self, *inputs: INPUT) -> None:
        arr = (INPUT * len(inputs))(*inputs)
        sent = self._user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
        if sent != len(inputs):
            raise OSError(f"SendInput sent {sent}/{len(inputs)} (error {ctypes.get_last_error()})")

    def cursor_pos(self) -> Tuple[int, int]:
        pt = POINT()
        if not self._user32.GetCursorPos(ctypes.byref(pt)):
            raise OSError(f"GetCursorPos failed (error {ctypes.get_last_error()})")
        return int(pt.x), int(pt.y)

    def set_cursor_pos(self, x: int, y: int) -> None:
        if not self._user32.SetCursorPos(int(x), int(y)):
            raise OSError(f"SetCursorPos failed (error {ctypes.get_last_error()})")

    def button(self, name: str, down: bool) -> None:
        self._send(mouse_input(_BUTTON_FLAGS[(name, bool(down))]))

    def wheel(self, vertical: int, horizontal: int) -> None:
        inputs = []
        if vertical:
            inputs.append(mouse_input(MOUSEEVENTF_WHEEL, vertical))
        if horizontal:
            inputs.append(mouse_input(MOUSEEVENTF_HWHEEL, horizontal))
        if inputs:
            self._send(*inputs)

    def key(self, name: str, down: bool) -> None:
        self._send(key_input(name, down))
