"""Key names and key combinations for `keys.press` (2026-11-10, registered gestures -> any shortcut).

Pure data and parsing; the Windows backend maps each name to a virtual-key code (output/windows/win32.py) and the
fake backend accepts the same names. A combination is text such as "ctrl+shift+s" or "win+e": modifiers first, then
one or more keys, pressed in order and released in reverse.

Ported idea from virtual-hand-20261110 `src/online/commands.py`: a young recogniser must not be able to end a session,
close things or wipe text at once, so those combinations are refused (`BLOCKED`), and Pause is MANUX's emergency stop.
"""
from __future__ import annotations

import string
from typing import Dict, Tuple

MODIFIERS = ("ctrl", "alt", "shift", "win")
NAMED = (
    "enter", "space", "backspace", "tab", "esc", "capslock", "insert", "delete", "home", "end", "pageup", "pagedown",
    "left", "up", "right", "down", "printscreen", "scrolllock", "numlock", "apps", "pause", "hangul", "hanja",
    "volumemute", "volumedown", "volumeup", "medianext", "mediaprev", "mediastop", "playpause",
    "browserback", "browserforward", "browserrefresh", "browserhome",
    "semicolon", "equal", "comma", "minus", "period", "slash", "backquote", "bracketleft", "backslash",
    "bracketright", "quote",
    "multiply", "add", "subtract", "decimal", "divide",
)
KEY_NAMES: Tuple[str, ...] = (MODIFIERS + tuple(string.ascii_lowercase) + tuple(string.digits)
                              + tuple(f"f{n}" for n in range(1, 25)) + NAMED + tuple(f"num{n}" for n in range(10)))
ALIASES: Dict[str, str] = {
    "control": "ctrl", "ctl": "ctrl", "windows": "win", "window": "win", "meta": "win", "super": "win", "cmd": "win",
    "return": "enter", "escape": "esc", "del": "delete", "ins": "insert", "pgup": "pageup", "pgdn": "pagedown",
    "prtsc": "printscreen", "printscr": "printscreen", "menu": "apps", "back": "backspace",
    "plus": "equal", "=": "equal", "-": "minus", ",": "comma", ".": "period", "/": "slash", "`": "backquote",
    ";": "semicolon", "'": "quote", "[": "bracketleft", "]": "bracketright", "\\": "backslash",
    "mute": "volumemute", "vol+": "volumeup", "vol-": "volumedown", "play": "playpause", "next": "medianext",
    "prev": "mediaprev", "previous": "mediaprev", "한영": "hangul", "한/영": "hangul", "kana": "hangul", "한자": "hanja",
}
BLOCKED = tuple(frozenset(c) for c in (
    ("alt", "f4"), ("ctrl", "w"), ("ctrl", "alt", "delete"), ("win", "l"), ("delete",), ("shift", "delete"),
))
STOP_KEY = "pause"                    # the emergency stop: sending it would stop MANUX itself


class KeyComboError(ValueError):
    pass


def parse_combo(text: str) -> Tuple[str, ...]:
    """'Ctrl + Shift + S' -> ('ctrl', 'shift', 's'): modifiers first (in MODIFIERS order), then the other keys."""
    parts = [p.strip().lower() for p in str(text or "").replace(" ", "").split("+")]
    if str(text or "").strip().endswith("++"):          # "ctrl++" = ctrl + plus
        parts = parts[:-2] + ["equal"]
    keys = [ALIASES.get(p, p) for p in parts if p]
    if not keys:
        raise KeyComboError("키를 입력하세요 (예: ctrl+c, win+e)")
    unknown = [k for k in keys if k not in KEY_NAMES]
    if unknown:
        raise KeyComboError(f"모르는 키: {', '.join(unknown)}")
    if len(set(keys)) != len(keys):
        raise KeyComboError("같은 키가 두 번 들어 있습니다")
    mods = [m for m in MODIFIERS if m in keys]
    rest = [k for k in keys if k not in MODIFIERS]
    if len(rest) > 3:
        raise KeyComboError("한 번에 누를 수 있는 키는 수정키 외 3개까지입니다")
    combo = tuple(mods + rest)
    if STOP_KEY in combo:
        raise KeyComboError("Pause는 MANUX 긴급 정지 키라 연결할 수 없습니다")
    if frozenset(combo) in BLOCKED:
        raise KeyComboError("창·세션을 닫거나 지우는 위험한 키라 연결할 수 없습니다")
    return combo


def combo_text(keys: Tuple[str, ...]) -> str:
    return "+".join(keys)


def combo_label(keys: Tuple[str, ...]) -> str:
    """('ctrl', 'shift', 's') -> 'Ctrl + Shift + S' for the screen."""
    names = {"win": "Win", "esc": "Esc", "pageup": "PgUp", "pagedown": "PgDn", "printscreen": "PrtSc", "equal": "=",
             "minus": "-", "period": ".", "comma": ",", "slash": "/", "playpause": "재생/일시정지"}
    return " + ".join(names.get(k, k.upper() if len(k) == 1 else k.capitalize()) for k in keys)
