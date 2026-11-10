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
| `virtual_hand.scroll`        | begin / hold / end | a fist; sideways moves the page (right = down by default)   | `mouse.scroll` (x`scroll_speed`, 0.25) |
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
from manux.features.virtual_hand.shapes import (SIZE_PX, BoxMapper, Grip, HandDrawer, ShapePinch, ShapeSwitch, ShapeTriple,
                                                ViewSmoother, is_fist, palm_centre,
                                                pinch_point, safe_box, valid_box)

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
    SCROLL: "mouse.scroll", SWITCH: "window.task_switcher",      # scroll speed: the scroll_speed setting (Intent.scale)
}
FIST_GAP = .5                             # s around a fist without a right click (the tips meet while it forms / opens)
NEAR = .45                                # thumb-index ratio drawn as "near" (approaching a pinch) on the screen hand
LABEL_SECONDS = .8                        # the action's name stays this long on the drawn hand (hand-mouse branch)

SETTINGS = {
    f"{ID}.box_left": .2, f"{ID}.box_top": .15, f"{ID}.box_right": .8, f"{ID}.box_bottom": .85,  # camera image, 0..1
    f"{ID}.pinch_hold": .45,          # s thumb + index stay closed before it is a drag instead of a click
    f"{ID}.double_tap": .7,           # s after a click in which the next close is the second click
    f"{ID}.scroll_follows_page": False,   # False: fist right = page down (the source's default)
    f"{ID}.scroll_speed": .25,            # fist browsing speed (x the scroll gain); 2026-11-10: .5 was too fast
    f"{ID}.draw_size": 160.0,             # logical px wrist -> middle knuckle of the drawn hand; 2026-11-10: 110 was too small
    f"{ID}.hand_crop": True,              # look at the hand at full resolution in this mode (tracking.hand_crop for all modes)
    f"{ID}.pinch_shape": True,            # click only on the person's pinch hand shape (their model; none: contact alone)
    f"{ID}.pinch_shape_min": .4,          # how sure the pinch-shape model must be (0..1); 2026-11-10 replay: .4
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
        self.drawer = HandDrawer()
        self.last_view: Optional[dict] = None      # the hand to draw on the screen (read by the UI, never by others)
        self.shape_model = None                    # perception.pinch_shape.PinchShapeModel (set by the composition root)
        self.shape_score: Optional[float] = None   # last pinch-shape score (diagnostics)
        self._fist_t = float("-inf")               # last frame that looked like a fist (no right click near it)
        self._label, self._label_until = "", float("-inf")   # the last action's name on the drawn hand (0.8 s)
        self.reset("init")

    # ------------------------------------------------------------------ Feature protocol
    def reset(self, reason: str) -> None:
        for part in (self.box, self.pinch, self.triple, self.switch, self.grip, self.smoother, self.drawer):
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
        box = safe_box((s.get("box_left", .2), s.get("box_top", .15), s.get("box_right", .8), s.get("box_bottom", .85)))
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

        fist = is_fist(lm, hand.world)
        grip = self.grip.step(fist, t)
        if fist or grip:
            self._fist_t = t
        pinch_evt = right_evt = None
        if not grip:
            quick = self._last_tap is not None and t - self._last_tap[0] <= double_tap
            # a fist forming or opening brings the three tips together for a moment: no right click within FIST_GAP s
            right_evt = self.triple.step(lm, w, h, hand.world, allowed=t - self._fist_t > FIST_GAP)
            if right_evt == "down" or (self.triple.closed and self.pinch.closed):
                self._triple_press = True         # the index got there first: that press is the right click now
            if right_evt == "up":
                self._triple_open_t = t
            settling = self.triple.closed or t - self._triple_open_t < .3   # the middle leaving looks like thumb + index
            pinch_evt = None if settling and not self.pinch.closed else self.pinch.step(
                lm, w, h, frames=1 if quick else None, shape_ok=self._pinch_shape(hand, s))
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
        draw_size = min(400.0, max(60.0, float(s.get("draw_size", SIZE_PX))))
        drawn = self.drawer(lm, hand.world, w, h, size_px=draw_size, now=t)   # the picture's shape, a steady size
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
                              "grip": bool(grip), "lost": False, "size": draw_size,
                              "guides": self._guides(lm, w, h, dragging_now, tap, right_evt),
                              "action": self._action_label(t, grip, dragging_now, tap or second is not None, right_evt)}
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
            speed = max(.01, float(s.get("scroll_speed", .25)))
            out.append(Intent(t, ID, SCROLL, "hold" if self._scrolling else "begin", point=scroll_point, scale=speed))
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
            self._label, self._label_until = "창 전환", t + LABEL_SECONDS
            if self.last_view is not None:
                self.last_view["action"] = self._label
        return out

    # ------------------------------------------------------------------ helpers
    def _guides(self, lm, w, h, dragging: bool, tap: bool, right_evt) -> List[List[str]]:
        """Thumb -> finger lines on the drawn hand, as in the hand-mouse branch: near (approaching), pinched, action."""
        if self.grip.on:
            return []
        out = []
        index = "action" if tap or dragging else "pinched" if self.pinch.closed else \
            "near" if self.pinch.ratio < NEAR else None
        if self.triple.closed or right_evt == "down":
            out += [["index", "action" if right_evt == "down" else "pinched"],
                    ["middle", "action" if right_evt == "down" else "pinched"]]
        elif index is not None:
            out.append(["index", index])
        return out

    def _action_label(self, t: float, grip: bool, dragging: bool, click: bool, right_evt) -> str:
        """The action's name next to the click point, kept LABEL_SECONDS after it fired (hand-mouse branch)."""
        name = ("스크롤" if grip else "끌기" if dragging else "좌클릭" if click else "우클릭" if right_evt == "down" else "")
        if name:
            self._label, self._label_until = name, t + (0.0 if grip or dragging else LABEL_SECONDS)
            return name
        return self._label if t <= self._label_until else ""

    def _pinch_shape(self, hand: HandObservation, s) -> bool:
        """The whole hand is the person's pinch shape (their own model), not just two fingertips touching.
        No model, no world joints or virtual_hand.pinch_shape off: contact alone decides, as before."""
        self.shape_score = None
        if self.shape_model is None or self.pinch.closed or not s.get("pinch_shape", True):
            return True
        self.shape_score = self.shape_model.score(hand.world)
        if self.shape_score is None:
            return True
        return self.shape_score >= float(s.get("pinch_shape_min", self.shape_model.threshold))

    def _close_spans(self, t: float, out: List[Intent]) -> None:
        if self._dragging:
            out.append(Intent(t, ID, DRAG, "end"))
        if self._scrolling:
            out.append(Intent(t, ID, SCROLL, "end"))
        if self._dragging or self._scrolling:
            self._last_release_t = t
        self._dragging = self._scrolling = False
        self._since = None
