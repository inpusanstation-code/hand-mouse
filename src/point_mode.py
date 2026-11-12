"""Pointing mode (2026-11-11, user request): a finger-gun hand moves the cursor with the index tip, and resting it on a
file or folder for a second opens it (double click) or opens its menu (right click).

    thumb up, index out, both tilted (diagonal), middle / ring / little finger folded   -> "double"
    thumb up, index and middle out side by side and touching, tilted, ring / little folded -> "right"

No separate entry: the hand shape itself is the mode (on by default, switched off in the settings window). The click only
happens on a file / folder item (Explorer, the desktop, a file dialog), asked of Windows UI Automation in a background
thread so the camera loop never waits. The user chose (2026-11-11): fingers tilted diagonally, files and folders only,
1 s dwell, the cursor follows the index tip.

The shape thresholds are starting points: no recording of this hand shape exists yet."""
from __future__ import annotations

import math
import sys
import threading
import time
from typing import Any, Callable, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------- the hand shape
OUT_2D, OUT_3D = 1.45, 1.4        # finger tip->wrist over knuckle->wrist: straight (pose_probe: straight ~1.9)
# 2026-11-11 report ("포인팅모드 더블클릭 판정도 너무 엄격한 거 같다. 이 정도에도 판정이 안 떨어지네"), measured on the person's
# logs (79,881 hand frames; 2,389 of them pointing-like: index out and tilted, the others not out, no pinch): only 27 % were
# read as the shape. 71 % of the misses had the thumb "not out" - straight (.98) and pointing up (23 degrees) but short in the
# picture (.50 palm lengths at the median: it points partly at the camera); 30 % had the ring finger just over "folded"
# (1.29-1.38). With the thumb at .45 and folded at 1.4 / 1.45: 52 % read; all frames read as the shape .9 % -> 2.0 %.
# Same day, the person again ("이 정도도 되어야 하는 거 아니냐", a finger gun on a desktop file: thumb long and up, index at
# 47 degrees): of the 195 pointing-like frames in the failure logs of those minutes 41 % could start the mode. The thumb
# and the tilt were fine; the FOLDED fingers were not folded enough - ring at 1.43 (2D) at the median, the middle "neither
# folded nor out". A loosely curled finger measures 1.4-1.5; next to an index at 2.0 that is folded. With "under 1.5 and at
# least .3 shorter than the index": 83 % start, 88 % stay; all frames read as the shape 1.7 % -> 1.9 %.
FOLD_2D, FOLD_3D = 1.5, 1.5       # ... folded (curled under 1.1); was 1.3 / 1.35, then 1.4 / 1.45
FOLD_GAP, FOLD_GAP_KEEP = .3, .2  # ... and this much shorter than the index in the picture (see shape)
# 2026-11-12 report (a finger gun on a desktop icon, thumb up, index nearly upright: "손가락의 의도가 명확한데도 안 되는 거
# 보면 손목 각도에 대한 엄격함은 좀 줄여야"): it was not the index's lean. Of that morning's frames with the thumb up, the
# index out and ring + little finger folded, 163 were not the shape, and in all but 2 the MIDDLE finger was the reason:
# "neither folded nor out" (102) or out without being the right-click shape. With the wrist bent the palm is seen
# short, and a folded finger's tip -> wrist over knuckle -> wrist blows up in the picture (the folded middle read
# 1.5-2.7 there, 1.2-1.5 in 3D). A finger is folded now when EITHER the picture says so (as before) or the 3D lengths
# do: at most FOLD_3D and this much shorter than the index in 3D. Same logs: frames read as the double-click shape
# 284 -> 504 of 13,436 (all shapes 2.6 % -> 4.4 %); the 11-11 logs of the other PC 8.9 % -> 9.8 % of 24,298.
FOLD_GAP_3D, FOLD_GAP_3D_KEEP = .4, .3
THUMB_STRAIGHT, THUMB_LEN = .85, .45  # src/motion_mode.hand_features (pose_probe uses .9 / .65 for "stuck out"); len was .6
# Once the mode is on, the shape may loosen (PointMode.step): a hand held up for a second relaxes, and the mode ending in the
# middle of the wait starts the wait over. The limits to START the mode stay the ones above.
KEEP = {"out": (1.35, 1.3), "fold": (1.6, 1.6), "thumb_straight": .75, "thumb_len": .35, "tilt": 8.0}
THUMB_UP_COS = math.cos(math.radians(80))   # the thumb points upward (anything up to 80 degrees off vertical)
TILT_MIN, TILT_MAX = 20.0, 80.0   # degrees the index (and middle) lean off vertical: "diagonal", not straight up / flat
TOGETHER = .35                    # index and middle tips this many hand sizes apart, at most, for the right-click shape
TOGETHER_DEG = 20.0               # ... and pointing the same way within this

