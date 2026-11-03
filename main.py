"""
Hand-Mouse: MediaPipe Hand Tracking Mouse Controller
- Snap & Fling: pinch Thumb + Index to catch the cursor, snap the wrist to throw it
  (distance depends on snap speed and direction). With no pinch, the wrist->palm point
  gives fine RELATIVE control with pointer acceleration ([M] switches to ABSOLUTE).
- Gestures:
  - Fist: same as no-pinch movement at 20x DPI (fast move)
  - Thumb tucked across the palm, other four fingers open (hold 0.4 s): show desktop (Win+D)
  - Thumb + Pinky: task switcher (point at a window, thumb+middle = open it, thumb+ring = cancel)
  - Thumb + Index (#4 + #8): Record & Fling (OFF by default, enable in the settings window) — draw a motion while pinched; on release the
    cursor replays that path (fast strokes amplified more), animated so the line is visible.
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
from pathlib import Path
import sys
import time
from typing import Union

import cv2
import numpy as np

from src.camera import CameraConfig, CameraStream
from src.gesture_engine import GestureEngine, GestureResult
from src.hand_tracker import HandTracker, pinch_guides
from src.mouse_controller import MouseController
from src.settings_panel import SettingsPanel
from src.hotkeys import VK_0, VK_F2, VK_NUMPAD0, VK_O, KeyPoller
from src.win_perf import keep_responsive_in_background
from src.perf_log import PerfLog
from src.pipeline import InferencePipeline, Snapshot
from src.status import describe_state, short_label
from src.overlay import CORNERS, StatusOverlay
from src.tray import TrayIcon
from src.ui_magnet import UITargetMagnet

WINDOW_NAME = "Hand-Mouse (MediaPipe)"  # must keep the "Hand-Mouse" prefix (hotkeys.py)


def draw_cursor_anchor(
    frame: np.ndarray,
    landmarks,
    anchor: tuple[float, float] | None,
    moving: bool,
) -> None:
    """Draw the wrist -> palm reference line and the cursor anchor point."""
    h, w = frame.shape[:2]
    wrist = (int(landmarks[0].x * w), int(landmarks[0].y * h))
    palm = (int(landmarks[9].x * w), int(landmarks[9].y * h))
    color = (0, 230, 118) if moving else (0, 140, 255)
    cv2.line(frame, wrist, palm, color, 3, cv2.LINE_AA)
    if anchor is not None:
        pt = (int(anchor[0] * w), int(anchor[1] * h))
        cv2.circle(frame, pt, 10, color, 2, cv2.LINE_AA)
        cv2.circle(frame, pt, 4, color, -1, cv2.LINE_AA)


def draw_recording(frame: np.ndarray, path) -> None:
    """Draw the pinch path being recorded (it is replayed by the cursor on release)."""
    if len(path) < 2:
        return
    h, w = frame.shape[:2]
    pts = np.array([[int(x * w), int(y * h)] for _, x, y in path], dtype=np.int32)
    cv2.polylines(frame, [pts], False, (255, 200, 0), 3, cv2.LINE_AA)
    cv2.circle(frame, tuple(pts[0]), 7, (255, 200, 0), 2, cv2.LINE_AA)
    cv2.circle(frame, tuple(pts[-1]), 5, (255, 255, 255), -1, cv2.LINE_AA)


def draw_hud(
    frame: np.ndarray,
    fps: float,
    source: Union[int, str],
    result: GestureResult,
    screen_pos: tuple[int, int],
    engine: GestureEngine,
    paused: bool,
    status_msg: str = "",
    grab_speed: float = 0.0,
    switcher_open: bool = False,
    detect_ms: float = 0.0,
    recent_action: str = "",
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

    state_text, state_rgb = describe_state(
        result,
        paused=paused,
        switcher_open=switcher_open,
        recent_action=recent_action,
        grab_speed=grab_speed,
        mode=mode,
    )
    state_color = state_rgb[::-1]  # RGB -> BGR for OpenCV

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
    d = result.distances or {}
    pky = d.get("pinky")
    mid, rng = d.get("middle"), d.get("ring")
    tk = d.get("thumb_tuck")
    pky_str = f"{pky:.3f}/{float(engine.config.get('pinky_click_threshold', 0.065)):.3f}" if pky is not None else "---"
    tk_str = f"{tk:.2f}/{float(engine.config.get('desktop_thumb_tuck', 0.45)):.2f}" if tk is not None else "---"
    info_line = (
        f"FPS: {fps:4.1f} Det: {detect_ms:4.1f}ms | {mode} | Idx: {dist_str}/{pinch_thr:.3f} | "
        f"Mid: {mid if mid is None else f'{mid:.3f}'}/{float(engine.config.get('click_threshold', 0.052)):.3f} "
        f"Rng: {rng if rng is None else f'{rng:.3f}'}/{float(engine.config.get('ring_click_threshold', 0.044)):.3f} | "
        f"Pky: {pky_str} | Tuck: {tk_str}"
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
        "[O/F2] SETTINGS  [SPACE] Pause  [M] Mode  [+/-] Pinch  [ [ / ] ] Fling  "
        "[P] Phone  [C] Cam  [R] Reload  [S] Save  [Q] Quit"
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


def render_snapshot(snap: Snapshot, engine: GestureEngine, status_msg: str = "") -> None:
    """Draw one pipeline snapshot onto its frame (runs on the main thread only)."""
    frame = snap.frame
    if snap.has_hand:
        HandTracker.draw_hand(frame, snap.landmarks, snap.guides)
        draw_cursor_anchor(frame, snap.landmarks, snap.palm_pt, snap.result.is_moving)
        draw_recording(frame, snap.recorded_path)
    if snap.should_detect:
        draw_hud(
            frame=frame,
            fps=snap.fps,
            source=snap.source,
            result=snap.result,
            screen_pos=snap.screen_pos,
            engine=engine,
            paused=snap.paused,
            status_msg=snap.fling_msg or status_msg,
            grab_speed=snap.grab_speed,
            switcher_open=snap.switcher_open,
            detect_ms=snap.detect_ms,
            recent_action=snap.recent_action,
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
        "--headless",
        action="store_true",
        help="No camera window: run in the background with a tray icon and a small status overlay "
             "(open the camera window again from the tray menu)",
    )
    parser.add_argument("--no-tray", action="store_true", help="Do not create the system tray icon")
    parser.add_argument("--overlay", action="store_true",
                        help="Show the small click-through status overlay even with the camera window open")
    parser.add_argument("--no-overlay", action="store_true", help="Never show the status overlay")
    parser.add_argument("--overlay-corner", choices=CORNERS, default="top-right",
                        help="Screen corner of the status overlay (default: top-right)")
    parser.add_argument(
        "--max-frames",
        type=int,
        default=0,
        help="Exit automatically after N frames (0 = run indefinitely)",
    )
    return parser.parse_args()


def _log_to_file_without_console() -> None:
    """pythonw.exe (run_admin.bat) has no console: keep messages and errors in a log file."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    log_dir = Path(__file__).resolve().parent / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        f = open(log_dir / "app_latest.log", "w", encoding="utf-8", buffering=1)
    except OSError:
        return
    sys.stdout = sys.stdout or f
    sys.stderr = sys.stderr or f


