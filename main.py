"""
Hand-Mouse: MediaPipe Hand Tracking Mouse Controller

The camera looks down (from above or obliquely) at your hand over the desk.
A virtual paper lies flat on the desk and stands for the monitor:
  - Thumb + Index pinch  = pen down. Left/right: move the hand sideways.
                           Up/down: curl middle+ring+pinky into the palm (down) or open them (up).
                           Release = pen up (cursor stays; re-pinch elsewhere to continue).
  - Calibration runs once at first start, and again whenever you click the "영점 재설정"
    button in the window (or press Z; H = step 1 only, V = step 2 only):
      1. left/right: sweep left/right several times; the densest bundle becomes horizontal.
      2. corners: make the hand pose for each monitor corner (left/right end, fingers open =
         top / curled = bottom) and hold the pinch briefly. Your hand range then covers the
         whole monitor (range mode). Left/right follows whatever you did - turning the wrist
         or moving the hand - and falls back to the step-1 sweep if the corners are too close.
  - Thumb + Middle pinch = Left Click (once per pinch)
  - Thumb + Ring pinch   = Right Click (once per pinch)
  - Thumb + Index + Middle = Drag Hold, Thumb + Pinky = Drag Toggle (both off by default)
- Supports:
  1. USB Webcams (`--source 0`)
  2. App-less Smartphone Browser Camera (`--phone-web` or `--source phone`)
  3. Smartphone IP Camera Stream (`--source http://<IP>:8080/video`)
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Union

import cv2
import numpy as np

from src.camera import CameraConfig, CameraStream
from src.gesture_engine import GestureEngine, GestureResult
from src.hand_tracker import HandTracker
from src.mouse_controller import MouseController

GESTURE_LABELS = {
    "thumb_index_pinch": "Thumb+Index",
    "thumb_middle_pinch": "Thumb+Middle",
    "thumb_ring_pinch": "Thumb+Ring",
    "thumb_pinky_pinch": "Thumb+Pinky",
    "thumb_index_middle_pinch": "Thumb+Index+Middle",
    "index_extend": "Index out",
    "index_middle_extend": "Index+Middle out",
}


_KR_FONTS: dict = {}


def put_text_kr(frame: np.ndarray, text: str, org: tuple[int, int], size: int, color_bgr: tuple) -> None:
    """Draw Korean text (OpenCV fonts have no Hangul). Falls back to OpenCV if Pillow/font is missing."""
    try:
        from PIL import Image, ImageDraw, ImageFont

        font = _KR_FONTS.get(size)
        if font is None:
            font = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", size)
            _KR_FONTS[size] = font
        x, y = org
        left, top, right, bottom = font.getbbox(text)
        x2, y2 = min(frame.shape[1], x + right + 4), min(frame.shape[0], y + bottom + 4)
        if x2 <= x or y2 <= y:
            return
        roi = frame[y:y2, x:x2]
        img = Image.fromarray(roi[:, :, ::-1])
        draw = ImageDraw.Draw(img)
        b, g, r = color_bgr
        draw.text((1, 1), text, font=font, fill=(0, 0, 0))
        draw.text((0, 0), text, font=font, fill=(r, g, b))
        frame[y:y2, x:x2] = np.asarray(img)[:, :, ::-1]
    except Exception:
        cv2.putText(frame, text.encode("ascii", "ignore").decode(), (org[0], org[1] + size),
                    cv2.FONT_HERSHEY_SIMPLEX, size / 32.0, color_bgr, 2, cv2.LINE_AA)


CORNER_TEXT = {
    "tl": ("왼쪽 위", "손을 1단계처럼 편하게 왼쪽 끝으로 보내고, 중지·약지·새끼는 활짝 편 채"),
    "tr": ("오른쪽 위", "손을 편하게 오른쪽 끝으로 보내고, 중지·약지·새끼는 활짝 편 채"),
    "br": ("오른쪽 아래", "손을 오른쪽 끝으로 보내고, 중지·약지·새끼는 손바닥 쪽으로 끝까지 만 채"),
    "bl": ("왼쪽 아래", "손을 왼쪽 끝으로 보내고, 중지·약지·새끼는 손바닥 쪽으로 끝까지 만 채"),
}
THUMB_CORNER_NAMES = {"tl": "왼쪽 위", "tr": "오른쪽 위", "br": "오른쪽 아래", "bl": "왼쪽 아래"}
THUMB_STATE_TEXT = {
    "wait": "그 자리에서 엄지를 잠깐 멈추세요",
    "holding": "그대로 멈추세요...",
    "move_on": "좋아요! 이제 엄지를 다음 자리로 옮기세요",
    "narrow_thumb": "네 자리가 너무 가깝거나 순서가 꼬였어요. 엄지를 더 넓게 움직여 처음부터 다시 해요",
}

CORNER_STATE_TEXT = {
    "wait": "엄지+검지를 붙이고 잠깐 그대로 멈추세요",
    "holding": "그대로 멈추세요...",
    "ok": "좋아요! 엄지+검지를 떼세요",
    "short": "조금 더 오래 붙이고 멈춰 주세요",
    "narrow_x": "왼쪽과 오른쪽 차이가 너무 작아요. 왼쪽·오른쪽 끝까지 더 보내서 처음부터 다시 해요",
    "narrow_y": "위아래 차이가 작아요. 더 활짝 펴고 더 깊이 말아서 처음부터 다시 해요",
}

CALIB_TEXT = {
    "wait": "엄지+검지를 붙이고 오른쪽으로 먼저 움직인 뒤, 좌우로 여러 번 왔다 갔다 하세요",
    "drawing": "좋아요, 계속 좌우로 왔다 갔다 하세요 (선이 겹칠수록 진해져요)",
    "more": "조금 더 해주세요. 엄지+검지를 붙이고 좌우로 왔다 갔다 하세요",
}

# Accumulated calibration strokes: repeated sweeps over the same path get brighter and thicker.
_CALIB_CANVAS: dict = {"session": -1, "drawn": 0, "img": None}


def draw_curl_meter(frame: np.ndarray, engine: GestureEngine) -> None:
    """A vertical gauge of the three fingers' openness (top = open, bottom = curled)."""
    h, w = frame.shape[:2]
    x, top, bottom = w - 90, 160, h - 160
    lo_v, hi_v = 0.6, 2.2  # openness shown on the gauge (fist .. fully open)

    def ypos(v: float) -> int:
        f = (min(hi_v, max(lo_v, v)) - lo_v) / (hi_v - lo_v)
        return int(bottom - f * (bottom - top))

    cv2.rectangle(frame, (x, top), (x + 26, bottom), (70, 70, 70), -1)
    cv2.rectangle(frame, (x, top), (x + 26, bottom), (150, 150, 150), 1)
    for values in engine.corner_values.values():
        cy = ypos(values[-1])  # (turn, move, openness): openness is last
        cv2.line(frame, (x, cy), (x + 26, cy), (0, 220, 120), 2)
    if engine._curl is not None:
        cy = ypos(engine._curl)
        cv2.rectangle(frame, (x - 8, cy - 3), (x + 34, cy + 3), (255, 255, 255), -1)
    put_text_kr(frame, "펴기", (x - 4, top - 30), 18, (230, 230, 230))
    put_text_kr(frame, "말기", (x - 4, bottom + 6), 18, (230, 230, 230))