# What the person can change in the settings window (2026-11-11 request: "포인팅 모드도 설정 안에서 상세 설정"):
# name -> (default, lowest, highest). Stored by the dashboard (QSettings), passed in UiState.point_settings.
SETTINGS = {
    "dwell": (1.0, .5, 3.0),          # s resting on a file / folder before the click
    "area_px": (40, 0, 100),          # a file / folder this near the fingertip counts
    "tilt_min": (20.0, 0.0, 45.0),    # the index (and middle) lean at least this many degrees off vertical ...
    "tilt_max": (80.0, 45.0, 90.0),   # ... and at most this many
    "enter_frames": (4, 2, 10),       # frames of the shape in a row before the mode starts
    "leave": (.35, .1, 1.0),          # s the shape may be lost before the mode ends
    "speed": (1.0, .5, 2.0),          # cursor speed while pointing (times the pointer sensitivity)
    "right_click": (True, False, True),   # the index + middle shape right-clicks
}


def clean_settings(raw: Any) -> dict:
    """Every setting, within its range (missing or broken ones at their default)."""
    out = {}
    raw = raw if isinstance(raw, dict) else {}
    for name, (default, low, high) in SETTINGS.items():
        value = raw.get(name, default)
        if isinstance(default, bool):
            out[name] = bool(value)
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = float(default)
        if not math.isfinite(value):
            value = float(default)
        value = max(float(low), min(float(high), value))
        out[name] = int(round(value)) if isinstance(default, int) else value
    if out["tilt_min"] > out["tilt_max"]:
        out["tilt_min"] = out["tilt_max"]
    return out


def _px(p: Any, aspect: float) -> Tuple[float, float]:
    return (float(p.x), float(p.y) * aspect)


def _tilt(landmarks: Sequence[Any], mcp: int, tip: int, aspect: float) -> Tuple[float, Tuple[float, float]]:
    """Degrees the finger (knuckle -> tip) leans off straight up on the screen, and its direction."""
    a, b = _px(landmarks[mcp], aspect), _px(landmarks[tip], aspect)
    vx, vy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(vx, vy) or 1e-9
    return math.degrees(math.acos(max(-1.0, min(1.0, -vy / n)))), (vx / n, vy / n)


def shape(landmarks: Sequence[Any], aspect: float = 720 / 1280, tilt: Tuple[float, float] = (TILT_MIN, TILT_MAX),
          right: bool = True, keep: bool = False) -> str:
    """"double", "right" or "" for one frame of 21 landmarks. `tilt`: the lean (degrees off vertical) the index must be
    within; `right`: the right-click shape is recognised at all; `keep`: the looser limits of a mode that is already on."""
    tilt_min, tilt_max = tilt
    if landmarks is None or len(landmarks) != 21:
        return ""
    from src.motion_mode import hand_features
    from src.pose_probe import _finger_ratios, finger_ratios_3d
    out_2d, out_3d = KEEP["out"] if keep else (OUT_2D, OUT_3D)
    fold_2d, fold_3d = KEEP["fold"] if keep else (FOLD_2D, FOLD_3D)
    thumb_straight, thumb_len = (KEEP["thumb_straight"], KEEP["thumb_len"]) if keep else (THUMB_STRAIGHT, THUMB_LEN)
    if keep:
        tilt_min, tilt_max = max(0.0, tilt_min - KEEP["tilt"]), min(90.0, tilt_max + KEEP["tilt"])
    r2, r3 = _finger_ratios(landmarks), finger_ratios_3d(landmarks, aspect)
    out = [a >= out_2d and b >= out_3d for a, b in zip(r2, r3)]
    # folded = short, AND clearly shorter than the index: a loosely curled finger measures 1.4-1.5, which only says
    # "folded" next to an index at 2.0 (the V sign is told the same way, pose_probe.V_GAP)
    gap = FOLD_GAP_KEEP if keep else FOLD_GAP
    gap3 = FOLD_GAP_3D_KEEP if keep else FOLD_GAP_3D
    folded = [(a <= fold_2d and b <= fold_3d and r2[0] - a >= gap) or (b <= fold_3d and r3[0] - b >= gap3)
              for a, b in zip(r2, r3)]
    if not out[0] or not folded[2] or not folded[3]:
        return ""
    f = hand_features(landmarks)
    if f.get("thumb_straight", 0.0) < thumb_straight or f.get("thumb_len", 0.0) < thumb_len:
        return ""
    if f.get("thumb_up", -1.0) < THUMB_UP_COS:
        return ""
    tilt_i, dir_i = _tilt(landmarks, 5, 8, aspect)
    if not tilt_min <= tilt_i <= tilt_max:
        return ""
    if folded[1]:
        return "double"
    if not out[1] or not right:
        return ""
    tilt_m, dir_m = _tilt(landmarks, 9, 12, aspect)
    if not tilt_min <= tilt_m <= tilt_max:
        return ""
    size = math.dist(_px(landmarks[0], aspect), _px(landmarks[9], aspect)) or 1e-9
    gap = math.dist(_px(landmarks[8], aspect), _px(landmarks[12], aspect)) / size
    same_way = math.degrees(math.acos(max(-1.0, min(1.0, dir_i[0] * dir_m[0] + dir_i[1] * dir_m[1]))))
    return "right" if gap <= TOGETHER and same_way <= TOGETHER_DEG else ""


