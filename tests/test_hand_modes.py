"""The two hand modes are separate worlds (2026-11-12, the person: "가상손 모드랑 손바닥 모드는 완전 별개의 세계관이라고
보면 되니까 특정 동작이 어디에 속하는지 명확하게 구분 … 커스텀 때도 해당 동작이 어떤 모드에서 돌아가는 건지 명확하게"),
and the hand on the screen reads the thumb + little-finger pinch from the hand shape ("저 동작도 동작 자체를 인식해서
작동하도록"). That morning a request made in the virtual hand was connected to palm mode's thumb + little-finger pinch,
which does nothing there, under a name that still carried the command it was recorded with ("창 선택")."""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

from src import llm_binding as lb
from src.action_bindings import MODE_NAMES_KO, gesture_mode, get_action_registry, works_in
from src.virtual_hand import TIPS, ShapePinky


def test_every_gesture_belongs_to_a_world():
    reg = SimpleNamespace(custom_motions={"motion_f5": {}}, composite_gestures={"comp_a": {"motion_only": True}, "comp_b": {}})
    assert [gesture_mode(k, reg) for k in ("vh_pinky", "vh_pinch", "vh_fist", "vh_drag")] == ["virtual"] * 4
    assert [gesture_mode(k, reg) for k in ("thumb_pinky", "thumb_middle", "thumb_index", "palm_side")] == ["palm"] * 4
    assert [gesture_mode(k, reg) for k in ("motion_f5", "comp_a", "swipe_left")] == ["motion"] * 3
    assert [gesture_mode(k, reg) for k in ("comp_b", "v_sign", "rock_sign", "seq_1", "path_1")] == ["all"] * 5
    assert works_in("virtual", "virtual") and not works_in("palm", "virtual") and not works_in("virtual", "palm")
    assert works_in("all", "virtual") and works_in("motion", "palm") and set(MODE_NAMES_KO) == {"virtual", "palm", "motion", "all"}


def test_the_ai_is_given_each_gestures_world_and_plain_names():
    gestures = {g["key"]: g for g in lb.gesture_list(get_action_registry())}
    assert gestures["thumb_pinky"]["name"] == "엄지+새끼" and gestures["thumb_pinky"]["mode_name"] == "손바닥 모드"
    assert gestures["vh_pinky"]["mode"] == "virtual" and gestures["vh_pinch"]["mode"] == "virtual"      # they were missing
    assert not any("(" in g["name"] and g["name"].endswith(("선택)", "클릭)")) for g in gestures.values())
    prompt = lb.system_prompt(list(gestures.values()))
    assert "- thumb_pinky | 엄지+새끼 | 손바닥 모드 |" in prompt and "- vh_pinky | " in prompt and "가상 손 모드" in prompt
    assert lb.plain_name("엄지+새끼 (창 선택)") == "엄지+새끼" and lb.plain_name("검지만 펴기 (가리키기) 유지") == "검지만 펴기 (가리키기) 유지"


def test_a_gesture_of_the_other_hand_mode_is_said_and_left_unticked():
    gestures = lb.gesture_list(get_action_registry())
    answer = {"summary": "", "questions": [], "proposals": [
        {"gesture_key": "thumb_pinky", "action_type": "hotkey", "action_value": "ctrl+w", "enabled": True},
        {"gesture_key": "vh_pinky", "action_type": "hotkey", "action_value": "ctrl+w", "enabled": True},
        {"gesture_key": "v_sign", "action_type": "hotkey", "action_value": "f5", "enabled": True}]}
    rows = lb.mark_modes(lb.check(answer, gestures)["proposals"], gestures, "virtual")
    palm, virtual, sign = rows
    assert palm["mode_name"] == "손바닥 모드" and palm["checked"] is False and palm["other_mode"] and "가상 손 모드에서는 동작하지 않아요" in palm["warning"]
    assert virtual["mode_name"] == "가상 손 모드" and virtual["checked"] and not virtual.get("other_mode")
    assert sign["mode"] == "all" and not sign.get("other_mode")
    again = lb.mark_modes(lb.check(answer, gestures)["proposals"], gestures, "palm")        # the same request in palm mode
    assert again[0]["checked"] and again[1]["checked"] is False and "손바닥 모드에서는 동작하지 않아요" in again[1]["warning"]


