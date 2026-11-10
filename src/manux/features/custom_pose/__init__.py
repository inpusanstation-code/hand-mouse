"""Feature `custom_pose`: gestures the person registered from a few demonstrations (perception/pose_memory.py).

Eight fixed slots, `custom_pose.slot1` .. `slot8`, each a `tap` when its pose has won RUN_FRAMES frames in a row (once
per hold; the pose must change before it fires again). The slots are **unbound by default** (D-004: a gesture without
a binding does nothing); the person picks the command for each, saved as a binding. The memory is swapped in by the
composition root (`set_memory`) when a gesture is added or removed; the feature itself reads no files.

It runs in every cursor mode next to the mode's own feature. The source paused the cursor while a registered gesture
was being made; features here cannot stop each other, so the cursor keeps moving (noted in the merge record).
"""
from __future__ import annotations

from typing import Optional, Sequence, Tuple

from manux.core.contracts import Activity, FrameContext, HandObservation, Intent
from manux.perception.pose_memory import PoseMemory, PoseRecognizer
from manux.perception.pose_registration import SLOTS

__all__ = ["ID", "GESTURES", "GESTURE_PHASES", "DEFAULT_BINDINGS", "SETTINGS", "CustomPoseFeature", "gesture_of"]

ID = "custom_pose"
GESTURES: Tuple[str, ...] = tuple(f"{ID}.{slot}" for slot in SLOTS)
GESTURE_PHASES = {g: frozenset({"tap"}) for g in GESTURES}
DEFAULT_BINDINGS = {g: None for g in GESTURES}
SETTINGS = {f"{ID}.enabled": True}
# tap actions a registered pose may run. `keys.press` takes any key combination (actions/keys.py refuses the dangerous
# ones); window.close (Alt+F4) is left out on purpose: a young recogniser must not close windows.
COMMANDS = ("keys.press", "mouse.left_click", "mouse.right_click", "window.task_switcher", "window.show_desktop",
            "nav.back", "nav.forward", "tab.prev", "tab.next")


def gesture_of(slot: str) -> str:
    return f"{ID}.{slot}"


class CustomPoseFeature:
    id = ID
    modes = frozenset({"pinch", "pointer", "virtual_hand"})
    gestures = GESTURES

    def __init__(self, memory: Optional[PoseMemory] = None) -> None:
        self.set_memory(memory)

    def set_memory(self, memory: Optional[PoseMemory]) -> None:
        self.memory = memory
        self.recognizer = PoseRecognizer(memory) if memory is not None and memory.registered() else None

    def reset(self, reason: str) -> None:
        if self.recognizer is not None:
            self.recognizer.reset()

    def activity(self) -> Activity:
        return Activity()

    def step(self, hand: Optional[HandObservation], ctx: FrameContext) -> Sequence[Intent]:
        if self.recognizer is None or not ctx.settings.get("enabled", True):
            return ()
        if hand is None:
            self.recognizer.reset()
            return ()
        label = self.recognizer.step(ctx.frame.t, hand.landmarks, hand.world, hand.frame.aspect)
        if label is None:
            return ()
        slot = self.memory.classes[label].extra.get("slot")
        if slot not in SLOTS:
            return ()
        return (Intent(ctx.frame.t, ID, gesture_of(slot), "tap", info={"name": label}),)