# ---------------------------------------------------------------------------- the mode and the dwell
class PointMode:
    """step() once per frame with the hand (or None): True while the mode is on. The shape must hold ENTER frames to
    start (a hand passing through it does not), and the mode lasts LEAVE seconds without it (a flickering frame does
    not end it). dwell() then times the cursor resting on one spot."""

    ENTER = 4                  # frames of the shape in a row (~0.13 s at 30 fps)
    SWITCH = 3                 # frames of the other shape to switch between double and right
    LEAVE = .35                # seconds without the shape before the mode ends
    DWELL = 1.0                # seconds resting on a file / folder (user's choice)
    STILL_PX = 24              # the cursor may wander this far (screen pixels) and still count as resting
    REARM_PX = 48              # after a click, move this far away before the next one (no repeated double clicks)
    # 2026-11-11 report: "완전 아무런 떨림도 없이 1초동안 유지해야 하는 거 같은데 그건 사실상 불가능 … 끝부분의 주변을 기준으로
    # 영역을 잡아서 그 영역에 포함된 파일, 폴더가 더블클릭 판정을 받도록". With the item known (its name and rectangle,
    # FileTargetProbe.target) the wait is on the ITEM, not on a spot: the fingertip may wander anywhere on or around it.
    ITEM_GRACE = .3            # s the item may drop out (the tip slips off, a check comes back empty) without starting over

    def __init__(self) -> None:
        self.tilt = (TILT_MIN, TILT_MAX)
        self.right = True
        self.settings = clean_settings({})
        self.reset()

    def configure(self, raw: Any) -> None:
        """The settings window's values (src/point_mode.SETTINGS); cheap enough to call every frame."""
        s = clean_settings(raw)
        if s == self.settings and getattr(self, "_configured", False):
            return
        self._configured = True
        self.settings = s
        self.DWELL, self.ENTER, self.LEAVE = float(s["dwell"]), int(s["enter_frames"]), float(s["leave"])
        self.tilt, self.right = (float(s["tilt_min"]), float(s["tilt_max"])), bool(s["right_click"])

    def reset(self) -> None:
        self.active = False
        self.kind = ""
        self._run_kind, self._run = "", 0
        self._seen_t = -1e9
        self.started = False                 # True on the frame the mode began
        self._anchor: Optional[Tuple[float, float]] = None
        self._since = 0.0
        self._spent_at: Optional[Tuple[float, float]] = None
        self.progress = 0.0
        self._item: Any = None               # the file / folder being waited on (its name and rectangle)
        self._item_seen = 0.0
        self._spent_item: Any = None         # the one just clicked: pointed away from before it can be clicked again

    def step(self, now: float, landmarks: Optional[Sequence[Any]], aspect: float) -> bool:
        self.started = False
        # (looser once the mode is on: the hand relaxes while it waits on a file)
        k = shape(landmarks, aspect, self.tilt, self.right, keep=self.active) if landmarks is not None else ""
        if k:
            self._seen_t = now
            self._run = self._run + 1 if k == self._run_kind else 1
            self._run_kind = k
        else:
            self._run_kind, self._run = "", 0
        if not self.active:
            if k and self._run >= self.ENTER:
                self.active, self.started, self.kind = True, True, k
                self._anchor, self._spent_at, self.progress = None, None, 0.0
                self._item, self._spent_item = None, None
            return self.active
        if now - self._seen_t > self.LEAVE:
            self.reset()
            return False
        if k and k != self.kind and self._run >= self.SWITCH:
            self.kind = k
            self._anchor, self.progress = None, 0.0       # a new shape starts its own wait
            self._item = None
        return True

    def _dwell_item(self, now: float, item: Any) -> str:
        """The wait on one file / folder (`item` = what identifies it, None = none near the fingertip now)."""
        if item is not None and item == self._item:
            self._item_seen = now
        elif item is not None:
            self._item, self._since, self._item_seen = item, now, now       # another one: its own wait
            if item != self._spent_item:
                self._spent_item = None
        elif self._item is not None and now - self._item_seen > self.ITEM_GRACE:
            self._item, self._spent_item = None, None                         # pointed away: it may be clicked again
        if self._item is None or self._item == self._spent_item:
            self.progress = 0.0
            return ""
        self.progress = min(1.0, (now - self._since) / self.DWELL)
        if self.progress >= 1.0:
            self._spent_item, self.progress = self._item, 0.0
            return self.kind
        return ""

    def dwell(self, now: float, cursor: Tuple[float, float], on_target: Optional[bool], item: Any = None) -> str:
        """The click to send now ("double" / "right") or "". `item`: the file / folder at or around the fingertip
        (anything that is equal for the same one) - the wait is on that item, however the tip wanders. Without it
        (`on_target` only: a file is under the cursor, None = not known yet) the cursor has to rest on one spot.
        progress (0..1) is how full the wait is, for the ring."""
        if item is not None or self._item is not None:
            return self._dwell_item(now, item)
        if self._spent_at is not None:
            if math.dist(cursor, self._spent_at) < self.REARM_PX:
                self.progress = 0.0
                return ""
            self._spent_at = None
        if self._anchor is None or math.dist(cursor, self._anchor) > self.STILL_PX:
            self._anchor, self._since = cursor, now
        if on_target is not True:
            self._since = now                             # the wait runs only on a file / folder
            self.progress = 0.0
            return ""
        self.progress = min(1.0, (now - self._since) / self.DWELL)
        if self.progress >= 1.0:
            self._spent_at, self._anchor, self.progress = cursor, None, 0.0
            return self.kind
        return ""


