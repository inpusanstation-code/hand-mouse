"""The control hand drawn on the screen, at the cursor (2026-11-10).

The rule engine still moves the cursor (movement scaling, clutch, pinches all unchanged). The drawn hand is placed so that its THUMB TIP
is exactly at the cursor: every click pinch closes a finger onto the thumb, so the point between the pinching fingers is where the click
lands. Size is fixed on screen, so a far, small hand is drawn as large as a near one.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional, Sequence, Tuple

SIZE_PX = 110.0          # wrist -> middle-finger knuckle on the screen (logical pixels)
THUMB_TIP = 4
ACTION_NAMES = {"left_click": "좌클릭", "right_click": "우클릭", "drag_hold": "끌기", "scroll_grab": "스크롤", "task_switcher": "창 전환",
                "show_desktop": "바탕화면"}


def view(landmarks: Sequence[Any], width: int, height: int, guides: Sequence[Tuple[str, str]] = (), action: str = "none",
         size_px: float = SIZE_PX) -> Optional[Dict[str, Any]]:
    """21 points relative to the thumb tip, in screen pixels: [x0, y0, x1, y1, ...]. None when the hand box is degenerate."""
    if len(landmarks) != 21:
        return None
    pts = [(p.x * width, p.y * height) for p in landmarks]
    size = math.dist(pts[0], pts[9])
    if size < 1.0:
        return None
    k = size_px / size
    ox, oy = pts[THUMB_TIP]
    flat = []
    for x, y in pts:
        flat += [round((x - ox) * k, 1), round((y - oy) * k, 1)]
    return {"pts": flat, "guides": [[f, s] for f, s in guides], "action": ACTION_NAMES.get(action, "")}