def draw_monitor_map(frame: np.ndarray, engine: GestureEngine, origin: tuple[int, int], size: tuple[int, int],
                     point: tuple | None = None, cursor: tuple | None = None) -> None:
    """A small monitor picture: corners being set (calibration) or where the hand points (range mode)."""
    from src.gesture_engine import CORNERS

    x0, y0 = origin
    mw, mh = size
    shade = frame.copy()
    cv2.rectangle(shade, (x0 - 8, y0 - 8), (x0 + mw + 8, y0 + mh + 8), (18, 18, 24), -1)
    cv2.addWeighted(shade, 0.7, frame, 0.3, 0, frame)
    cv2.rectangle(frame, (x0, y0), (x0 + mw, y0 + mh), (200, 200, 200), 2)
    target = engine.corner_target
    if engine.calibrating and engine.calib_phase in ("corners", "thumb"):
        for k, (name, cx, cy) in enumerate(CORNERS):
            px, py = int(x0 + cx * mw), int(y0 + cy * mh)
            if name in engine.corner_values:
                cv2.circle(frame, (px, py), 10, (0, 220, 120), -1, cv2.LINE_AA)
            elif target is not None and name == target[0]:
                cv2.circle(frame, (px, py), 13, (0, 230, 255), 2, cv2.LINE_AA)
                if engine.corner_hold > 0:
                    cv2.ellipse(frame, (px, py), (13, 13), -90, 0, int(360 * engine.corner_hold),
                                (0, 230, 255), 4, cv2.LINE_AA)
            else:
                cv2.circle(frame, (px, py), 7, (120, 120, 120), -1, cv2.LINE_AA)
    if cursor is not None:
        cv2.circle(frame, (int(x0 + cursor[0] * mw), int(y0 + cursor[1] * mh)), 5, (255, 255, 255), -1, cv2.LINE_AA)
    if point is not None:
        cv2.circle(frame, (int(x0 + point[0] * mw), int(y0 + point[1] * mh)), 7, (0, 255, 140), 2, cv2.LINE_AA)


def draw_thumb_pad(frame: np.ndarray, engine: GestureEngine, calibrating: bool = False) -> None:
    """Thumb mode: the thumb's "trackpad" drawn on the hand (calibrated corners), and the thumb."""
    from src.gesture_engine import CORNERS

    h, w = frame.shape[:2]

    def img(tp) -> tuple[int, int] | None:
        q = engine.hand_to_image(tp)
        return None if q is None else (int(q[0] * w), int(q[1] * h))

    if calibrating:
        quad = [engine.corner_values.get(name) for name, _, _ in CORNERS]
    else:
        quad = engine.config.get("thumb_corners") or []
    pts = [img(c) for c in quad if c is not None]
    pts = [p for p in pts if p is not None]
    if len(pts) == 4:
        poly = np.array(pts, np.int32)
        tint = frame.copy()
        cv2.fillPoly(tint, [poly], (40, 80, 40))
        cv2.addWeighted(tint, 0.35, frame, 0.65, 0, frame)
        cv2.polylines(frame, [poly], True, (0, 255, 140), 2, cv2.LINE_AA)
    for k, p in enumerate(pts):
        cv2.circle(frame, p, 6, (0, 220, 120), -1, cv2.LINE_AA)
    if engine._thumb is not None:
        tp = img(engine._thumb)
        if tp is not None:
            cv2.circle(frame, tp, 9, (0, 255, 255), 2, cv2.LINE_AA)
            if calibrating and engine.corner_hold > 0:
                cv2.ellipse(frame, tp, (16, 16), -90, 0, int(360 * engine.corner_hold), (0, 230, 255), 4,
                            cv2.LINE_AA)