# ---------------------------------------------------------------------------- what is under the cursor
FILE_WINDOWS = frozenset({"CabinetWClass", "ExploreWClass", "Progman", "WorkerW", "#32770"})   # Explorer, desktop, file dialogs


AREA_PX = 40          # a file / folder this near the fingertip counts (the tip need not be exactly on it)


def area_points(x: int, y: int, radius: int = AREA_PX) -> list:
    """The fingertip, then points around it at half the radius and at the radius: nearest first."""
    pts = [(x, y)]
    for r in (radius // 2, radius):
        d = int(round(r * .7071))
        pts += [(x + r, y), (x - r, y), (x, y + r), (x, y - r), (x + d, y + d), (x - d, y + d), (x + d, y - d), (x - d, y - d)]
    return pts


_USER32 = None


def _user32():
    """This module's OWN handle on user32. 2026-11-12, from the app's trace: setting argument types on the shared
    `ctypes.windll.user32` (GetAncestor) broke the uiautomation package's own calls to the same function - after four
    clicks every file check ended in "ArgumentError: argument 2 ... 'c_long' object cannot be interpreted as an integer"."""
    global _USER32
    if _USER32 is None:
        import ctypes
        from ctypes import wintypes
        user = ctypes.WinDLL("user32", use_last_error=True)
        user.WindowFromPoint.argtypes, user.WindowFromPoint.restype = [wintypes.POINT], wintypes.HWND
        user.GetAncestor.argtypes, user.GetAncestor.restype = [wintypes.HWND, ctypes.c_uint], wintypes.HWND
        user.GetParent.argtypes, user.GetParent.restype = [wintypes.HWND], wintypes.HWND
        user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        _USER32 = user
    return _USER32


IDC_HAND = 32649


def link_cursor() -> bool:
    """True while the mouse cursor is the "hand" (2026-11-12: "포인팅 모드가 링크 선택이나 웹페이지에서 탭할 수 있도록").
    Browsers and most programs show it over what a click follows: links, buttons of a web page, tabs of some apps.
    It needs no look into the page (the accessibility question "what is at this point" stops at any transparent
    window on top, as the file check found), only what Windows is drawing as the cursor. False where it cannot be
    asked. Not covered: things a program shows with the plain arrow (most native buttons, text fields)."""
    try:
        import ctypes
        from ctypes import wintypes

        class CURSORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD), ("hCursor", ctypes.c_void_p),
                        ("ptScreenPos", wintypes.POINT)]

        user = _user32()
        if not getattr(user, "_cursor_ready", False):
            user.GetCursorInfo.argtypes, user.GetCursorInfo.restype = [ctypes.POINTER(CURSORINFO)], wintypes.BOOL
            user.LoadCursorW.argtypes, user.LoadCursorW.restype = [wintypes.HINSTANCE, ctypes.c_void_p], ctypes.c_void_p
            user._cursor_ready = True
        info = CURSORINFO()
        info.cbSize = ctypes.sizeof(CURSORINFO)
        if not user.GetCursorInfo(ctypes.byref(info)) or not info.hCursor:
            return False
        return info.hCursor == user.LoadCursorW(None, ctypes.c_void_p(IDC_HAND))
    except Exception:
        return False


