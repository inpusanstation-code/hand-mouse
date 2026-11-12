"""How the hand skeletons are drawn (2026-11-12, "스켈레톤 색깔을 유저가 정할수 있게 설정에 옵션을 줘. 스켈레톤 색깔이랑 투명도 등").

Two places draw a hand: the camera preview (src/HandSkeleton.qml: the control hand and the other hand) and the virtual hand
on the desktop (dashboard.qml `virtualHandWindow`). The settings window picks their colours, how opaque they are and how
thick the lines are; the values live in QSettings "skeletonStyle" (JSON, per profile like the other screen options).
Drawing only: nothing here changes what is recognised. The pinch lines (amber / green / red) and the fist's amber keep
their colours, they are signals.
"""
from __future__ import annotations

import re
from typing import Any, Dict

DEFAULTS: Dict[str, Any] = {
    "main": "#46E5BD",          # preview: the control hand (the theme's mint)
    "other": "#D946EF",         # preview: the other hand (src/other_hand_motion.py)
    "vh_line": "#F5F7F8",       # desktop virtual hand: the bones
    "vh_joint": "#46E5BD",      # desktop virtual hand: the joints
    "preview_alpha": 1.0,       # 0.2 .. 1: how opaque the preview skeletons are
    "vh_alpha": 1.0,            # 0.2 .. 1: how opaque the desktop virtual hand is
    "width": 1.0,               # 0.5 .. 2.5: line thickness, times the usual
}
RANGES = {"preview_alpha": (0.2, 1.0), "vh_alpha": (0.2, 1.0), "width": (0.5, 2.5)}
COLOR_KEYS = ("main", "other", "vh_line", "vh_joint")
PRESETS = ["#46E5BD", "#2FBF8F", "#38BDF8", "#3B82F6", "#D946EF", "#A78BFA", "#F472B6", "#F2B544", "#F97316",
           "#EF4444", "#F5F7F8", "#94A3B8", "#112331"]
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def color(value: Any) -> str:
    """'#RRGGBB' (upper case) or '' when it is not one ('46e5bd' without the # is taken too)."""
    text = str(value or "").strip()
    if text and not text.startswith("#"):
        text = "#" + text
    return text.upper() if _HEX.match(text) else ""


def clean(values: Any) -> Dict[str, Any]:
    """Every key, each a valid value (anything unreadable falls back to the default)."""
    values = values if isinstance(values, dict) else {}
    out = dict(DEFAULTS)
    for key in COLOR_KEYS:
        out[key] = color(values.get(key)) or DEFAULTS[key]
    for key, (low, high) in RANGES.items():
        try:
            out[key] = round(min(high, max(low, float(values.get(key, DEFAULTS[key])))), 2)
        except (TypeError, ValueError):
            out[key] = DEFAULTS[key]
    return out