def draw_calibration(frame: np.ndarray, engine: GestureEngine) -> None:
    """Instructions, the accumulated sweeps / curl gauge, the current estimate and progress."""
    h, w = frame.shape[:2]
    if engine.calib_phase == "thumb":
        draw_thumb_pad(frame, engine, calibrating=True)
        draw_monitor_map(frame, engine, (40, 150), (240, 135))
        _draw_calib_footer(frame, engine)
        return
    if engine.calib_phase == "corners":
        draw_curl_meter(frame, engine)
        draw_monitor_map(frame, engine, (40, 150), (240, 135))
        _draw_calib_footer(frame, engine)
        return
    canvas = _CALIB_CANVAS
    if canvas["session"] != engine.calib_session or canvas["img"] is None or canvas["img"].shape != (h, w):
        canvas.update(session=engine.calib_session, drawn=0, img=np.zeros((h, w), np.float32))
    img = canvas["img"]
    segments = engine.calib_segments
    if len(segments) < canvas["drawn"]:
        canvas["drawn"] = 0
        img[:] = 0
    for (x0, y0), (x1, y1) in segments[canvas["drawn"]:]:
        stroke = np.zeros((h, w), np.float32)
        cv2.line(stroke, (int(x0 * w), int(y0 * h)), (int(x1 * w), int(y1 * h)), 1.0, 4, cv2.LINE_AA)
        img += 0.22 * stroke
    canvas["drawn"] = len(segments)

    if segments:
        glow = cv2.GaussianBlur(img, (0, 0), 4.0) * 2.0 + img  # overlaps spread out = thicker
        level = np.clip(glow, 0.0, 1.0)
        color = np.zeros_like(frame, np.float32)
        color[:] = (0, 200, 255)  # warm yellow
        alpha = level[:, :, None]
        frame[:] = (frame.astype(np.float32) * (1.0 - alpha) + color * alpha).astype(np.uint8)

    # Current estimate: a long line through the bundle centre along the averaged direction.
    if engine.calib_estimate is not None and engine.calib_center is not None:
        import math

        a = engine.aspect or 1.0
        ux, uy = math.cos(engine.calib_estimate) / a, math.sin(engine.calib_estimate)
        n = max(1e-6, ((ux * w) ** 2 + (uy * h) ** 2) ** 0.5)
        ux, uy = ux * w / n, uy * h / n
        cx, cy = int(engine.calib_center[0] * w), int(engine.calib_center[1] * h)
        half = 260
        cv2.line(frame, (int(cx - ux * half), int(cy - uy * half)), (int(cx + ux * half), int(cy + uy * half)),
                 (255, 80, 255), 2, cv2.LINE_AA)
        cv2.arrowedLine(frame, (cx, cy), (int(cx + ux * 90), int(cy + uy * 90)), (255, 80, 255), 3,
                        cv2.LINE_AA, tipLength=0.25)
        put_text_kr(frame, "기준선 (오른쪽)", (int(cx + ux * 96), int(cy + uy * 96) - 12), 16, (255, 120, 255))

    _draw_calib_footer(frame, engine)


def _draw_calib_footer(frame: np.ndarray, engine: GestureEngine) -> None:
    h, w = frame.shape[:2]
    shade = frame.copy()
    cv2.rectangle(shade, (0, h - 116), (w, h), (18, 18, 24), -1)
    cv2.addWeighted(shade, 0.78, frame, 0.22, 0, frame)
    step = f" ({engine.calib_step_no}/{engine.calib_step_count})" if engine.calib_step_count > 1 else ""
    progress = engine.calib_progress
    target = engine.corner_target
    if engine.calib_phase == "thumb" and target is not None:
        corner_name = THUMB_CORNER_NAMES[target[0]]
        title = f"엄지 영점 맞추기  ·  {corner_name} 모서리 ({engine.corner_index + 1}/4) - 커서가 그 모서리에 가 있어요"
        msg = f"손은 편하게 둔 채, 엄지 끝을 '{corner_name}'으로 쓸 자리에 두세요"
        msg2 = THUMB_STATE_TEXT.get(engine.calib_state, THUMB_STATE_TEXT["wait"])
    elif engine.calib_phase == "corners" and target is not None:
        corner_name, how = CORNER_TEXT[target[0]]
        title = f"모서리 맞추기{step}  ·  {corner_name} 모서리 ({engine.corner_index + 1}/4) - 커서가 그 모서리에 가 있어요"
        msg = f"{how} 엄지+검지를 붙이세요"
        msg2 = CORNER_STATE_TEXT.get(engine.calib_state, CORNER_STATE_TEXT["wait"])
    else:
        title = f"방향 맞추기{step}  ·  커서는 화면 정가운데에 있어요"
        if progress >= 1.0:
            msg = "충분해요! 엄지+검지를 떼면 " + ("다음 단계로 넘어가요" if engine._calib_queue else "완료돼요")
        else:
            msg = CALIB_TEXT.get(engine.calib_state, CALIB_TEXT["wait"])
        msg2 = ""
    put_text_kr(frame, title, (16, h - 108), 20, (255, 220, 120))
    put_text_kr(frame, "Esc: 건너뛰기", (w - 130, h - 108), 16, (180, 180, 180))
    put_text_kr(frame, msg, (16, h - 80), 20, (0, 255, 255))
    if msg2:
        put_text_kr(frame, msg2, (16, h - 54), 20, (120, 255, 160))
    bar_x, bar_y, bar_w = 16, h - 18, w - 140
    cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + 12), (90, 90, 90), 1, cv2.LINE_AA)
    cv2.rectangle(frame, (bar_x, bar_y), (bar_x + int(bar_w * progress), bar_y + 12),
                  (0, 220, 120) if progress >= 1.0 else (0, 200, 255), -1)
    cv2.putText(frame, f"{int(progress * 100):3d}%", (bar_x + bar_w + 12, bar_y + 11),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230, 230, 230), 1, cv2.LINE_AA)