def link_item(cursor: Tuple[float, float], last: Any, radius: int) -> Any:
    """What the wait is on while the cursor is a hand: ("링크", a square of `radius` around where the hand cursor was
    first seen). The same square as long as the fingertip stays inside it, so a trembling tip keeps its wait; a tip
    that leaves it starts a new one there."""
    if last is not None and last[0] == LINK_NAME:
        left, top, right, bottom = last[1]
        if left <= cursor[0] <= right and top <= cursor[1] <= bottom:
            return last
    x, y, r = int(cursor[0]), int(cursor[1]), max(8, int(radius))
    return (LINK_NAME, (x - r, y - r, x + r, y + r))


LINK_NAME = "링크"


def window_under(x: int, y: int) -> Tuple[int, str]:
    """(handle of the window the MOUSE would reach at that point, class of its top-level window). Windows skips what
    lets clicks through (a transparent overlay, a tooltip); (0, "") where that cannot be asked."""
    try:
        import ctypes
        from ctypes import wintypes
        user = _user32()
        hwnd = user.WindowFromPoint(wintypes.POINT(int(x), int(y)))
        if not hwnd:
            return 0, ""
        root = user.GetAncestor(hwnd, 2) or hwnd            # GA_ROOT
        buf = ctypes.create_unicode_buffer(256)
        user.GetClassNameW(root, buf, 256)
        return int(hwnd), buf.value
    except Exception:
        return 0, ""


def window_parents(hwnd: int, limit: int = 4) -> list:
    """The window and up to `limit` of its parents, nearest first (the list of files may hang one level up)."""
    out = [int(hwnd)]
    try:
        user = _user32()
        for _ in range(limit):
            hwnd = user.GetParent(hwnd)
            if not hwnd:
                break
            out.append(int(hwnd))
    except Exception:
        pass
    return out


def item_at(items: Sequence[Tuple[str, Tuple[int, int, int, int]]], x: int, y: int) -> Any:
    """The (name, rectangle) whose rectangle holds the point, "" when none does."""
    for name, (left, top, right, bottom) in items:
        if left <= x < right and top <= y < bottom:
            return (name, (left, top, right, bottom))
    return ""


def item_near(items: Sequence[Tuple[str, Tuple[int, int, int, int]]], x: int, y: int, radius: int) -> Any:
    """The item the point is on or, failing that, the nearest one whose rectangle is within `radius` pixels of it."""
    best, best_d = "", float(radius) + 1e-6
    for name, (left, top, right, bottom) in items:
        dx = max(left - x, 0, x - (right - 1))
        dy = max(top - y, 0, y - (bottom - 1))
        d = math.hypot(dx, dy)
        if d == 0:
            return (name, (left, top, right, bottom))
        if d <= best_d:
            best, best_d = (name, (left, top, right, bottom)), d
    return best


# ---------------------------------------------------------------------------- links, buttons, menu entries
# 2026-11-12 ("포인팅 모드에서 이런 웹페이지 메뉴들도 선택할 수 있게", a YouTube side menu the label called "not a link"):
# the hand-cursor test (link_cursor) caught that menu for one frame in a whole try - the trace has one "link" line and
# then 25 without, the cursor resting on the entry. Why the hand cursor went away there is not known. So the thing
# under the fingertip is asked for itself: Windows' accessibility interface gives the element the MOUSE reaches at a
# point (AccessibleObjectFromPoint goes through the window the mouse reaches, so the transparent overlays that stopped
# UI Automation's point question do not stop it), with its role, name and rectangle. An element that is clicked - a
# link, a button, a menu entry, a tab, a list entry, a text box - is the target; a text or picture inside one counts
# as that one (its parents are looked at, TAP_PARENTS up).
TAP_ROLES = {12: "메뉴", 30: "링크", 34: "목록 항목", 36: "목록 항목", 37: "탭", 42: "입력 칸", 43: "단추", 44: "체크 상자",
             45: "선택 단추", 46: "선택 상자", 56: "단추", 57: "단추", 62: "단추"}
TAP_PARENTS = 4
TAP_MAX_W, TAP_MAX_H = 1200, 400         # larger than this is a region, not something to tap
TAP = "tap"
_ACC: dict = {}


