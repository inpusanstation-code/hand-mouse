"""Feature `virtual_hand`: a box on the camera image is the whole monitor; the hand's shape clicks (from virtual-hand-20261110).

Where the palm centre is inside the box is where the cursor is (no relative movement, no speed scaling). In this mode
the pinch rules are not running at all (the mode is its own); only these hand shapes act:

| gesture id                   | phase              | hand                                                        | action (default)       |
| ---------------------------- | ------------------ | ----------------------------------------------------------- | ---------------------- |
| `virtual_hand.place`         | hold               | the palm in the box                                         | `mouse.place`          |
| `virtual_hand.left_click`    | tap                | thumb + index closed, opened again before `pinch_hold`      | `mouse.left_click`     |
| (double click)               | tap                | a second close within `double_tap` s: same point, at once   | `mouse.left_click`     |
| `virtual_hand.drag`          | begin / hold / end | thumb + index kept closed `pinch_hold` s, until it opens    | `mouse.drag`           |
| `virtual_hand.right_click`   | tap                | thumb, index and middle together                            | `mouse.right_click`    |
| `virtual_hand.scroll`        | begin / hold / end | a fist; sideways moves the page (right = down by default)   | `mouse.scroll` (x0.5)  |
| `virtual_hand.task_switcher` | tap                | thumb folded, four fingers up, held still 0.5 s             | `window.task_switcher` |

While a click finger is closed the point holds where the hand aimed (0.15 s before the touch, if that was only the tilt of
the closing fingers). The cursor is the clicking point and maps the box onto the monitor edge to edge; the hand drawn on
the screen is shifted so that its thumb-index point sits on the cursor (2026-11-10: the source's per-click offset from
the palm made the cursor jump when the fingers met and kept clicks off the right and bottom edges).

Differences from the source: its fist came from the rule engine (`active_gesture == "fist"`); features do not import
each other here, so `shapes.is_fist` judges it from the shape. Its F-key click log and TCN click check are not ported.
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from manux.core.contracts import Activity, FrameContext, HandObservation, Intent
from manux.features.virtual_hand.shapes import (BoxMapper, Grip, ShapePinch, ShapeSwitch, ShapeTriple,
                                                OneEuro, ViewSmoother, hand_size_px, is_fist, palm_centre,
                                                pinch_point, valid_box, view_points)

__all__ = ["ID", "MODE", "GESTURES", "GESTURE_PHASES", "DEFAULT_BINDINGS", "SETTINGS", "VirtualHandFeature"]

ID = MODE = "virtual_hand"
PLACE, LEFT, RIGHT, DRAG, SCROLL, SWITCH = (f"{ID}.{n}" for n in
                                           ("place", "left_click", "right_click", "drag", "scroll", "task_switcher"))
GESTURES: Tuple[str, ...] = (PLACE, LEFT, RIGHT, DRAG, SCROLL, SWITCH)
GESTURE_PHASES = {
    PLACE: frozenset({"hold"}), LEFT: frozenset({"tap"}), RIGHT: frozenset({"tap"}),
    DRAG: frozenset({"begin", "hold", "end"}), SCROLL: frozenset({"begin", "hold", "end"}), SWITCH: frozenset({"tap"}),
}
DEFAULT_BINDINGS = {
    PLACE: "mouse.place", LEFT: "mouse.left_click", RIGHT: "mouse.right_click", DRAG: "mouse.drag",
    SCROLL: {"action": "mouse.scroll", "params": {"gain": .5}}, SWITCH: "window.task_switcher",
}
SETTINGS = {
    f"{ID}.box_left": .2, f"{ID}.box_top": .15, f"{ID}.box_right": .8, f"{ID}.box_bottom": .85,  # camera image, 0..1
    f"{ID}.pinch_hold": .45,          # s thumb + index stay closed before it is a drag instead of a click
    f"{ID}.double_tap": .7,           # s after a click in which the next close is the second click
    f"{ID}.scroll_follows_page": False,   # False: fist right = page down (the source's default)
}


class VirtualHandFeature:
    id = ID
    modes = frozenset({MODE})
    gestures = GESTURES

    def __init__(self) -> None:
        self.box = BoxMapper()
        self.pinch = ShapePinch("index")
        self.triple = ShapeTriple()
        self.switch = ShapeSwitch()
        self.grip = Grip()
        self.smoother = ViewSmoother()
        self.size_filter = OneEuro(.3, .002)       # the drawn hand's scale changes slowly, never in one frame
        self.last_view: Optional[dict] = None      # the hand to draw on the screen (read by the UI, never by others)
        self.reset("init")

    # ------------------------------------------------------------------ Feature protocol
    def reset(self, reason: str) -> None:
        for part in (self.box, self.pinch, self.triple, self.switch, self.grip, self.smoother, self.size_filter):
            part.reset()
        self._since: Optional[float] = None       # when thumb + index closed (this press)
        self._dragging = False
        self._scrolling = False
        self._double = False                      # this press is a double click's second click
        self._triple_press = False                # this press became a right click
        self._triple_open_t = float("-inf")
        self._last_tap: Optional[Tuple[float, Tuple[float, float], Optional[List[float]]]] = None
        self._anchor: Optional[List[float]] = None  # drawn-hand px of the thumb-index point (the cursor sits there)
        self.last_view = None
        self._last_release_t = getattr(self, "_last_t", float("-inf"))
        self._last_t = float("-inf")

    def activity(self) -> Activity:
        return Activity(holding=self._dragging or self._scrolling, last_release_t=self._last_release_t)

    def step(self, hand: Optional[HandObservation], ctx: FrameContext) -> Sequence[Intent]:
        t = ctx.frame.t
        self._last_t = t
        s = ctx.settings
        box = (s.get("box_left", .2), s.get("box_top", .15), s.get("box_right", .8), s.get("box_bottom", .85))
        out: List[Intent] = []
        if hand is None or not valid_box(box):
            self._close_spans(t, out)
            self.pinch.reset()
            self.triple.reset()
            if self.last_view is not None:
                self.last_view = {**self.last_view, "lost": True}   # the UI fades it, then hides it
            return out
        lm, w, h = hand.landmarks, hand.frame.width, hand.frame.height
        pinch_hold, double_tap = float(s.get("pinch_hold", .45)), float(s.get("double_tap", .7))

        grip = self.grip.step(is_fist(lm), t)
        pinch_evt = right_evt = None
        if not grip:
            quick = self._last_tap is not None and t - self._last_tap[0] <= double_tap
            right_evt = self.triple.step(lm, w, h)
            if right_evt == "down" or (self.triple.closed and self.pinch.closed):
                self._triple_press = True         # the index got there first: that press is the right click now
            if right_evt == "up":
                self._triple_open_t = t
            settling = self.triple.closed or t - self._triple_open_t < .3   # the middle leaving looks like thumb + index
            pinch_evt = None if settling and not self.pinch.closed else self.pinch.step(lm, w, h, frames=1 if quick else None)
        else:
            self.pinch.reset()
            self.triple.reset()
            self._since, self._double, self._triple_press = None, False, False

        second = None
        if pinch_evt == "down":
            self._since = t
            if self._last_tap is not None and t - self._last_tap[0] <= double_tap:
                second = self._last_tap[1]
                self._since, self._double = None, True
            self._last_tap = None
        # held closed long enough: a drag, not a click (stays a drag until the fingers open)
        dragging_now = self.pinch.closed and self._since is not None and t - self._since >= pinch_hold \
            and not self._triple_press and not self.triple.closed
        tap = pinch_evt == "up" and not self._dragging and not dragging_now and not self._double and not self._triple_press
        if pinch_evt == "up" or (not self.pinch.closed and not self.triple.closed):
            self._since, self._double, self._triple_press = None, False, False

        aiming = (self.pinch.closed and not dragging_now and not self._dragging) or tap or self.triple.closed
        point = self.box.target(lm, box, hold=grip or aiming, now=t, aim=not grip)
        if second is not None:
            point = second                         # exactly the first click's point: Windows pairs them

        # ---- the drawn hand. The cursor IS the clicking point (box edge = monitor edge, no jump when the fingers
        # meet: the old per-click offset caused 18.5 jumps >= 60 px a minute in the 2026-11-10 replay). The drawing is
        # shifted so that its thumb-index point (`anchor`, slowly followed, frozen while clicking) sits on the cursor.
        size = hand_size_px(lm, w, h, hand.world)
        drawn = view_points(lm, w, h, hand_px=self.size_filter((size,), t)[0] if size else None)
        if drawn is not None:
            drawn = self.smoother(drawn, t)
        engaged = (self.pinch.closed or self.triple.closed or dragging_now or self._dragging or tap
                   or right_evt == "down" or pinch_evt == "up")
        if drawn is not None:
            aim_px = pinch_point(drawn, "index")
            if self._anchor is None:
                self._anchor = list(aim_px)
            elif not engaged and not grip:
                self._anchor = [a + .15 * (b - a) for a, b in zip(self._anchor, aim_px)]
            self.last_view = {"pts": drawn, "anchor": [round(v, 1) for v in self._anchor], "aim": not engaged,
                              "grip": bool(grip), "lost": False}
        offset = None

        # ---- spans first: a drag or a scroll that should end ends before anything new starts
        if self._dragging and not (self.pinch.closed and not self.triple.closed):
            out.append(Intent(t, ID, DRAG, "end"))
            self._dragging = False
            self._last_release_t = t
        if self._scrolling and not grip:
            out.append(Intent(t, ID, SCROLL, "end"))
            self._scrolling = False
            self._last_release_t = t

        out.append(Intent(t, ID, PLACE, "hold", point=point, offset=offset))
        if grip:
            cx, _ = palm_centre(lm)
            follows = bool(s.get("scroll_follows_page", False))
            scroll_point = (.5, cx if follows else 1.0 - cx)   # sideways is easier than up and down
            out.append(Intent(t, ID, SCROLL, "hold" if self._scrolling else "begin", point=scroll_point))
            self._scrolling = True
        elif dragging_now:
            out.append(Intent(t, ID, DRAG, "hold" if self._dragging else "begin"))
            self._dragging = True
        elif tap or second is not None:
            out.append(Intent(t, ID, LEFT, "tap"))
            self._last_tap = (t, point, offset) if tap else None
        elif right_evt == "down":
            out.append(Intent(t, ID, RIGHT, "tap"))
        elif not self.pinch.closed and not self.triple.closed and self.switch.step(lm, w, h, t):
            out.append(Intent(t, ID, SWITCH, "tap"))
        return out

    # ------------------------------------------------------------------ helpers
    def _close_spans(self, t: float, out: List[Intent]) -> None:
        if self._dragging:
            out.append(Intent(t, ID, DRAG, "end"))
        if self._scrolling:
            out.append(Intent(t, ID, SCROLL, "end"))
        if self._dragging or self._scrolling:
            self._last_release_t = t
        self._dragging = self._scrolling = False
        self._since = None
