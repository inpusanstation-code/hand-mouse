"""2026-11-11: palm_side -> Win+D was switched off, yet a composite bound to Win+D kept showing the desktop."""
from src.action_bindings import ActionBindingRegistry


def test_other_gestures_with_the_same_command_are_named(tmp_path):
    reg = ActionBindingRegistry(tmp_path / "b.json")
    reg.set_binding("palm_side", "mouse_action", "show_desktop", enabled=False)
    key = "comp_open_hand_hold"
    reg.composite_gestures[key] = {"key": key, "name": "손 펴기 유지", "base_posture": "open_hand",
                                   "trigger_type": "hold", "enabled": True}
    reg.set_binding(key, "mouse_action", "show_desktop", track="composite")
    assert reg.others_with_action("palm_side", "mouse_action", "show_desktop") == ["손 펴기 유지 (복합 동작)"]
    assert reg.others_with_action("palm_side", "mouse_action", "left_click") == ["엄지+중지 (좌클릭)"]   # the default binding
    reg.set_binding(key, "mouse_action", "show_desktop", enabled=False)      # switched off: no longer named, never fires
    assert reg.others_with_action("palm_side", "mouse_action", "show_desktop") == []
    assert reg.resolve_effective_action(key)["action_type"] == "none"
    assert reg.composite_gestures[key]["enabled"] is False