def accessible_at(x: int, y: int) -> Any:
    """(name, (left, top, right, bottom), TAP, what) of the clickable element the mouse reaches at that point, or
    None. Must run off the camera loop (it asks another program and may take a moment); COM is set up by the caller."""
    import ctypes
    from ctypes import wintypes
    if not _ACC:
        import comtypes.client
        from comtypes.automation import VARIANT
        from src.uia import _LOCK
        with _LOCK:                                   # comtypes writes its wrapper module on first use
            module = comtypes.client.GetModule("oleacc.dll")
        dll = ctypes.OleDLL("oleacc")
        dll.AccessibleObjectFromPoint.argtypes = [wintypes.POINT, ctypes.POINTER(ctypes.POINTER(module.IAccessible)),
                                                  ctypes.POINTER(VARIANT)]
        _ACC.update(dll=dll, iface=module.IAccessible, variant=VARIANT)
    iface, variant = _ACC["iface"], _ACC["variant"]
    acc = ctypes.POINTER(iface)()
    child = variant()
    _ACC["dll"].AccessibleObjectFromPoint(wintypes.POINT(int(x), int(y)), ctypes.byref(acc), ctypes.byref(child))
    if not acc:
        return None
    node, part = acc, child
    for _ in range(TAP_PARENTS + 1):
        try:
            role = node.accRole(part)
        except Exception:
            role = None
        if isinstance(role, int) and role in TAP_ROLES:
            try:
                left, top, width, height = node.accLocation(part)
            except Exception:
                return None
            if width <= 0 or height <= 0 or width > TAP_MAX_W or height > TAP_MAX_H:
                return None
            try:
                name = str(node.accName(part) or "").strip()
            except Exception:
                name = ""
            what = TAP_ROLES[role]
            return (name[:60] or what, (int(left), int(top), int(left + width), int(top + height)), TAP, what)
        try:
            if getattr(part, "value", 0):
                part = variant(0)                     # a simple child: next, the object that holds it
                continue
            parent = node.accParent
            node = parent.QueryInterface(iface) if parent is not None else None
        except Exception:
            node = None
        if node is None:
            break
    return None


# The same question through UI Automation, for the programs that answer it only that way. Measured 2026-11-12 on a
# test page in Chrome: the accessibility interface above gave "Chrome Legacy Window" for every point of the page
# (Chrome does not open a page's contents to it unasked), while the window's UI Automation tree had the page's links,
# buttons and text boxes with their rectangles from the second look on (the first look makes Chrome switch them on).
# The tree is not asked "what is at this point" (that question stops at a transparent window on top): it is walked
# down from the window the mouse reaches, into the children whose rectangle holds the point.
TAP_TYPES = {"HyperlinkControl": "링크", "ButtonControl": "단추", "MenuItemControl": "메뉴", "TabItemControl": "탭",
             "ListItemControl": "목록 항목", "TreeItemControl": "목록 항목", "EditControl": "입력 칸",
             "CheckBoxControl": "체크 상자", "RadioButtonControl": "선택 단추", "ComboBoxControl": "선택 상자",
             "SplitButtonControl": "단추"}
TAP_NODES = 1500             # elements looked at in one walk, at most
TAP_SECONDS = .6             # ... and time spent on it


def window_root(hwnd: int) -> int:
    try:
        return int(_user32().GetAncestor(hwnd, 2) or hwnd)        # GA_ROOT
    except Exception:
        return int(hwnd)


def uia_tap_at(auto: Any, hwnd: int, x: int, y: int, radius: int = 0) -> Any:
    """(name, rectangle, TAP, what) of the clickable element of that window at the point - the smallest one holding
    it, else the nearest within `radius` - or None. `auto`: the uiautomation module, set up for this thread."""
    def reach(r) -> float:
        dx = max(r.left - x, 0, x - r.right)
        dy = max(r.top - y, 0, y - r.bottom)
        return math.hypot(dx, dy)

    best = None
    started, looked = time.monotonic(), 0
    stack = [auto.ControlFromHandle(window_root(hwnd))]
    while stack and looked < TAP_NODES and time.monotonic() - started < TAP_SECONDS:
        ctrl = stack.pop()
        if ctrl is None:
            continue
        for child in ctrl.GetChildren():
            looked += 1
            r = child.BoundingRectangle
            width, height = r.right - r.left, r.bottom - r.top
            empty = width <= 0 or height <= 0
            if not empty and reach(r) > radius:
                continue                              # the point is not in or around it: nor in what it holds
            kind = child.ControlTypeName
            if not empty and kind in TAP_TYPES and width <= TAP_MAX_W and height <= TAP_MAX_H:
                rank = (reach(r), width * height)
                if best is None or rank < best[0]:
                    what = TAP_TYPES[kind]
                    best = (rank, (str(child.Name or "").strip()[:60] or what,
                                   (int(r.left), int(r.top), int(r.right), int(r.bottom)), TAP, what))
            stack.append(child)
    return best[1] if best is not None else None