def main() -> int:
    _log_to_file_without_console()
    args = parse_args()
    perf = keep_responsive_in_background()

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
    settings = SettingsPanel(engine)
    keys = KeyPoller()
    perf_log = PerfLog(Path(__file__).resolve().parent / "logs" / "perf_latest.csv")
    # Aim assist: slow the cursor near clickable UI (reads engine.config live, [Settings] toggles it)
    magnet = UITargetMagnet(lambda: engine.config)
    mouse.slowdown_provider = magnet.factor
    magnet.start()
    pipeline = InferencePipeline(camera, tracker, engine, mouse, perf_log, max_frames=args.max_frames)

    hud_visible = not args.headless
    pipeline.publish_frames = hud_visible

    overlay: StatusOverlay | None = None
    overlay_wanted = (args.headless or args.overlay) and not args.no_overlay
    if overlay_wanted:
        overlay = StatusOverlay(corner=args.overlay_corner)
        overlay.start()

    tray: TrayIcon | None = None
    if not args.no_tray:
        tray = TrayIcon(
            is_paused=lambda: pipeline.paused,
            is_hud=lambda: hud_visible,
            is_overlay=lambda: overlay is not None and overlay.visible,
        )
        if not tray.start():
            tray = None
    if args.headless and tray is None:
        print("[Warn] --headless without a tray icon: stop the app from Task Manager.", file=sys.stderr)

    status_msg = ""
    status_expire = 0.0
    window_open = False

    print("=== Hand-Mouse Started ===")
    if perf:
        print(f"  Background performance: {', '.join(perf)}")
    if camera.is_phone_web and camera.phone_server is not None:
        print(f"  [Smartphone Browser Mode] Open this URL on your phone (Chrome/Safari):")
        print(f"  >>> {camera.phone_server.url} <<<")
    else:
        print(f"  Camera Source : {camera.config.source}")
    print(f"  Movement Mode : {engine.config.get('movement_mode')}")
    print("  Fine Control: move your hand with NO pinch (relative + acceleration, [M] = absolute).")
    print("  Make a FIST to move the same way at 20x DPI.")
    print("  Tuck the THUMB, open the other four fingers and hold 0.4 s = show desktop (Win+D).")
    print("  THUMB+PINKY opens the task switcher: point at a window, THUMB+MIDDLE opens it, THUMB+RING cancels.")
    if engine.config.get("record_fling_enabled", False):
        print("  Record & Fling ON: pinch THUMB+INDEX, draw a motion, release to replay it.")
    else:
        print("  THUMB+INDEX pinch = grab the page and scroll it like a touchscreen.")
    print("  Thumb+Middle = Left Click, Thumb+Ring = Right Click.")
    print("  Press 'O' (or '0', or F2 from any window) to open the SETTINGS window.")
    print("  Press 'P' in window to switch to Smartphone Browser mode, 'C' for USB Webcam, 'Q' to quit.")
    if tray is not None:
        print("  System tray icon: pause / camera window / status overlay / settings / quit.")
    if args.headless:
        print("  Headless: no camera window (open it from the tray menu).")

    def say(text: str, seconds: float = 2.0) -> None:
        nonlocal status_msg, status_expire
        status_msg, status_expire = text, time.perf_counter() + seconds

    def set_hud(visible: bool) -> None:
        nonlocal hud_visible
        hud_visible = visible
        pipeline.publish_frames = visible  # hidden => the pipeline skips the frame hand-off entirely

    def set_paused(value: bool) -> None:
        pipeline.set_paused(value)
        say("Mouse Control PAUSED" if value else "Mouse Control RESUMED")
        if tray is not None:
            tray.refresh()

    def toggle_settings() -> None:
        opened = settings.toggle()
        say("Settings window OPEN (sliders apply live, [S] to save)" if opened else "Settings window closed")

    def switch_mode() -> None:
        def task() -> str:
            cur = str(engine.config.get("movement_mode", "relative")).lower()
            new = "relative" if cur == "absolute" else "absolute"
            engine.set_movement_mode(new)
            mouse.release_all()
            return f"Switched Movement Mode -> {new.upper()}"
        pipeline.post(task)

    def switch_camera(target: str) -> None:
        def task() -> str:
            if target == "phone":
                camera.switch_source("phone")
                return "Switched to Smartphone Browser Camera Mode"
            if camera.is_phone_web:
                camera.switch_source(0)
                return "Switched to USB Webcam 0"
            if isinstance(camera.config.source, int):
                next_idx = (camera.config.source + 1) % 3
                if camera.switch_source(next_idx):
                    return f"Switched to Camera Index {next_idx}"
                camera.switch_source(0)
                return "Reverted to Camera Index 0"
            return ""
        pipeline.post(task)

    quit_requested = False
    pipeline.start()
    try:
        while not pipeline.finished and not quit_requested:
            # --- tray menu commands (executed here, on the main thread)
            while tray is not None and not tray.commands.empty():
                cmd = tray.commands.get_nowait()
                if cmd == "pause":
                    set_paused(not pipeline.paused)
                elif cmd == "hud":
                    set_hud(not hud_visible)
                    tray.refresh()
                elif cmd == "overlay":
                    if overlay is None:
                        overlay = StatusOverlay(corner=args.overlay_corner)
                        overlay.start()
                    else:
                        overlay.set_visible(not overlay.visible)
                    tray.refresh()
                elif cmd == "settings":
                    toggle_settings()
                elif cmd == "quit":
                    quit_requested = True
            while not pipeline.messages.empty():
                say(pipeline.messages.get_nowait())

            key = -1
            if hud_visible:
                snap = pipeline.wait_snapshot(0.05)
                if snap is not None and snap.frame is not None:
                    if time.perf_counter() > status_expire:
                        status_msg = ""
                    render_snapshot(snap, engine, status_msg)
                    cv2.imshow(WINDOW_NAME, snap.frame)
                    window_open = True
                key = cv2.waitKey(1) & 0xFF
                if window_open and cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                    # closed with the window's X button: hide to the tray, or quit without one
                    if tray is not None:
                        set_hud(False)
                        tray.refresh()
                    else:
                        quit_requested = True
            else:
                if window_open:
                    cv2.destroyAllWindows()
                    window_open = False
                time.sleep(0.04)  # no rendering at all: the main thread is (almost) idle

            if overlay is not None and overlay.visible:
                snap_now = pipeline.latest()
                if snap_now is not None:
                    overlay.set_state(*short_label(
                        snap_now.result, has_hand=snap_now.has_hand, paused=snap_now.paused,
                        switcher_open=snap_now.switcher_open, recent_action=snap_now.recent_action,
                    ))

            # Settings window: physical-key polling works in Korean IME mode too.
            # O / 0 while a Hand-Mouse window is focused, F2 from anywhere.
            want_settings = False
            if keys.available:
                want_settings = keys.pressed([VK_F2]) or keys.pressed(
                    [VK_O, VK_0, VK_NUMPAD0], require_focus=True
                )
            elif key in (ord("o"), ord("O"), ord("0")):
                want_settings = True
            if want_settings:
                toggle_settings()

            if key in (27, ord("q"), ord("Q")):
                break
            elif key == ord(" "):
                set_paused(not pipeline.paused)
            elif key in (ord("m"), ord("M")):
                switch_mode()
            elif key in (ord("+"), ord("=")):
                thr = min(0.12, float(engine.config.get("pinch_threshold", 0.055)) + 0.005)
                engine.config["pinch_threshold"] = round(thr, 4)
                engine.config["release_threshold"] = round(thr + 0.02, 4)
                say(f"Pinch Threshold -> {thr:.3f} (More sensitive)")
            elif key in (ord("-"), ord("_")):
                thr = max(0.02, float(engine.config.get("pinch_threshold", 0.055)) - 0.005)
                engine.config["pinch_threshold"] = round(thr, 4)
                engine.config["release_threshold"] = round(thr + 0.02, 4)
                say(f"Pinch Threshold -> {thr:.3f} (Stricter)")
            elif key in (ord("["), ord("]")):
                # Fling distance: ']' farther, '[' shorter (x1.2 per press, saved with 'S')
                cur = float(engine.config.get("fling_strength", 1.0))
                new = cur * 1.2 if key == ord("]") else cur / 1.2
                new = round(max(0.1, min(5.0, new)), 3)
                engine.config["fling_strength"] = new
                say(f"Fling Distance -> {new:.2f} ({'farther' if key == ord(']') else 'shorter'}, [S] to save)")
            elif key in (ord("r"), ord("R")):
                pipeline.post(lambda: (engine.load_config(), "Reloaded config/gestures.json")[1])
            elif key in (ord("s"), ord("S")):
                say(f"Saved config to {engine.save_config().name}")
            elif key in (ord("p"), ord("P")):
                switch_camera("phone")
            elif key in (ord("c"), ord("C")):
                switch_camera("next")
        if pipeline.error is not None:
            print(f"[Error] inference thread stopped: {pipeline.error!r}", file=sys.stderr)
    finally:
        pipeline.stop()
        magnet.shutdown()
        if tray is not None:
            tray.stop()
        if overlay is not None:
            overlay.shutdown()
        mouse.close()
        settings.shutdown()
        perf_log.close()
        mouse.release_all()
        tracker.close()
        camera.release()
        cv2.destroyAllWindows()

    return 1 if pipeline.error is not None else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:
        import traceback

        _log_to_file_without_console()
        traceback.print_exc()
        raise
