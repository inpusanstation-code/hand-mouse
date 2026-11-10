"""Supported sensitivity controls from Dan's settings_panel.py at a60241d.

Presentation metadata and validation only; features and the Windows sink own behaviour.
Opening the editor never retunes existing values. Apply accepts only edited keys.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

from manux.settings.help import help_for
from manux.settings.schema import Setting
from manux.settings.store import Settings


@dataclass(frozen=True)
class Control:
    key: str
    label: str
    low: float
    high: float
    step: float
    group: str
    hint: str


CONTROLS = (
    Control("pinch.pinch_threshold", "엄지·검지 핀치 감도 · 스크롤", .02, .12, .001, "pinch", "높을수록 쉽게 잡힙니다. 놓는 기준은 +0.02로 함께 조절됩니다."),
    Control("pinch.click_threshold", "엄지·중지 클릭 감도 · 좌클릭", .02, .12, .001, "click", "높을수록 손가락을 덜 붙여도 클릭됩니다."),
    Control("pinch.ring_click_threshold", "엄지·약지 클릭 감도 · 우클릭", .02, .12, .001, "click", "높을수록 손가락을 덜 붙여도 클릭됩니다."),
    Control("pinch.pinky_click_threshold", "엄지·새끼 핀치 감도 · 창 전환", .02, .12, .001, "pinch", "높을수록 창 전환 핀치가 쉽게 잡힙니다."),
    Control("pinch.pinch_release_grace", "핀치 유지 보정 (초)", 0, .5, .01, "pinch", "짧게 손가락이 벌어져도 핀치를 유지하는 시간입니다."),
    Control("pinch.pinch_fistlike_confirm", "주먹 모양 핀치 확인 (초)", 0, .4, .01, "pinch", "주먹과 핀치를 구분하기 위해 기다리는 시간입니다."),
    Control("pinch.click_release_margin", "클릭 핀치 유지 여유", 0, .06, .002, "click", "높을수록 클릭 중 손가락이 조금 벌어져도 유지됩니다."),
    Control("pinch.click_release_grace", "클릭 핀치 끊김 보정 (초)", 0, .2, .01, "click", "짧은 추적 흔들림으로 클릭이 끊기는 것을 줄입니다."),
    Control("pinch.click_confirm_time", "클릭 확인 시간 (초)", 0, .3, .01, "click", "짧을수록 빠르게 반응하고 길수록 우발적인 클릭을 줄입니다."),
    Control("cursor.relative_gain_min", "이동 감도 (천천히)", .05, 3, .05, "cursor", "손을 천천히 움직일 때의 커서 이동 배율입니다."),
    Control("cursor.relative_gain_max", "이동 감도 (빠르게)", .5, 6, .1, "cursor", "손을 빠르게 움직일 때의 커서 이동 배율입니다."),
    Control("cursor.smoothing", "이동 부드러움", .05, 1, .01, "cursor", "낮을수록 부드럽고, 높을수록 손의 움직임에 빠르게 반응합니다."),
    Control("pinch.fist_curl_enter", "주먹 판정 기준", .5, 1.3, .05, "cursor", "주먹 이동으로 인식하는 손가락 굽힘 기준입니다."),
    Control("pinch.fist_confirm_time", "주먹 확인 시간 (초)", 0, .5, .01, "cursor", "주먹 이동으로 전환하기 전에 확인하는 시간입니다."),
    Control("pinch.fist_dpi_multiplier", "주먹 이동 배율", .05, 35, .05, "cursor", "1보다 작으면 주먹으로 세밀하게, 크면 주먹으로 빠르게 움직입니다(예전 hand-mouse는 35)."),
    Control("pinch.long_press_drag_multiplier", "길게 누르기 드래그 배율", 1, 30, .5, "click", "좌클릭 핀치를 길게 유지해 드래그할 때의 이동 배율입니다."),
    Control("pinch.long_press_time", "길게 눌러 드래그 시작 (초)", .3, 1.5, .05, "click",
            "엄지·중지를 이만큼 붙이고 있으면 드래그가 시작됩니다. 짧을수록 빨리 잡히지만 클릭이 드래그로 바뀌기 쉽습니다."),
    Control("cursor.drag_after_click_guard", "클릭 직후 드래그 보호 (초)", 0, 1, .02, "click",
            "클릭하자마자 같은 자리에서 드래그하면 Windows가 더블클릭으로 읽습니다. 이 시간 동안은 손이 움직일 때 누릅니다. 0은 끔, 0.52 권장."),
)
# Choices shown as plain words. The value stays the setting's own type (here a bool).
CHOICES = {
    "pinch.drag_on_move": dict(
        label="드래그 시작 방식", group="click", choices=(False, True),
        labels=("길게 눌러서 시작 (기본)", "누른 채 움직이면 바로 시작"),
        hint="‘바로 시작’은 엄지·중지를 붙인 채 손을 움직이는 순간 드래그가 되고, 드래그 중에는 검지가 스쳐도 스크롤로 바뀌지 않습니다."),
}
# Choices that set several settings at once. Not stored themselves: the shown value is read back from the settings.
PRESETS = {
    "preset.fist_style": dict(
        label="주먹 이동 방식", group="cursor", choices=("precise", "fast"),
        labels=("주먹 = 정밀하게 (느리게) · 편 손 = 빠르게 (기본)", "주먹 = 빠르게 · 편 손 = 정밀하게 (예전 hand-mouse)"),
        hint="손을 쥐고 펴는 것으로 커서 속도를 바꿉니다. ‘빠르게’는 예전 hand-mouse처럼 주먹으로 멀리 빨리 가고 편 손으로 세밀하게 맞춥니다. 아래 ‘주먹 이동 배율’(0.05~35)로 더 세밀하게 조절할 수 있습니다.",
        values={"precise": {"pinch.fist_dpi_multiplier": .35, "pinch.shape_dpi_min": 2.0},
                "fast": {"pinch.fist_dpi_multiplier": 35.0, "pinch.shape_dpi_min": 1.0}},
        current=lambda settings: "fast" if float(settings.get("pinch.fist_dpi_multiplier")) > 1 else "precise"),
}
BY_KEY = {c.key: c for c in CONTROLS}
VERTICAL_INPUT = Setting(
    "cursor.vertical_input", "wrist_pitch", kind="choice", choices=("hand_position", "wrist_pitch"),
    doc="손 전체 이동은 손의 상하 위치를, 손목 기울기는 손목 각도를 사용합니다. 좌우는 모두 손 위치를 사용합니다. 손목 자동 보정은 손목 방식에만 적용됩니다.")
VERTICAL_LABELS = ("손 전체 이동 (기존 방식)", "손목 기울기")
CURSOR_SETTINGS = (
    VERTICAL_INPUT,
    Setting("cursor.relative_gain_min", .35, minimum=.05, maximum=3),
    Setting("cursor.relative_gain_max", 1.2, minimum=.5, maximum=6),
    Setting("cursor.smoothing", .35, minimum=.05, maximum=1),
)


def rows(settings: Settings):
    choice = dict(key=VERTICAL_INPUT.key, label="상하 이동 방식", kind="choice", group="cursor",
                  choices=list(VERTICAL_INPUT.choices), choiceLabels=list(VERTICAL_LABELS),
                  minimum=0, maximum=1, step=1, hint=VERTICAL_INPUT.doc,
                  value=settings.get(VERTICAL_INPUT.key), defaultValue=VERTICAL_INPUT.default,
                  editable=not settings.is_overridden(VERTICAL_INPUT.key))
    presets = [dict(key=key, label=p["label"], kind="choice", group=p["group"], choices=list(p["choices"]),
                    choiceLabels=list(p["labels"]), minimum=0, maximum=1, step=1, hint=p["hint"],
                    value=p["current"](settings), defaultValue=p["choices"][0],
                    editable=not any(settings.is_overridden(k) for k in p["values"][p["choices"][0]]))
               for key, p in PRESETS.items()]
    return [choice] + presets + [dict(key=c.key, label=c.label, kind="float", choices=[], choiceLabels=[],
                 minimum=c.low, maximum=c.high, step=c.step,
                 group=c.group, hint=help_for(c.key) or c.hint, value=settings.get(c.key),
                 defaultValue=settings.schema.get(c.key).default,
                 editable=not settings.is_overridden(c.key)) for c in CONTROLS] + [
        dict(key=key, label=c["label"], kind="choice", group=c["group"], choices=list(c["choices"]),
             choiceLabels=list(c["labels"]), minimum=0, maximum=1, step=1, hint=c["hint"],
             value=settings.get(key), defaultValue=settings.schema.get(key).default,
             editable=not settings.is_overridden(key)) for key, c in CHOICES.items()]


def prepare(settings: Settings, edits: Mapping[str, object]) -> dict[str, object]:
    """Validate a whole edit before any save; enforce Dan's coupled release/gain limits."""
    result = {}
    chosen = {}
    for key, value in edits.items():
        if key in PRESETS:
            if value not in PRESETS[key]["choices"]:
                raise ValueError(f"{PRESETS[key]['label']}: 목록에서 고르세요.")
            if any(settings.is_overridden(k) for k in PRESETS[key]["values"][value]):
                raise ValueError("프로필이 지정한 값입니다. 기본 프로필에서 변경하세요.")
            chosen.update(PRESETS[key]["values"][value])
            continue
        if key == VERTICAL_INPUT.key:
            checked, warning = VERTICAL_INPUT.coerce(value)
            if warning:
                raise ValueError("상하 이동 방식을 선택하세요.")
            if settings.is_overridden(key):
                raise ValueError("프로필이 지정한 이동 방식입니다. 기본 프로필에서 변경하세요.")
            result[key] = checked
            continue
        if key in CHOICES:
            if value not in CHOICES[key]["choices"] or type(value) is not type(CHOICES[key]["choices"][0]):
                raise ValueError(f"{CHOICES[key]['label']}: 목록에서 고르세요.")
            if settings.is_overridden(key):
                raise ValueError("프로필이 지정한 값입니다. 기본 프로필에서 변경하세요.")
            result[key] = value
            continue
        control = BY_KEY.get(key)
        if control is None or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("올바른 민감도 숫자를 입력하세요.")
        if not control.low <= value <= control.high:
            raise ValueError(f"{control.label}: {control.low}~{control.high} 범위로 입력하세요.")
        if settings.is_overridden(key):
            raise ValueError("프로필이 지정한 감도입니다. 기본 프로필에서 변경하세요.")
        result[key] = round(control.low + round((value - control.low) / control.step) * control.step, 6)
    for key, value in chosen.items():
        result.setdefault(key, value)          # a value moved by hand in the same edit wins over the preset
    if "pinch.pinch_threshold" in result:
        result["pinch.release_threshold"] = round(result["pinch.pinch_threshold"] + .02, 6)
    low, high = "cursor.relative_gain_min", "cursor.relative_gain_max"
    if result.get(low, settings.get(low)) > result.get(high, settings.get(high)):
        if low in result and high not in result:
            result[high] = result[low]
        elif high in result and low not in result:
            result[low] = result[high]
        else:
            raise ValueError("빠른 이동 감도는 느린 이동 감도 이상으로 설정하세요.")
    if any(settings.is_overridden(key) for key in result):
        raise ValueError("함께 조절할 값이 프로필에 지정되어 있습니다. 기본 프로필에서 변경하세요.")
    return result
