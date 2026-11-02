"""
Hand-Mouse: MediaPipe Hand Tracking Mouse Controller
- Primary Gesture: Pinch Thumb (#4) + Index (#8) and move your hand up/down/left/right to move the cursor.
- Additional Gestures:
  - Thumb + Middle (#4 + #12): Left Click
  - Thumb + Ring (#4 + #16): Right Click
  - Thumb + Index + Middle (#4 + #8 + #12): Drag Hold (press & move)
  - Thumb + Pinky (#4 + #20): Drag Toggle
- Supports:
  1. USB Webcams (`--source 0`)
  2. App-less Smartphone Browser Camera (`--phone-web` or `--source phone`)
  3. Smartphone IP Camera Stream (`--source http://<IP>:8080/video`)
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Union

import cv2
import numpy as np

from src.camera import CameraConfig, CameraStream
from src.gesture_engine import GestureEngine, GestureResult
from src.hand_tracker import HandTracker
from src.mouse_controller import MouseController


def draw_hud(
    frame: np.ndarray,
    fps: float,
    source: Union[int, str],
    result: GestureResult,
    screen_pos: tuple[int, int],
    engine: GestureEngine,
    paused: bool,
    status_msg: str = "",
) -> None:
    """Draw real-time status overlay, active margin guide box, and keyboard shortcuts."""
    h, w = frame.shape[:2]
    margin = float(engine.config.get("active_margin", 0.15))
    mode = str(engine.config.get("movement_mode", "absolute")).upper()

    # Draw active screen mapping boundary in ABSOLUTE mode
    if mode == "ABSOLUTE":
        x1, y1 = int(margin * w), int(margin * h)
        x2, y2 = int((1.0 - margin) * w), int((1.0 - margin) * h)
        box_color = (0, 230, 118) if result.is_moving else (120, 120, 120)
        cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 1, cv2.LINE_AA)
        cv2.putText(
            frame,
            "Active Screen Area",
            (x1 + 6, y1 + 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            box_color,
            1,
            cv2.LINE_AA,
        )

    # Top semi-transparent status bar
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, 92), (18, 18, 24), -1)
    cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)

    state_color = (0, 255, 128) if result.is_moving else (200, 200, 200)
    if paused:
        state_text = "PAUSED (Press SPACE to resume)"
        state_color = (0, 180, 255)
    elif result.action == "move_cursor":
        state_text = "MOVING CURSOR (Thumb + Index Pinched)"
    elif result.action == "drag_hold":
        state_text = "DRAGGING (Thumb + Index + Middle)"
        state_color = (80, 160, 255)
    elif result.action in ("left_click", "right_click", "drag_toggle"):
        state_text = f"ACTION: {result.action.upper()}"
        state_color = (0, 120, 255)
    else:
        state_text = "IDLE (Pinch Thumb + Index to Move Cursor)"

    cv2.putText(
        frame,
        f"State: {state_text}",
        (16, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        state_color,
        2,
        cv2.LINE_AA,
    )

    pinch_thr = float(engine.config.get("pinch_threshold", 0.055))
    dist_str = f"{result.pinch_distance:.3f}" if result.pinch_distance < 1.0 else "---"
    info_line = (
        f"FPS: {fps:4.1f} | Cam: {source} | Mode: {mode} | "
        f"PinchDist: {dist_str} (Thr: {pinch_thr:.3f}) | Screen: {screen_pos}"
    )
    cv2.putText(
        frame,
        info_line,
        (16, 56),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        (220, 220, 220),
        1,
        cv2.LINE_AA,
    )

    help_line = (
        "[SPACE] Pause  [M] Mode(Abs/Rel)  [+/-] Pinch Sensitivity  "
        "[P] Phone-Web  [C] USB Cam  [R] Reload  [S] Save  [Q/ESC] Quit"
    )
    cv2.putText(
        frame,
        help_line,
        (16, 80),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.43,
        (160, 200, 255),
        1,
        cv2.LINE_AA,
    )

    if status_msg:
        cv2.putText(
            frame,
            status_msg,
            (16, h - 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )


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
        choices=["absolute", "relative"],
        default=None,
        help="Cursor movement mode: 'absolute' (screen mapping) or 'relative' (touchpad clutch mode)",
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

    print("=== Hand-Mouse Started ===")
    if camera.is_phone_web and camera.phone_server is not None:
        print(f"  [Smartphone Browser Mode] Open this URL on your phone (Chrome/Safari):")
        print(f"  >>> {camera.phone_server.url} <<<")
    else:
        print(f"  Camera Source : {camera.config.source}")
    print(f"  Movement Mode : {engine.config.get('movement_mode')}")
    print("  Primary Control: Pinch THUMB + INDEX together and move hand up/down/left/right.")
    print("  Press 'P' in window to switch to Smartphone Browser mode, 'C' for USB Webcam, 'Q' to quit.")

    try:
        while True:
            ok, frame = camera.read()
            if not ok or frame is None:
                time.sleep(0.03)
                continue

            # Only run MediaPipe detection when we have an actual camera feed (not on the QR waiting screen)
            should_detect = not camera.is_phone_web or (
                camera.phone_server is not None and camera.phone_server.has_client
            )

            if should_detect:
                detections = tracker.detect(frame)
            else:
                detections = []

            if detections:
                hand = detections[0]
                result = engine.process(hand.landmarks)
                if not paused:
                    screen_pos = mouse.apply(result, engine.config)
                else:
                    screen_pos = mouse.last_screen_pos

                HandTracker.draw_hand(
                    frame,
                    hand.landmarks,
                    is_pinched=engine.is_pinched,
                    active_action=result.action,
                )
            else:
                result = engine.process(None)
                mouse.release_all()
                screen_pos = mouse.last_screen_pos

            now = time.perf_counter()
            if now > status_expire:
                status_msg = ""

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
                )

            cv2.imshow("Hand-Mouse (MediaPipe)", frame)
            frame_count += 1
            if args.max_frames > 0 and frame_count >= args.max_frames:
                break

            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q"), ord("Q")):
                break
            elif key == ord(" "):
                paused = not paused
                if paused:
                    mouse.release_all()
                status_msg = "Mouse Control PAUSED" if paused else "Mouse Control RESUMED"
                status_expire = now + 2.0
            elif key in (ord("m"), ord("M")):
                cur_mode = str(engine.config.get("movement_mode", "absolute")).lower()
                new_mode = "relative" if cur_mode == "absolute" else "absolute"
                engine.set_movement_mode(new_mode)
                mouse.release_all()
                status_msg = f"Switched Movement Mode -> {new_mode.upper()}"
                status_expire = now + 2.0
            elif key in (ord("+"), ord("=")):
                thr = min(0.12, float(engine.config.get("pinch_threshold", 0.055)) + 0.005)
                engine.config["pinch_threshold"] = round(thr, 4)
                engine.config["release_threshold"] = round(thr + 0.02, 4)
                status_msg = f"Pinch Threshold -> {thr:.3f} (More sensitive)"
                status_expire = now + 2.0
            elif key in (ord("-"), ord("_")):
                thr = max(0.02, float(engine.config.get("pinch_threshold", 0.055)) - 0.005)
                engine.config["pinch_threshold"] = round(thr, 4)
                engine.config["release_threshold"] = round(thr + 0.02, 4)
                status_msg = f"Pinch Threshold -> {thr:.3f} (Stricter)"
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