def test_the_list_of_connected_commands_says_the_world_of_each(tmp_path):
    path = tmp_path / "ai.json"
    path.write_text(json.dumps([{"gesture_key": "thumb_pinky", "gesture_name": "엄지+새끼 (창 선택)", "action_type": "hotkey",
                                 "action_value": "ctrl+w", "enabled": True},
                                {"gesture_key": "vh_pinky", "gesture_name": "엄지+새끼 집기 (0.3초 유지)", "action_type": "hotkey",
                                 "action_value": "ctrl+w", "enabled": True}]), encoding="utf-8")
    old = lb.still_in_force
    lb.still_in_force = lambda *a, **k: True
    try:
        rows = {r["gesture_key"]: r for r in lb.History(path).rows(get_action_registry())}
    finally:
        lb.still_in_force = old
    assert rows["thumb_pinky"]["gesture_name"] == "엄지+새끼" and rows["thumb_pinky"]["mode_name"] == "손바닥 모드"
    assert rows["vh_pinky"]["gesture_name"] == "엄지+새끼 집기 (0.3초 유지)" and rows["vh_pinky"]["mode"] == "virtual"


def _hand(pinch=None):
    """An open hand pointing up (x, y in 0..1, y down); `pinch`: the finger whose tip the thumb tip is put on."""
    pts = [[.5, .8]] + [[.44, .74], [.4, .68], [.37, .63], [.34, .58]]                      # wrist, thumb out to the side
    for x in (.45, .5, .55, .6):                                                              # index .. little finger, straight up
        pts += [[x, .6], [x, .52], [x, .46], [x, .4]]
    if pinch:
        tip = pts[TIPS[pinch]]
        if pinch == "pinky":
            tip[:] = [.56, .66]                                                               # folded towards the palm
        pts[4] = list(tip)
    return [SimpleNamespace(x=p[0], y=p[1], z=0.0) for p in pts]


def test_thumb_and_little_finger_held_together_is_read_from_the_hand_shape_once():
    sp = ShapePinky()
    fired = [sp.step(_hand("pinky"), 1280, 720, t / 30) for t in range(30)]
    assert fired.count(True) == 1 and fired.index(True) == round(ShapePinky.HOLD * 30) and sp.closed      # after the hold, once
    assert not any(sp.step(_hand(), 1280, 720, 1 + t / 30) for t in range(5)) and not sp.closed           # let go
    assert sum(sp.step(_hand("pinky"), 1280, 720, 2 + t / 30) for t in range(30)) == 1                    # ... and again
    for other in (None, "index", "middle", "ring"):                                                        # other hands: nothing
        sp = ShapePinky()
        assert not any(sp.step(_hand(other), 1280, 720, t / 30) for t in range(30)), other
    sp = ShapePinky()                                                                                      # a touch that does not last
    assert not any(sp.step(_hand("pinky" if t < 5 else None), 1280, 720, t / 30) for t in range(30))


def test_in_the_virtual_hand_the_pinch_runs_what_is_connected_to_it_and_palm_modes_connection_does_not(tmp_path):
    from tests.test_virtual_hand import box_runtime
    reg = get_action_registry()
    assert reg.get_binding("vh_pinky")["action_value"] == "none"                 # nothing connected until the person does
    reg.set_binding("thumb_pinky", "hotkey", "ctrl+shift+t")                     # palm mode's pinch: another world
    rt = box_runtime(tmp_path)
    for _ in range(4):
        rt._step()
    opened = list(rt.tracker.hand)
    hand = rt.tracker.hand
    tip = hand[TIPS["pinky"]]
    hand[4] = type(tip)(tip.x, tip.y, tip.z)

    def hold(seconds):
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            time.sleep(1 / 60)
            rt._step()

    hold(ShapePinky.HOLD + .25)
    assert not [e for e in rt.mouse.event_log if e.startswith("hotkey")]         # held, but nothing is connected
    rt.tracker.hand[:] = opened
    hold(.15)
    reg.set_binding("vh_pinky", "hotkey", "ctrl+w")
    rt._binding_cache = {}
    hand[4] = type(tip)(tip.x, tip.y, tip.z)
    hold(ShapePinky.HOLD + .4)
    assert [e for e in rt.mouse.event_log if e.startswith("hotkey")] == ["hotkey:ctrl+w"]      # once, and its own command