def draw_turn_gauge(frame: np.ndarray, engine: GestureEngine, landmarks) -> None:
    """Range mode: from the wrist, the calibrated left/right turn limits and the current turn."""
    import math

    if not landmarks or engine._yaw is None or not engine.range_ready:
        return
    h, w = frame.shape[:2]
    a = engine.aspect or 1.0
    wx, wy = landmarks[0].x * w, landmarks[0].y * h
    length = max(60.0, engine.palm_size * h * 1.6)

    def ray(angle: float) -> tuple[int, int]:
        # angle is measured in aspect-corrected units (x * aspect, y); undo for drawing
        dx, dy = math.sin(angle) / a, -math.cos(angle)
        n = max(1e-6, math.hypot(dx * w, dy * h))
        return int(wx + dx * w / n * length), int(wy + dy * h / n * length)

    left = math.radians(float(engine.config["range_left_deg"]))
    right = math.radians(float(engine.config["range_right_deg"]))
    for ang in (left, right):
        cv2.line(frame, (int(wx), int(wy)), ray(ang), (140, 140, 140), 2, cv2.LINE_AA)
    cv2.line(frame, (int(wx), int(wy)), ray(engine._yaw), (0, 255, 140), 3, cv2.LINE_AA)
    put_text_kr(frame, "왼쪽 끝", ray(left), 16, (200, 200, 200))
    put_text_kr(frame, "오른쪽 끝", ray(right), 16, (200, 200, 200))


def draw_axis(frame: np.ndarray, engine: GestureEngine) -> None:
    """Fingers mode: show the horizontal axis through the pen and how up/down works."""
    pen = engine.last_pen_image
    if pen is None:
        return
    h, w = frame.shape[:2]
    down = engine.is_pinched
    color = (0, 255, 140) if down else (150, 150, 150)
    ex, ey = engine.paper_to_image(1.0, 0.0)  # one palm width toward screen right
    norm = max(1e-6, (ex * ex * w * w + ey * ey * h * h) ** 0.5)
    ux, uy = ex * w / norm, ey * h / norm
    cx, cy = int(pen[0] * w), int(pen[1] * h)
    half = 110
    cv2.line(frame, (int(cx - ux * half), int(cy - uy * half)), (cx, cy), color, 2, cv2.LINE_AA)
    cv2.arrowedLine(frame, (cx, cy), (int(cx + ux * half), int(cy + uy * half)), color, 2, cv2.LINE_AA,
                    tipLength=0.15)
    cv2.circle(frame, (cx, cy), 7 if down else 5, color, -1 if down else 2, cv2.LINE_AA)
    cv2.putText(frame, "Right", (int(cx + ux * (half + 8)), int(cy + uy * (half + 8))),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)


def draw_paper(
    frame: np.ndarray,
    engine: GestureEngine,
    screen_pos: tuple[int, int],
    screen_size: tuple[int, int],
) -> None:
    """Draw the virtual desk paper (= monitor) placed under the pen so that the pen sits
    where the cursor currently is on screen."""
    pen = engine.last_pen_image
    if pen is None:
        return
    h, w = frame.shape[:2]
    sw, sh = max(1, screen_size[0]), max(1, screen_size[1])
    speed = float(engine.config.get("pen_speed", 1.2)) * float(engine.config.get("dpi_scale", 1.0))
    paper_w = 1.0 / max(0.05, speed)
    paper_h = paper_w * sh / sw
    fx = screen_pos[0] / sw
    fy = screen_pos[1] / sh

    def corner(u: float, v: float) -> tuple[int, int]:
        ix, iy = engine.paper_to_image((u - fx) * paper_w, (v - fy) * paper_h)
        return int((pen[0] + ix) * w), int((pen[1] + iy) * h)

    poly = np.array([corner(0, 0), corner(1, 0), corner(1, 1), corner(0, 1)], dtype=np.int32)
    down = engine.is_pinched
    color = (0, 255, 140) if down else (150, 150, 150)
    if down:
        tint = frame.copy()
        cv2.fillPoly(tint, [poly], (30, 70, 40))
        cv2.addWeighted(tint, 0.30, frame, 0.70, 0, frame)
    cv2.polylines(frame, [poly], True, color, 2 if down else 1, cv2.LINE_AA)

    # Arrow on the top edge shows which way is "up" on the screen.
    cv2.arrowedLine(frame, corner(0.5, 0.12), corner(0.5, 0.0), color, 2, cv2.LINE_AA, tipLength=0.4)

    pen_px = (int(pen[0] * w), int(pen[1] * h))
    cv2.circle(frame, pen_px, 7 if down else 5, color, -1 if down else 2, cv2.LINE_AA)
    cv2.putText(
        frame,
        "Paper (pen down)" if down else "Paper (pen up)",
        (int(poly[0][0]) + 6, int(poly[0][1]) + 18),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        color,
        1,
        cv2.LINE_AA,
    )