def is_tap(item: Any) -> bool:
    """True for a link / button / menu entry (one click), False for a file or folder (the click connected to it)."""
    return isinstance(item, tuple) and len(item) >= 3 and item[2] == TAP


def tap_point(item: Any, cursor: Tuple[float, float]) -> Tuple[int, int]:
    """Where to click an element: where the fingertip is when that is on it, else the nearest spot inside it."""
    left, top, right, bottom = item[1]
    pad = lambda lo, hi, v: int(min(max(v, lo + min(3, (hi - lo) // 2)), hi - min(3, (hi - lo) // 2)))   # noqa: E731
    return pad(left, right, cursor[0]), pad(top, bottom, cursor[1])


def cursor_name() -> str:
    """The mouse cursor Windows is drawing now, for the trace: "hand", "arrow", "text" or its handle."""
    try:
        import ctypes
        from ctypes import wintypes

        class CURSORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD), ("hCursor", ctypes.c_void_p),
                        ("ptScreenPos", wintypes.POINT)]

        user = _user32()
        link_cursor()                                  # (sets the argument types once)
        info = CURSORINFO()
        info.cbSize = ctypes.sizeof(CURSORINFO)
        if not user.GetCursorInfo(ctypes.byref(info)):
            return "?"
        for number, name in ((32649, "hand"), (32512, "arrow"), (32513, "text")):
            if info.hCursor == user.LoadCursorW(None, ctypes.c_void_p(number)):
                return name
        return hex(info.hCursor or 0)
    except Exception:
        return "?"


def uia_file_probe(radius_of: Callable[[], int] = lambda: AREA_PX) -> Callable[[int, int], Any]:
    """(x, y) -> (name, (left, top, right, bottom)) of the file / folder item at that point or, failing that, the
    nearest one within `radius_of()` pixels of it; "" when there is none.

    How (2026-11-12, after two traces of "it worked a few times, then never"): Windows is asked which window the MOUSE
    reaches at the point; when that is a file window (desktop, Explorer, a file dialog) the point is looked up among
    that window's own items, listed once a second. The earlier way asked UI Automation "what is at this point" 17
    times per check - that question stops at the first window whatever it lets through (the graphics driver's
    full-screen overlay answered "a document" for a desktop file) and each of those answers took a fifth of a second,
    so one check took seconds and was stale by the time it came (the label stayed at "파일 확인 중…")."""
    import uiautomation as auto

    auto.SetGlobalSearchTimeout(0)
    listed: dict = {}                          # window handle -> (when, its file items): asked at most once a second

    def items_of(hwnd: int) -> list:
        """Every list item (file / folder) in that window, with its rectangle."""
        hit = listed.get(hwnd)
        if hit is not None and time.monotonic() - hit[0] < 1.0:
            return hit[1]
        out: list = []
        stack = [(auto.ControlFromHandle(hwnd), 0)]
        while stack and len(out) < 3000:
            ctrl, depth = stack.pop()
            if ctrl is None:
                continue
            for child in ctrl.GetChildren():
                kind = child.ControlTypeName
                if kind == "ListItemControl":
                    r = child.BoundingRectangle
                    out.append((str(child.Name or "?"), (int(r.left), int(r.top), int(r.right), int(r.bottom))))
                elif depth < 5 and kind in ("ListControl", "PaneControl", "GroupControl", "WindowControl", "CustomControl"):
                    stack.append((child, depth + 1))
        if len(listed) > 8:
            listed.clear()
        listed[hwnd] = (time.monotonic(), out)
        return out

    def probe(x: int, y: int):
        hwnd, cls = window_under(x, y)
        probe.seen = "mouse reaches " + (cls or "?")
        if not hwnd or cls not in FILE_WINDOWS:
            # not a file window: a link, a button or a menu entry under the fingertip (2026-11-12)
            found = None
            try:
                if hwnd and getattr(probe, "taps", lambda: True)():
                    found = uia_tap_at(auto, hwnd, int(x), int(y), max(0, int(radius_of()))) or accessible_at(int(x), int(y))
            except Exception as exc:
                probe.seen += f" · tap error {type(exc).__name__}: {exc}"[:120]
                return ""
            if found is not None:
                probe.seen += f" · {found[3]}"
                return found
            return ""
        radius = max(0, int(radius_of()))
        for handle in window_parents(hwnd):        # the window under the point, else the one that holds the list
            try:
                items = items_of(handle)
            except Exception as exc:               # a window that went away or does not answer
                probe.seen += f" · error {type(exc).__name__}: {exc}"[:120]
                continue
            if items:
                probe.seen += f" · {len(items)} items"
                return item_near(items, int(x), int(y), radius)
        probe.seen += " · no items"
        return ""

    probe.seen = ""
    return probe


class FileTargetProbe:
    """Asks UI Automation, in its own thread, what is under the cursor. ask() from the camera loop is free; answer()
    gives True / False for a point near the last asked one, None while unknown."""

    NEAR_PX = 12
    REFRESH = .4          # s after which a found item is looked up again (the window may have scrolled or closed)

    def __init__(self, probe_factory: Callable[[], Callable[[int, int], str]] = uia_file_probe) -> None:
        self._factory = probe_factory
        self.area_px = AREA_PX               # the settings window's "around the fingertip" (src/point_mode.SETTINGS)
        self.taps = True                     # also look for links / buttons / menu entries outside file windows
        self.available = sys.platform == "win32"
        self._want: Optional[Tuple[int, int]] = None
        self._have: Optional[Tuple[Tuple[int, int], str]] = None
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # for the person and the trace (2026-11-11: "아무리 오래 파일에 검지끝을 두어도 … 작동을 안한다" and nothing said why)
        self.error = ""                      # why the check could not start (then it never answers)
        self.seen = ""                       # what Windows said was at the last asked point
        self.asked = 0
        self.answered = 0

    def state(self, x: float, y: float) -> str:
        """"off" (the check cannot run) | "file" | "none" (asked: no file / folder there) | "asking" (no answer yet)."""
        if not self.available:
            return "off"
        if self.target(x, y) is not None:
            return "file"
        got = self.answer(x, y)
        return "asking" if got is None else "file" if got else "none"

    def ask(self, x: float, y: float) -> None:
        p = (int(round(x)), int(round(y)))
        have = self._have
        fresh = time.monotonic() - getattr(self, "_have_t", 0.0) < self.REFRESH
        # 2026-11-11 report ("아무리 오래 파일에 검지끝을 두어도 포인팅모드 더블클릭이 작동을 안한다"): an answer for a point
        # this near was kept for ever. A "no file here" given once - the element could not be read that moment, a window
        # was over the file - then stood for as long as the fingertip rested there, which is exactly what the person
        # does to click. Every answer, yes or no, is asked again after REFRESH.
        if have is not None and fresh and abs(have[0][0] - p[0]) + abs(have[0][1] - p[1]) <= self.NEAR_PX:
            return
        if self.target(x, y) is not None and fresh:
            return                             # still on / around the item that was found: no need to ask again yet
        self._want = p
        self.asked += 1
        self._wake.set()
        if self._thread is None and self.available:
            self._thread = threading.Thread(target=self._run, name="point-target", daemon=True)
            self._thread.start()

    def answer(self, x: float, y: float) -> Optional[bool]:
        have = self._have
        if have is None or abs(have[0][0] - x) + abs(have[0][1] - y) > self.NEAR_PX:
            return None
        return bool(have[1])

    def target(self, x: float, y: float) -> Any:
        """(name, rectangle) of the file / folder the point is on or within AREA_PX of, as last found; None when there
        is none there (or the probe gives names only: then `answer` says whether the point is on a file)."""
        have = self._have
        if have is None or not isinstance(have[1], tuple):
            return None
        left, top, right, bottom = have[1][1]
        a = self.area_px
        if left - a <= x <= right + a and top - a <= y <= bottom + a:
            return have[1]
        return None

    @property
    def name(self) -> str:
        found = self._have[1] if self._have else ""
        return found[0] if isinstance(found, tuple) else found

    def _run(self) -> None:
        try:
            import uiautomation as auto
            ctx = auto.UIAutomationInitializerInThread()          # noqa: F841 (kept alive for the thread)
            from src.uia import create_client
            create_client()
            try:
                probe = self._factory(lambda: self.area_px)
            except TypeError:                                     # a factory without the radius (tests)
                probe = self._factory()
            try:
                probe.taps = lambda: self.taps
            except Exception:
                pass
        except Exception as exc:                                  # no UI Automation: the dwell never clicks
            print(f"[pointing mode] file check disabled: {exc}", file=sys.stderr)
            self.error = f"{type(exc).__name__}: {exc}"[:200]
            self.available = False
            return
        while not self._stop.is_set():
            self._wake.wait(.5)
            self._wake.clear()
            p = self._want
            if p is None:
                continue
            try:
                found = probe(*p)
                self.seen = str(getattr(probe, "seen", ""))
            except Exception as exc:
                found = ""
                self.seen = f"error {type(exc).__name__}: {exc}"[:120]
            self.answered += 1
            self._have = (p, found)
            self._have_t = time.monotonic()
            time.sleep(.03)

    def shutdown(self) -> None:
        self._stop.set()
        self._wake.set()