def draw_hud(
    frame: np.ndarray,
    fps: float,
    source: Union[int, str],
    result: GestureResult,
    screen_pos: tuple[int, int],
    engine: GestureEngine,
    paused: bool,
    status_msg: str = "",
    screen_size: tuple[int, int] = (1920, 1080),
    landmarks=None,
) -> None:
    """Draw the paper (or absolute area), status bar, and keyboard shortcuts."""
    h, w = frame.shape[:2]
    margin = float(engine.config.get("active_margin", 0.15))
    dpi_scale = max(0.2, min(10.0, float(engine.config.get("dpi_scale", 1.0))))
    mode = str(engine.config.get("movement_mode", "relative")).lower()

    fingers = str(engine.config.get("vertical_source", "fingers")).lower() == "fingers"
    if engine.calibrating:
        draw_calibration(frame, engine)
    elif mode == "thumb" and engine.thumb_ready:
        draw_thumb_pad(frame, engine)
        sw, sh = max(1, screen_size[0]), max(1, screen_size[1])
        draw_monitor_map(frame, engine, (w - 210, 130), (180, 101), point=result.screen_point,
                         cursor=(screen_pos[0] / sw, screen_pos[1] / sh))
    elif mode == "range" and engine.range_ready:
        if engine.range_x_source == "turn":
            draw_turn_gauge(frame, engine, landmarks)
        else:
            draw_axis(frame, engine)
        sw, sh = max(1, screen_size[0]), max(1, screen_size[1])
        draw_monitor_map(frame, engine, (w - 210, 130), (180, 101), point=result.screen_point,
                         cursor=(screen_pos[0] / sw, screen_pos[1] / sh))
    elif mode in ("relative", "range") and fingers:
        draw_axis(frame, engine)
    elif mode == "relative":
        draw_paper(frame, engine, screen_pos, screen_size)
    else:
        base_span = max(1e-6, 1.0 - 2.0 * margin)
        half_span = min(1.0, max(0.04, base_span / dpi_scale)) * 0.5
        x1, y1 = int((0.5 - half_span) * w), int((0.5 - half_span) * h)
        x2, y2 = int((0.5 + half_span) * w), int((0.5 + half_span) * h)
        box_color = (0, 230, 118) if result.is_moving else (120, 120, 120)
        cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 1, cv2.LINE_AA)
        cv2.putText(
            frame,
            f"Active Screen Area (x{dpi_scale:.1f})",
            (x1 + 6, max(18, y1 + 18)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            box_color,
            1,
            cv2.LINE_AA,
        )

    # Top semi-transparent status bar
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, 112), (18, 18, 24), -1)
    cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)

    label = GESTURE_LABELS.get(result.active_gesture, "")
    state_color = (200, 200, 200)
    if paused:
        state_text = "PAUSED (Press SPACE to resume)"
        state_color = (0, 180, 255)
    elif engine.calibrating:
        state_text = {
            "x": "CALIBRATING - sweep left/right several times",
            "thumb": "CALIBRATING - thumb tip at each corner",
        }.get(engine.calib_phase, "CALIBRATING - monitor corners")
        state_color = (0, 220, 255)
    elif result.hold_point is not None:
        state_text = f"CLICK - cursor held ({label})" if label else "CLICK - cursor held"
        state_color = (0, 200, 255)
    elif result.action == "move_cursor":
        state_text = {"thumb": "THUMB CURSOR", "range": "MOVING CURSOR (Thumb+Index)"}.get(
            mode, "PEN DOWN - drawing (Thumb+Index)")
        state_color = (0, 255, 128)
    elif result.action == "drag_hold":
        state_text = "DRAGGING (Thumb+Index+Middle)"
        state_color = (80, 160, 255)
    elif result.action in ("left_click", "right_click", "drag_toggle"):
        state_text = f"{result.action.upper()} ({label})"
        state_color = (0, 120, 255)
    elif label:
        state_text = f"HOLDING {label} (release to click again)"
        state_color = (0, 200, 255)
    elif result.pending_gesture:
        state_text = f"... {GESTURE_LABELS.get(result.pending_gesture, '')}"
    else:
        state_text = "PEN UP (Pinch Thumb+Index to draw)"

    cv2.putText(frame, f"State: {state_text}", (16, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, state_color, 2, cv2.LINE_AA)

    # Clickable "reset calibration" button (handled by on_mouse)
    bx1, by1, bx2, by2 = w - 176, 8, w - 12, 42
    UI["reset_button"] = (bx1, by1, bx2, by2)
    hover = UI.get("hover", False)
    cv2.rectangle(frame, (bx1, by1), (bx2, by2), (90, 70, 40) if hover else (60, 50, 35), -1)
    cv2.rectangle(frame, (bx1, by1), (bx2, by2), (0, 200, 255), 1, cv2.LINE_AA)
    put_text_kr(frame, "영점 재설정", (bx1 + 30, by1 + 4), 20, (255, 255, 255))

    def fmt(key: str) -> str:
        d = result.distances.get(key, 1.0)
        return f"{d:.3f}" if d < 1.0 else "---"

    axis_txt = "set" if engine.config.get("paper_x_angle_deg") is not None else "auto"
    curl_txt = f"{result.curl:.2f}" if result.curl is not None else "---"
    vert_txt = (
        f"Curl:{curl_txt} x{float(engine.config.get('curl_gain', 0.5)):.2f}"
        if fingers
        else f"Tilt:{float(engine.config.get('paper_tilt_deg', 45.0)):.0f}"
    )
    jit = UI.get("jitter")
    jit_txt = f" | Shake raw/out:{jit[0]:.0f}/{jit[1]:.0f}px{' LOCK' if jit[2] else ''}" if jit else ""
    info_line = (
        f"FPS:{fps:4.1f} {w}x{h}{jit_txt} | {MODE_NAMES.get(mode, mode)} x{dpi_scale:.1f} | Axis:{axis_txt} "
        f"Rot:{float(engine.config.get('paper_rotation_deg', 0.0)):+.0f} | {vert_txt} | "
        f"Idx:{fmt('index')} Mid:{fmt('middle')} Ring:{fmt('ring')} Pinky:{fmt('pinky')} | Pos:{screen_pos}"
    )
    cv2.putText(frame, info_line, (16, 56), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (220, 220, 220), 1, cv2.LINE_AA)

    help_lines = (
        "[SPACE] Pause  [M] Mode  [ [ ] ] Speed  [+/-] Pinch  [Z] Calibrate  [H] Step 1 only  [V] Corners only  [F] Flip",
        "[J/L] Axis rotate -/+  [I/K] Up/down speed +/-  [X] Clear calib  [D] Pinch log  [P] Phone  [C] Cam  [S] Save  [Q] Quit",
    )
    for row, text in enumerate(help_lines):
        cv2.putText(frame, text, (16, 80 + row * 20), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (160, 200, 255), 1, cv2.LINE_AA)

    if status_msg:
        cv2.putText(frame, status_msg, (16, h - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2, cv2.LINE_AA)


MODE_NAMES = {"thumb": "THUMB", "range": "RANGE", "relative": "PEN", "absolute": "ABS"}
MODE_CYCLE = ("relative", "range", "thumb", "absolute")

# Window UI state shared with the mouse callback
UI: dict = {"reset_button": None, "reset_clicked": False, "hover": False}


def on_mouse(event: int, x: int, y: int, flags: int, param: object) -> None:
    """Camera-window clicks: the "reset calibration" button."""
    rect = UI.get("reset_button")
    inside = rect is not None and rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]
    UI["hover"] = inside
    if event == cv2.EVENT_LBUTTONUP and inside:
        UI["reset_clicked"] = True


def next_mode(engine: GestureEngine) -> str:
    cur = str(engine.config.get("movement_mode", "range")).lower()
    ready = {"thumb": engine.thumb_ready, "range": engine.range_ready}
    order = [m for m in MODE_CYCLE if ready.get(m, True)]
    return order[(order.index(cur) + 1) % len(order)] if cur in order else order[0]


def apply_calibration(engine: GestureEngine, mouse: MouseController, phases: tuple | None = None) -> str:
    """Start the calibration for the current mode (or the given steps) with the cursor centred."""
    phases = tuple(phases) if phases else engine.calibration_phases()
    mouse.release_all()
    mouse.center_cursor()
    engine.start_calibration(phases)
    names = {"x": "direction", "corners": "corners", "thumb": "thumb corners"}
    return "Calibration: " + " -> ".join(names[ph] for ph in phases)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Hand-Mouse: Control your OS mouse using Google MediaPipe hand tracking."
    )
    parser.add_argument(
        "--source",
        type=str,
        default="0",
        help="Camera source: USB webcam index ('0'), 'phone' (app-less smartphone browser), or IP URL",
    )
    parser.add_argument(
        "--phone-web",
        action="store_true",
        help="Start built-in HTTPS server so your smartphone can stream its camera via browser without any app",
    )
    parser.add_argument(
        "--phone-port",
        type=int,
        default=8443,
        help="Port for the built-in smartphone HTTPS web camera server (default: 8443)",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["range", "relative", "absolute"],
        default=None,
        help="Cursor movement mode: 'range' (hand range = monitor, default), 'relative' (pen) or 'absolute' (camera area = screen)",
    )
    parser.add_argument(
        "--dpi",
        type=float,
        default=None,
        help="Cursor speed multiplier (e.g. 1.5 = smaller hand movement covers the screen; range 0.2 - 10)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to custom gesture JSON config (default: config/gestures.json)",
    )
    parser.add_argument(
        "--no-mirror",
        action="store_true",
        help="Disable horizontal camera flip",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run camera & gesture visualization without moving the actual OS mouse cursor",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=0,
        help="Exit automatically after N frames (0 = run indefinitely)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    engine = GestureEngine(config_path=args.config)
    if args.mode:
        engine.set_movement_mode(args.mode)
    if args.dpi is not None:
        engine.set_dpi_scale(args.dpi)

    chosen_source = "phone" if args.phone_web else args.source
    cam_cfg = CameraConfig(
        source=CameraStream.parse_source(chosen_source),
        mirror=not args.no_mirror,
        phone_port=args.phone_port,
    )
    camera = CameraStream(cam_cfg)
    if not camera.open():
        print(
            f"[Error] Could not open camera source '{chosen_source}'.\n"
            "  - For USB webcam: python main.py --source 0\n"
            "  - For App-less Smartphone Browser: python main.py --phone-web",
            file=sys.stderr,
        )
        return 1

    tracker = HandTracker(num_hands=1)
    mouse = MouseController(dry_run=args.dry_run)

    paused = False
    status_msg = ""
    status_expire = 0.0
    frame_count = 0
    last_detections = []
    last_result = GestureResult()
    screen_pos = mouse.last_screen_pos
    never_calibrated = not engine.is_mode_calibrated()
    if bool(engine.config.get("calibrate_on_start", False)) or never_calibrated:
        apply_calibration(engine, mouse)
        screen_pos = mouse.last_screen_pos
    window = "Hand-Mouse (MediaPipe)"
    cv2.namedWindow(window)
    cv2.setMouseCallback(window, on_mouse)
    shown_corner = None

    print("=== Hand-Mouse Started ===")
    if camera.is_phone_web and camera.phone_server is not None:
        print(f"  [Smartphone Browser Mode] Open this URL on your phone (Chrome/Safari):")
        print(f"  >>> {camera.phone_server.url} <<<")
    else:
        print(f"  Camera Source : {camera.config.source}")
    print(f"  Movement Mode : {engine.config.get('movement_mode')}")
    print("  Pinch THUMB + INDEX to move the cursor; THUMB + MIDDLE = left click, THUMB + RING = right click.")
    print("  (M switches modes; thumb mode = thumb tip steers, index out / index+middle out click.)")
    print("  Click: THUMB + MIDDLE = left, THUMB + RING = right.")
    print("  Calibration: click '영점 재설정' in the window (or Z). H = step 1 only, V = corners only.")
    print("  If a pinch is missed, press 'D' right after: the last few seconds are saved to logs/.")
    print("  Press 'P' in window to switch to Smartphone Browser mode, 'C' for USB Webcam, 'Q' to quit.")

    try:
        while True:
            ok, frame = camera.read()
            if not ok or frame is None:
                time.sleep(0.01)
                continue

            # Only run MediaPipe detection when we have an actual camera feed (not on the QR waiting screen)
            should_detect = not camera.is_phone_web or (
                camera.phone_server is not None and camera.phone_server.has_client
            )

            if should_detect and camera.is_new_frame:
                detections = tracker.detect(frame)
                last_detections = detections

                if detections:
                    hand = detections[0]
                    result = engine.process(hand.landmarks, image_size=(frame.shape[1], frame.shape[0]))
                    last_result = result
                    if not paused:
                        screen_pos = mouse.apply(result, engine.config)
                    else:
                        screen_pos = mouse.last_screen_pos
                else:
                    result = engine.process(None)
                    last_result = result
                    mouse.release_all()
                    screen_pos = mouse.last_screen_pos
            else:
                detections = last_detections if should_detect else []
                result = last_result

            if detections:
                HandTracker.draw_hand(
                    frame,
                    detections[0].landmarks,
                    is_pinched=engine.is_pinched,
                    active_action=result.action,
                    active_finger=engine.active_finger,
                    distances=result.extension if engine.thumb_mode else result.distances,
                    thresholds=(
                        {k: float(engine.config.get("extend_on_ratio", 1.55)) for k in ("index", "middle")}
                        if engine.thumb_mode
                        else engine.enter_thresholds()
                    ),
                    high_is_on=engine.thumb_mode,
                )

            now = time.perf_counter()
            # Corner step: put the cursor on the corner being set, so it is clear which one.
            target = engine.corner_target
            if target != shown_corner:
                shown_corner = target
                if target is not None:
                    screen_pos = mouse.place_cursor(target[1], target[2])
            if UI["reset_clicked"]:
                UI["reset_clicked"] = False
                status_msg = apply_calibration(engine, mouse)
                status_expire = now + 2.5
            if engine.pop_calibration_done():
                engine.save_config()
                mouse.release_all()
                screen_pos = mouse.center_cursor()
                status_msg = "Calibration saved"
                status_expire = now + 3.0
            if now > status_expire:
                status_msg = ""

            # Process remote commands sent from the smartphone browser buttons
            if camera.is_phone_web and camera.phone_server is not None:
                for p_cmd in camera.phone_server.pop_commands():
                    if p_cmd == "toggle_mode":
                        new_mode = next_mode(engine)
                        engine.set_movement_mode(new_mode)
                        mouse.release_all()
                        status_msg = f"Switched Movement Mode -> {new_mode.upper()}"
                        status_expire = now + 2.5
                    elif p_cmd == "dpi_up":
                        cur_dpi = float(engine.config.get("dpi_scale", 1.0))
                        new_dpi = engine.set_dpi_scale(cur_dpi + 0.2)
                        status_msg = f"Speed UP -> x{new_dpi:.1f}"
                        status_expire = now + 2.5
                    elif p_cmd == "dpi_down":
                        cur_dpi = float(engine.config.get("dpi_scale", 1.0))
                        new_dpi = engine.set_dpi_scale(cur_dpi - 0.2)
                        status_msg = f"Speed DOWN -> x{new_dpi:.1f}"
                        status_expire = now + 2.5
                    elif p_cmd == "calibrate":
                        status_msg = apply_calibration(engine, mouse)
                        status_expire = now + 2.5
                    elif p_cmd in ("calibrate_x", "calibrate_corners"):
                        status_msg = apply_calibration(engine, mouse, ("x",) if p_cmd.endswith("x") else ("corners",))
                        status_expire = now + 2.5

            UI["jitter"] = (mouse.jitter_raw_px, mouse.jitter_out_px, mouse.locked)
            if should_detect:
                draw_hud(
                    frame=frame,
                    fps=camera.fps,
                    source=camera.phone_server.url if (camera.is_phone_web and camera.phone_server) else camera.config.source,
                    result=result,
                    screen_pos=screen_pos,
                    engine=engine,
                    paused=paused,
                    status_msg=status_msg,
                    screen_size=(mouse.screen_w, mouse.screen_h),
                    landmarks=detections[0].landmarks if detections else None,
                )

            cv2.imshow(window, frame)
            frame_count += 1
            if args.max_frames > 0 and frame_count >= args.max_frames:
                break

            key = cv2.waitKey(1) & 0xFF
            if key == 27 and engine.calibrating:
                engine.cancel_calibration()
                status_msg = "Calibration skipped - saved values kept (button / Z to calibrate)"
                status_expire = now + 2.5
            elif key in (27, ord("q"), ord("Q")):
                break
            elif key == ord(" "):
                paused = not paused
                if paused:
                    mouse.release_all()
                status_msg = "Mouse Control PAUSED" if paused else "Mouse Control RESUMED"
                status_expire = now + 2.0
            elif key in (ord("m"), ord("M")):
                new_mode = next_mode(engine)
                engine.set_movement_mode(new_mode)
                mouse.release_all()
                status_msg = f"Switched Movement Mode -> {new_mode.upper()}"
                status_expire = now + 2.0
            elif key in (ord("+"), ord("=")):
                thr = min(0.12, float(engine.config.get("pinch_threshold", 0.055)) + 0.005)
                engine.config["pinch_threshold"] = round(thr, 4)
                engine.config["click_threshold"] = round(thr + 0.02, 4)
                engine.config["release_threshold"] = round(thr + 0.025, 4)
                status_msg = f"Pinch Threshold -> {thr:.3f} (More sensitive)"
                status_expire = now + 2.0
            elif key in (ord("-"), ord("_")):
                thr = max(0.02, float(engine.config.get("pinch_threshold", 0.055)) - 0.005)
                engine.config["pinch_threshold"] = round(thr, 4)
                engine.config["click_threshold"] = round(thr + 0.02, 4)
                engine.config["release_threshold"] = round(thr + 0.025, 4)
                status_msg = f"Pinch Threshold -> {thr:.3f} (Stricter)"
                status_expire = now + 2.0
            elif key in (ord("]"), ord("}")):
                cur_dpi = float(engine.config.get("dpi_scale", 1.0))
                new_dpi = engine.set_dpi_scale(cur_dpi + 0.2)
                status_msg = f"Speed UP -> x{new_dpi:.1f} (smaller paper)"
                status_expire = now + 2.0
            elif key in (ord("["), ord("{")):
                cur_dpi = float(engine.config.get("dpi_scale", 1.0))
                new_dpi = engine.set_dpi_scale(cur_dpi - 0.2)
                status_msg = f"Speed DOWN -> x{new_dpi:.1f}"
                status_expire = now + 2.0
            elif key in (ord("z"), ord("Z")):
                status_msg = apply_calibration(engine, mouse)
                status_expire = now + 2.5
            elif key in (ord("h"), ord("H")):
                status_msg = apply_calibration(engine, mouse, ("x",))
                status_expire = now + 2.5
            elif key in (ord("v"), ord("V")):
                status_msg = apply_calibration(engine, mouse, ("corners",))
                status_expire = now + 2.5
            elif key in (ord("j"), ord("J"), ord("l"), ord("L")):
                step = -2.0 if key in (ord("j"), ord("J")) else 2.0
                deg = engine.adjust_paper_rotation(step)
                status_msg = f"Horizontal axis fine-tune {deg:+.0f} deg (S to save)"
                status_expire = now + 2.0
            elif key in (ord("i"), ord("I"), ord("k"), ord("K")):
                up = key in (ord("i"), ord("I"))
                if str(engine.config.get("vertical_source", "fingers")).lower() == "fingers":
                    gain = float(engine.config.get("curl_gain", 0.5)) * (1.15 if up else 1 / 1.15)
                    engine.config["curl_gain"] = round(max(0.05, min(5.0, gain)), 3)
                    status_msg = f"Up/down (finger curl) speed x{engine.config['curl_gain']:.2f} (S to save)"
                else:
                    deg = engine.adjust_paper_tilt(5.0 if up else -5.0)
                    status_msg = f"Paper tilt {deg:.0f} deg (S to save)"
                status_expire = now + 2.0
            elif key in (ord("d"), ord("D")):
                stamp = time.strftime("%Y%m%d_%H%M%S")
                log_path = engine.dump_debug(Path(__file__).resolve().parent / "logs" / f"pinch_{stamp}.csv")
                status_msg = f"Saved pinch log: logs/{log_path.name}"
                status_expire = now + 3.0
            elif key in (ord("x"), ord("X")):
                engine.clear_x_calibration()
                engine.clear_calibration()
                status_msg = "Calibration cleared: horizontal axis follows the hand (Z to calibrate)"
                status_expire = now + 2.0
            elif key in (ord("f"), ord("F")):
                inverted = not bool(engine.config.get("paper_invert_x", True))
                engine.config["paper_invert_x"] = inverted
                status_msg = f"Left/right {'inverted' if inverted else 'normal'} (S to save)"
                status_expire = now + 2.0
            elif key in (ord("r"), ord("R")):
                engine.load_config()
                status_msg = "Reloaded config/gestures.json"
                status_expire = now + 2.0
            elif key in (ord("s"), ord("S")):
                saved_path = engine.save_config()
                status_msg = f"Saved config to {saved_path.name}"
                status_expire = now + 2.0
            elif key in (ord("p"), ord("P")):
                camera.switch_source("phone")
                status_msg = "Switched to Smartphone Browser Camera Mode"
                status_expire = now + 2.5
            elif key in (ord("c"), ord("C")):
                if camera.is_phone_web:
                    camera.switch_source(0)
                    status_msg = "Switched to USB Webcam 0"
                elif isinstance(camera.config.source, int):
                    next_idx = (camera.config.source + 1) % 3
                    if camera.switch_source(next_idx):
                        status_msg = f"Switched to Camera Index {next_idx}"
                    else:
                        camera.switch_source(0)
                        status_msg = "Reverted to Camera Index 0"
                status_expire = now + 2.0
    finally:
        mouse.release_all()
        tracker.close()
        camera.release()
        cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
