"""
Qt mode runtime: camera -> hand tracking -> pointer engine -> OS mouse on its own thread.

Before (2026-11-04) the Qt dashboard ran this inline on the UI thread, so a slow UI frame
delayed the cursor and vice versa, and a tray-only app had nothing to run on. Now:

- this thread owns the camera, MediaPipe, the pointer engine, the mouse, the hand-area crop,
  failure recording and the tracking test, and never touches Qt;
- the Qt thread hands over a `UiState` (what the user chose) and commands, and renders the
  newest `Snapshot` (preview frame, status, metrics, tracking-test view).

The same split lets a tray / overlay front end drive it without the dashboard window.
"""
from __future__ import annotations

import json
import math
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple

import cv2

from src.action_bindings import (CompositeGestureDetector, DEFAULT_GESTURE_BINDINGS, PALM_ACTION_KEYS, VIRTUAL_ACTION_KEYS,
                                 get_action_registry, use_binding_profile)
from src import default_moves
from src.failure_log import FailureRecorder
from src.finger_kinematics import CausalFingerTracker
from src.close_sign import CloseSign
from src.toggle_sign import ToggleSign
from src.motion_mode import ACTION_LABELS, MotionMode
from src.palm_axes import PalmAxesCalibration, valid_axes
from src.elbow_pivot import ElbowPivot
from src.pose_tracker import DEFAULT_POSE_MODEL, PoseTracker, pick_arm
from src.guided_recording import GuidedSession, tasks_for
from src.recorder import SessionRecorder
from src.gesture_gate import DEFAULT_MODEL as GATE_MODEL, GestureGate, load_predictor
from src.click_check import ClickCheck
from src.click_log import ClickLog
from src import use_gate
from src.use_log import UseLog, read_events as read_use_events, shadow_verdict
from src.online.use_import import CLICK_ACTIONS, click_base, click_key, click_name, learnable as use_import_learnable
from src.gesture_engine import GestureEngine, GestureResult
from src.hand_crop import HandCrop
from src.crop_recorder import CropRecorder, crops_path
from src.roi_tracker import RoiTracker, hand_box
from src.hand_selection import HandFollower, _center_and_size, merge_duplicates, selected_detection
from src.virtual_hand import hand_px
from src.virtual_hand import Responder as VhResponder, response as vh_response
from src.virtual_hand import (ACTION_NAMES as HAND_ACTION_NAMES, BoxMapper, DEFAULT_BOX, Grip, HandSize, PINCH_HOLD, Ratchet, ShapePinch, ShapeSwitch, ShapeTriple, ViewSmoother, triple_point,
                              click_offset, holds_still, pinch_point, VIRTUAL_OFF_ACTIONS, virtual_guides,
                              palm_centre, valid_box, view as virtual_hand_view)
from src.online.collector import OnlineCollector
from src.finger_overlay import overlay_frame, preview_hand
from src.pose_probe import PoseProbe, arm_label, hand_posture, hand_shot, relabelled, set_hand_label
from src.macro import cancel_all as cancel_macros
from src.sequence import SequenceDetector, SequenceStore
from src.path_gesture import PathDetector, PathStore
from src.point_mode import FileTargetProbe, PointMode, shape as point_shape
from src import hand_direction as hand_dir
from src.draw_mode import DrawMode, ShapeStore, ensure_bindings as ensure_draw_bindings

VH_ANCHOR_FOLLOW = .15   # share of the way the drawn hand's anchor follows its thumb-index point each frame (manux)
from src.perf_log import foreground_window_title
from src.online.commands import CommandGate, binding_key, command_of, command_text, forget_command
from src.online.pose_memory import POSE_FILE, PoseMemory, PoseRecognizer, pose_features
from src.online.registration import USER_SOURCE, RegistrationConfig, RegistrationError, RegistrationSession
from src.online.samples import DEFAULT_ROOT as ONLINE_DEFAULT_ROOT, SampleStore
from src.recorder import machine_info
from src.hand_tracker import HandLandmark, HandTracker, pinch_guides
from src.pointer_engine import PointerEngine, PointerSettings
from src.pointer_workspace import FINGERTIPS
from src.tracking_test import TrackingTest, result_line

ONE_SHOT = ("left_click", "right_click", "drag_toggle", "alt_tab", "show_desktop", "task_switcher")
USE_ACTIONS = ONE_SHOT + ("scroll_grab", "drag_hold")     # written to the use log when they start (src/use_log.py)
POINT_LIKE = frozenset({"index_point", "l_sign", "two_fingers"})   # hand shapes the pointing hand passes through
RIGHT_HOLD = .6          # s thumb + index + middle stay together before the virtual hand right-clicks (see _step)
POINT_QUIET = 1.5        # s after pointing mode (src/point_mode.py) before the V sign may switch the control
RETRY_SECONDS = 8.0      # a taught gesture its checking model keeps refusing: tries this close together count as one wish
RETRY_PASS = 3           # ... and the third one goes through
WAITING_USES = 4         # uses on a new day that start a round for a gesture whose checking model waits for one (verifier.MIN_HELD)
USE_LABELS = {"right_click": "thumb_ring", "left_click": "thumb_middle", "scroll_grab": "thumb_index",
              "task_switcher": "thumb_pinky", "show_desktop": "palm_side"}
USE_LABELS_VIRTUAL = {"left_click": "thumb_index", "drag_hold": "thumb_index", "right_click": "thumb_index_middle",
                      "scroll_grab": "fist"}              # the virtual hand's shapes (src/virtual_hand.py)


def _online_gate_class():
    try:
        from src.online.safety import OnlineGate
        return OnlineGate
    except Exception:          # no torch: there is no learned-model checker to tell apart
        return type(None)

FREEZE_SECONDS = .2     # a flicker of the recognition must not let the cursor jump

DOUBLE_TAP = .7     # seconds after a pinch click in which the next thumb + index press is the second click
CLICK_CHECK_THRESHOLD = .3   # TCN thumb_index peak over a press needed for a click. Held-out replay (16 recordings the TCN
# never saw, 2026-11-10): .3 keeps 93 % of thumb + index clicks and cuts rest-time closes only 8.5 -> 6.8 a minute, because most of
# those are real pinches right after a thumb + index task (labelled rest). Too little to pay 7 % of the clicks for: off by default
# ("virtual_click_check": true in config/gestures.json turns it on).
CLICK_NAMES = {"left": "좌클릭", "double": "더블클릭", "drag": "끌기", "right": "우클릭"}
PASSIVE_ACTIONS = frozenset({"none", "move_cursor", "pointer_wait"})   # the engine is doing nothing a hand shape would undo
VH_LOST_KEEP = .6     # seconds the drawn hand stays (faded) after the camera loses the hand (2026-11-11: .4 left 29 of
                      # 76 losses in the failure logs showing no hand; .6 covers 5 more)


@dataclass(frozen=True)
class UiState:
    """What the UI thread decided (replaced as a whole, read once per frame)."""
    stage: str = "splash"               # splash | welcome | capture | main
    control_hand: str = ""              # "Left" | "Right" | ""
    use_index_pointer: bool = True
    click_style: str = "pinch"
    anchor: str = "index"
    anchor_joints: Tuple[int, ...] = ()  # landmarks the cursor follows (palm mode / "직접 지정"); () = config default
    hand_crop: bool = False
    axes: Optional[Tuple[float, float, float, float]] = None
    calibrating: bool = False
    sensitivity: int = 100              # percent
    show_fingertips: bool = False
    profile: Optional[str] = None       # calibration profile the user picked (None = no profile)
    profile_epoch: int = 0              # +1 when the profile in use was reset / renamed: read its settings again
    motion_request: int = 0             # +1 each time the user presses the motion-mode button
    palm_axes_request: int = 0          # +1 per press of "cursor direction" (palm / fist cursor): start the wizard
    palm_axes_cancel: int = 0           # +1 per press of its cancel button
    palm_axes_reset: int = 0            # +1 per press of its reset button
    rec_mode: str = "off"               # dataset recording (src/recorder.py): "off" | "guided" | "free"
    rec_advance: int = 0                # +1 per press of "start" in guided recording
    tcn_gate: bool = False              # right click / scroll grab confirmed by the trained model (src/gesture_gate.py)
    gate_model: str = "tcn"             # "tcn" = models/gesture_tcn.onnx, "online" = the model learned from this person
    virtual_hand: bool = False          # the hand on the screen: a box on the camera image maps to the monitor (src/virtual_hand.py)
    virtual_box: Tuple[float, float, float, float] = DEFAULT_BOX
    screen_ratio: float = 1.0           # physical / logical pixels of the main screen (the drawn hand is in logical ones)
    rec_focus: str = ""                 # guided recording of one gesture only (training center "집중 녹화"); "" = all
    model_version: int = 0              # +1 when the training center saved a new model: reload the gate
    rec_plan: Optional[Dict[str, Any]] = None
    rec_paused: bool = False
    rec_discard: int = 0                # +1 per press of "녹화 취소 (버리기)"
    point_mode: bool = True             # pointing mode (src/point_mode.py), switched in the settings window
    point_settings: Optional[Dict[str, Any]] = None   # its details (src/point_mode.SETTINGS); None = defaults
    signal_text: bool = True            # the name of the signal written beside the drawn hand (settings window)


@dataclass
class Snapshot:
    seq: int
    frame: Any                          # annotated BGR frame for the preview
    detected: bool
    paused: bool
    action: str
    fps: float
    detect_ms: float
    status: str
    contacts: Tuple[int, ...] = ()
    tip: Optional[Tuple[float, float]] = None   # index fingertip (direction calibration)
    aspect: float = 1.0
    source: Any = 0
    mirrored: bool = True
    detections: List[Any] = field(default_factory=list)  # all hands (hand setup screen)
    metrics: Optional[Tuple[str, int, bool]] = None      # camera mode, brightness, dark
    tracking: Optional[Dict[str, Any]] = None             # tracking test view (None = closed)
    failures: Optional[Tuple[str, str]] = None            # summary, last file (when changed)
    recent_line: Optional[str] = None                     # new tracking result line
    message: str = ""                                      # one-off console message
    toggle_progress: float = 0.0                          # progress 0..1 of the on/off sign hold
    close_sign: Optional[Tuple[float, float, str]] = None  # (progress 0..1 of the close-window hold, seconds left to confirm, notice)
    motion: Optional[Tuple[bool, float, str, float, float]] = None  # on, seconds left (0 = no timeout), last command, entering 0..1, leaving 0..1
    palm_axes: Tuple[bool, str, float, str, bool] = (False, "", 0.0, "", False)  # wizard running, prompt, progress, note, correction saved
    rec: Optional[Dict[str, Any]] = None  # dataset recording view: mode, prompt, sub, progress, overall, waiting, frames, file
    gate_status: Optional[Dict[str, Any]] = None  # Stage 7: calibrated confidence & rejection reason from GestureGate
    registration: Optional[Dict[str, Any]] = None  # adding a new gesture: state, demo, seconds, report (src/online/registration.py)
    online_gesture: str = ""              # a registered gesture recognised right now (shown on the preview, sends nothing)
    virtual_hand: Optional[Dict[str, Any]] = None  # the hand drawn at the cursor (src/virtual_hand.py), None = no hand
    preview_hand: Optional[Dict[str, Any]] = None  # skeleton drawn over the preview by src/HandSkeleton.qml (src/finger_overlay.py)
    finger: Optional[Dict[str, Any]] = None        # fingertips drawn next to the cursor by src/FingerTracker.qml
    point: Optional[Dict[str, Any]] = None         # pointing mode: kind, dwell progress 0..1, on a file (src/point_mode.py)
    pose_probe: Optional[Dict[str, Any]] = None    # [손 모양 보여주기] countdown / holding / result (src/pose_probe.py)
    pose_probe_shot: Optional[Tuple[Any, ...]] = None  # (number, BGR hand picture, the look's pictures in order) of that result
    draw: Optional[Dict[str, Any]] = None          # drawing mode: pen, stroke, last recognised shape (src/draw_mode.py)
    hand_lost: bool = False               # no hand for `hand_lost_alert` seconds: the screen shows it big
    arm_lost: bool = False                # Pose has not seen the arm for `arm_lost_alert` seconds (only when Pose runs)
    admin_blocked: bool = False           # an admin window (Task Manager) is in front and this app is not admin: input is dropped
    learn_request: Tuple = (0, "")  # (+1 per request, use log folder): start a learning round from the use log
    onnx_request: int = 0                 # +1 = the UI thread should train a candidate of models/gesture_tcn.onnx
    base_request: int = 0                 # +1 = the UI thread should make the base model (scripts/online_make_base.py)
    learn_advice: str = ""                # what the app makes of learning rounds that were cut off (round_marker.advice)
    learn_note: str = ""               # the main screen's line: taught gestures' uses being collected / learned
    learn_items: List[Dict[str, Any]] = field(default_factory=list)   # the same, one card per gesture


def tracking_view(test: TrackingTest, cursor) -> Dict[str, Any]:
    """Everything the test window shows, as plain data (no shared mutable object)."""
    t = test.current
    return {
        "done": test.done,
        "paused": test.paused,
        "index": test.index,
        "total": len(test.targets),
        "target": None if t is None else (t.fx, t.fy, t.size_px / test.monitor.width),
        "holding": t is not None and t.inside_since is not None,
        "hand_present": test.hand_present,
        "cursor": test.cursor_fraction(cursor),
        "summary": test.summary_text() if test.done else "",
    }


def ui_style(ui) -> str:
    return getattr(ui, "click_style", "")


def ui_gate_on(rt) -> bool:
    return bool(getattr(rt.ui, "tcn_gate", False))


class QtRuntime:
    def __init__(self, *, camera, tracker: HandTracker, engine: GestureEngine, mouse, perf_log,
                 config_path=None, dry_run: bool = False, max_frames: int = 0,
                 draw_cursor_anchor: Callable = None, draw_recording: Callable = None,
                 log_dir: Optional[Path] = None, online_root: Optional[Path] = None) -> None:
        self.camera, self.tracker, self.engine, self.mouse = camera, tracker, engine, mouse
        self.online: Optional[OnlineCollector] = None     # config "online_learning_enabled" (docs/online-learning-design.md)
        self._online_root = online_root
        self._online_failed = False
        self.online_memory: Optional[PoseMemory] = None
        self.recognizer: Optional[PoseRecognizer] = None
        self.registration: Optional[RegistrationSession] = None
        self.registration_config: Optional[RegistrationConfig] = None
        self._registration_view: Optional[Dict[str, Any]] = None
        self._online_gesture = ""
        self._online_gesture_until = 0.0
        self._virtual_hand: Optional[Dict[str, Any]] = None
        self.vh_responder = VhResponder()              # fast / smooth filters by what the hand is doing
        self.box_mapper = BoxMapper()
        self.view_smoother = ViewSmoother()
        self.hand_size = HandSize()      # the drawn hand's scale, steady when the hand turns
        self._vh_click: Optional[List[float]] = None   # pinch point on the drawn hand, frozen while the fingers touch
        self._vh_engaged = False
        # thumb-index point of the drawn hand (logical px from the palm): the drawing is shifted so it sits on the cursor.
        # Follows slowly, frozen while clicking or gripping (manux-merged-20261110 VirtualHandFeature._anchor).
        self._vh_anchor: Optional[List[float]] = None
        self.shape_pinch = ShapePinch("index")         # thumb + index = left click / drag, from the hand shape only
        self.shape_right = ShapeTriple()               # thumb + index + middle together = right click, from the hand shape only
        self._pinch_triple = False                     # this thumb + index press became the three-finger right click
        self.click_check: Optional[ClickCheck] = None  # the TCN's second look at thumb + index clicks (loaded on first use)
        self.use_log: Optional[UseLog] = None          # joints around every command + the TCN's shadow verdict (logs/use_events)
        self._watchers: Dict[str, GestureGate] = {}    # "tcn" / "online": the models only watching (copies that block nothing)
        self._watch_loading: set = set()
        self._watch_stale: set = set()
        self._use_watchers: Dict[str, GestureGate] = {}   # this frame's watchers: the real checker for its kind, else the copy
        self._use_real_kind = ""                       # which kind the switched-on intent checker is ("" = off)
        self._use_gate: Dict[str, Dict[str, Any]] = {} # commands a watching model may stop (src/use_gate.py)
        self._use_deciding = False
        self._use_blocking: Optional[str] = None
        self.use_blocked = 0
        self._use_round_t = 0.0                        # last time a learning round was asked for
        self._use_round_events = 0
        self._use_round_marks = 0
        self._use_pending: Dict[str, int] = {}         # taught gesture -> its uses no learning round has taken yet
        self._use_names: Dict[str, str] = {}
        self._use_status: Dict[str, Dict[str, Any]] = {}   # taught gesture -> what the last round found (verifiers/status.json)
        self._use_retries: Dict[str, List[float]] = {} # taught gesture -> when its checking model said no lately
        self._use_forced: Optional[str] = None         # the gesture just let through on its third try
        self._click_kind = ""                          # "double" on the frame of a double click's second tap (use_import.click_key)
        self._learn_note = ""                          # the main screen's line about collecting / learning
        self._learn_items: List[Dict[str, Any]] = []   # the same as cards: key, name, state, n, need, text, hint
        self._use_rounds = 0
        self._use_new: Dict[str, int] = {}             # per gesture: collected uses the person has not judged yet
        self._learn_request = 0                        # +1 = the UI thread should start a learning round from the use log
        self._use_t = 0.0
        self._use_prev_action = "none"
        self.click_log: Optional[ClickLog] = None      # everyday virtual hand clicks + F "not a click" marks (logs/virtual_clicks)
        self._triple_open_t = -1e9                     # when the three fingers last came apart
        self.shape_switch = ShapeSwitch()              # thumb folded, four fingers up = task switcher, from the hand shape only
        self.point = PointMode()                       # finger-gun: index tip moves the cursor, resting on a file clicks it
        self._point_seen = -1e9                        # when pointing mode was last on (the V sign waits after it)
        self._inspect: Tuple[str, float] = ("", 0.0)   # control off: the last signal the hand made, and until when it is shown
        self._inspect_detector: Optional[CompositeGestureDetector] = None
        self.point_probe = FileTargetProbe()           # is a file / folder under the cursor (UI Automation, own thread)
        self._point_view: Optional[Dict[str, Any]] = None
        self.grip = Grip()                             # what the virtual hand holds: a file (drag) or the page (scroll)
        self.holds = default_moves.HoldRemap()         # fist scroll / drags connected to another command (src/default_moves.py)
        self.ratchet = Ratchet()                       # a fist scrolls one way: bringing the hand back is not a scroll
        self._fist_y: Optional[float] = None           # where the page is held: follows the palm only while the hand is a fist
        self._palm_trail: List[Tuple[float, float, float]] = []   # (time, palm x, palm y) of the last moments: how fast the hand travels
        self._pinch_moving = False                     # this thumb + index pinch closed while the hand was travelling
        self._pinch_since: Optional[float] = None      # thumb + index closed since (shape pinch)
        self._pinch_drag = False
        self._pinch_double = False                     # this press is a double click's second click
        self._pinch_rejected = False                   # the click check dropped this press while it was held
        self._last_tap: Optional[Tuple[float, Tuple[int, int]]] = None   # (time, screen point) of the last pinch click
        self._vh_last: Optional[Dict[str, Any]] = None  # the last drawn hand, kept a moment when the camera loses the hand
        self._vh_lost: Optional[float] = None
        self.command_gate = CommandGate()
        self._online_model_version = 0
        self._freeze_until = 0.0
        self.perf_log = perf_log
        self.dry_run = dry_run
        self.max_frames = int(max_frames)
        self._draw_cursor_anchor = draw_cursor_anchor
        self._draw_recording = draw_recording
        # True: the hand skeleton and cursor anchor are drawn by QML over the preview instead of into the camera frame
        self.qml_skeleton = True
        self.pose_probe = PoseProbe()      # "this hand shape" for the AI binding helper (src/llm_binding.py)
        from src import custom_postures
        custom_postures.register()         # the hand shapes the user named join the posture lists
        self.draw_store = ShapeStore()
        self.seq_store = SequenceStore()       # gesture sequences: shapes in order run a command (src/sequence.py)
        self.path_store = PathStore()          # shape-drawing gestures: e.g. a fist drawing a circle (src/path_gesture.py)
        self.paths = PathDetector()
        self.sequences = SequenceDetector()
        self.draw = DrawMode(self.draw_store)   # drawing mode: shapes drawn on the monitor run commands
        try:
            ensure_draw_bindings(get_action_registry(), self.draw_store)
        except Exception:
            pass
        self._preview_hand: Optional[Dict[str, Any]] = None
        self._finger: Optional[Dict[str, Any]] = None
        self.log_dir = log_dir or Path(__file__).resolve().parents[1] / "logs"

        self.pointer = PointerEngine(GestureEngine(config_path=config_path))
        # crop_min_px: how small the crop around a far hand may get (the hand then fills more of what MediaPipe sees)
        self.hand_crop = HandCrop(min_px=int(engine.config.get("crop_min_px", 96)),
                                  scale=float(engine.config.get("crop_scale", 2.4)),
                                  search_seconds=float(engine.config.get("crop_search_seconds", 0.0)),
                                  collapse_ratio=float(engine.config.get("crop_collapse_ratio", 0.0)))
        self._search_frames = 0
        # while the detector has lost the hand, a video tracker keeps the crop on it (src/roi_tracker.py)
        self.roi_tracker = RoiTracker(str(engine.config.get("crop_tracker", "off")),
                                      float(engine.config.get("crop_track_seconds", 3.0)))
        self.failures = FailureRecorder(self.log_dir / "failures")
        self.test: Optional[TrackingTest] = None

        self.ui = UiState()
        self.paused = True
        self.frames = 0
        self.error: Optional[BaseException] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._commands: "queue.Queue[tuple]" = queue.Queue()
        self._cond = threading.Condition()
        self._snap: Optional[Snapshot] = None
        self._seen = 0

        self._had_hand = False
        self._det_path = ""
        self._hand_follower = HandFollower()
        self._applied_profile = engine.profile_name
        self.motion = MotionMode(engine.config)
        self.close_sign = CloseSign(engine.config)
        self.toggle_sign = ToggleSign(engine.config)
        self.finger_tracker = CausalFingerTracker()
        self.composite_detector = CompositeGestureDetector(get_action_registry())
        # the composite gestures marked "motion mode only": judged while motion mode is on, by their own detector
        self.motion_composite_detector = CompositeGestureDetector(get_action_registry())
        self._guided_rep_token = None
        self._close_notice, self._close_notice_until = "", 0.0
        self._motion_seen = 0
        self._motion_last = ""
        self._palm_seen = (0, 0, 0)               # palm_axes_request / cancel / reset already handled
        self._palm_cal: Optional[PalmAxesCalibration] = None
        self._palm_note, self._palm_note_until = "", 0.0
        # Elbow pivot (src/elbow_pivot.py): estimated from the palm's arcs, used by the palm / fist cursor when
        # `elbow_pivot` is on. The mouse controller reads it; this thread feeds it.
        self.elbow = ElbowPivot(engine.config)
        mouse.elbow_pivot = self.elbow
        # Arm tracking (src/pose_tracker.py): shoulder / elbow / wrist of the cursor arm, every few frames (palm mode)
        self.pose: Optional[PoseTracker] = None
        if engine.config.get("pose_enabled", False) and DEFAULT_POSE_MODEL.exists():
            try:
                self.pose = PoseTracker()
            except Exception as exc:                # a broken model must not stop the app
                print(f"  [Warn] Pose model not loaded: {exc}")
        self._arm = None
        self._arm_t = -1e9
        self._hand_seen_t = time.perf_counter()
        self._crop_rec: Optional[CropRecorder] = None      # hand pictures of a guided recording (rec_save_crops)
        self._admin_blocked, self._admin_checked_t = False, 0.0
        self._pose_raw: Optional[Tuple[float, list]] = None     # (time, Pose joints 11-16 as x, y, visibility) unsmoothed
        # Dataset recording (src/recorder.py, src/guided_recording.py)
        self.rec_dir = Path(__file__).resolve().parents[1] / "recordings"
        self._rec: Optional[SessionRecorder] = None
        self._guided: Optional[GuidedSession] = None
        self._rec_mode = "off"
        self._rec_adv_seen = 0
        self._rec_note, self._rec_note_until = "", 0.0
        self._last_pipeline_result: Optional[Dict[str, Any]] = None
        self.training_job = None
        # Intent check by the trained gesture model (loaded the first time it is switched on)
        self.gate: Optional[GestureGate] = None
        self._gate_failed = False
        self._elbow_announced = False
        self._was_dragging = False
        self._seen_inertia = None
        self._last_scroll_total = [0, 0]
        self._raw_hands: list = []
        self._last_step_t = 0.0
        self._status, self._status_until = "", 0.0
        self._recent_action, self._recent_until = "", 0.0
        self._last_fling = 0
        self._metrics: Optional[Tuple[str, int, bool]] = None
        self._pending_failures: Optional[Tuple[str, str]] = None
        self._pending_recent: Optional[str] = None
        self._pending_message = ""

    # ------------------------------------------------------------------ any thread
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="qt-runtime", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.point_probe.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=3.0)

    @property
    def finished(self) -> bool:
        return self._stop.is_set() or (self._thread is not None and not self._thread.is_alive())

    def post(self, *command) -> None:
        """("key", code) | ("pause",) | ("tracking_start",) | ("tracking_close",) | ("failure_mark",)"""
        self._commands.put(command)

    def wait_snapshot(self, timeout: float = .03) -> Optional[Snapshot]:
        with self._cond:
            self._cond.wait_for(lambda: self._snap is not None and self._snap.seq != self._seen, timeout)
            if self._snap is None or self._snap.seq == self._seen:
                return None
            self._seen = self._snap.seq
            return self._snap

    # ------------------------------------------------------------------ runtime thread
    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self._step()
                if self.max_frames > 0 and self.frames >= self.max_frames:
                    break
        except BaseException as exc:  # surfaced to the UI thread through .error / .finished
            self.error = exc
            raise
        finally:
            self._stop.set()
            try:
                self.mouse.release_all()
            except Exception:
                pass
            if self.online is not None:
                try:
                    self.online.close()
                except Exception:
                    pass
            if self.use_log is not None:
                try:
                    self.use_log.close()
                except Exception:
                    pass
            try:
                self._stop_recording(time.perf_counter())   # quitting mid-recording still leaves a complete file
            except Exception:
                pass
            with self._cond:
                self._cond.notify_all()

    def _say(self, text: str, seconds: float = 2.0) -> None:
        self._status, self._status_until = text, time.perf_counter() + seconds

    def _pause(self) -> None:
        self.paused = True
        cancel_macros()          # a running macro stops between steps (Pause = emergency stop)
        self.mouse.close_switcher(confirm=False)
        self.mouse.release_all()
        self.engine.reset()
        self._recent_until = 0.0

    def _record_negative_candidate(self, now: float, source: str, note: str = "") -> None:
        g_stat = self.gate.status_summary() if self.gate is not None else {}
        recent_act = getattr(self, "_recent_action", "") if now < getattr(self, "_recent_until", 0.0) + 2.0 else None
        self._use_mark(now, source)
        self.failures.record_negative_candidate(
            now,
            source=source,
            suspected_action=recent_act,
            suspected_gesture=g_stat.get("top_gesture", ""),
            calibrated_confidence=g_stat.get("calibrated_confidence"),
            rejection_reason=g_stat.get("rejection_reason", ""),
            note=note,
        )

    def _drain(self, now: float) -> None:
        while True:
            try:
                cmd = self._commands.get_nowait()
            except queue.Empty:
                return
            kind = cmd[0]
            if kind == "pause":
                if not self.paused and now < getattr(self, "_recent_until", 0.0) + 1.0:
                    self._record_negative_candidate(now, "user_cancelled", "Paused immediately after action")
                self._pause()
            elif kind == "tracking_start" and self.test is None:
                self.mouse.release_all()
                self.mouse.warp_to(*self.mouse.screens.primary.center)
                self.test = TrackingTest(self.mouse.screens.primary)
            elif kind == "tracking_close":
                self.test = None
                self._pause()
            elif kind == "mark_recent":
                # F8 (any window): only "the click or command of the last 5 seconds was not meant" - never the wider
                # failure record or the "what was it?" question, which belong to the F key in the app's own window
                if not self._virtual_click_mark(now):
                    hit = self.use_log.mark_last(now, "f8_key") if self.use_log is not None else None
                    if hit is not None:
                        self._say(f"방금 {self._use_name(str(hit.get('key') or ''))}: '원하지 않음'으로 기록했어요", 1.5)
                    else:
                        self._say("최근 5초 안에 표시할 클릭·명령이 없어요", 1.5)
            elif kind == "failure_mark" and self._virtual_click_mark(now):
                pass
            elif kind == "failure_mark":
                if self._rec is not None:
                    self._rec.event(now, "mark")
                self._record_negative_candidate(now, "f_key", "Manual failure mark button")
                if self.online is not None:
                    self.online.capture_recent(now)      # the window then asks what it really was (main.py run_qt)
                if self.failures.trigger(now, "manual"):
                    self._say("실패·오작동 부정 후보 기록 (자동 재학습 미투입)")
            elif kind == "return_block_mark":
                if self._rec is not None:
                    self._rec.event(now, "return_blocked_fp")
                if self.failures.mark_return_block_fp(now, note="Manual return block false-positive mark"):
                    self._say("이동 차단 오탐 기록 (복귀 억제 오작동)")
            elif kind == "rec_discard":
                self._discard_recording(now)
            elif kind == "register_start":
                self._register_start(cmd[1], now)
            elif kind == "register_approve":
                self._register_approve()
            elif kind == "register_cancel":
                self._register_cancel()
            elif kind == "draw_mode":
                self._set_draw(not self.draw.active if cmd[1] is None else bool(cmd[1]))
            elif kind == "use_recount":
                self._use_decide(recount=True)         # the person judged collected uses (src/use_review.py): count again
            elif kind == "seq_reload":
                self.seq_store.load()
                self.sequences.reset()
                self.path_store.load()
                self.paths.reset()
            elif kind == "draw_reload":
                self.draw_store.load()
                try:
                    ensure_draw_bindings(get_action_registry(), self.draw_store)
                except Exception:
                    pass
            elif kind == "pose_probe":
                self.pose_probe.start(now)
            elif kind == "pose_probe_cancel":
                self.pose_probe.cancel()
            elif kind == "pose_teach_save":
                self._pose_teach_save(cmd[1])
            elif kind == "gesture_delete":
                self._gesture_delete(cmd[1])
            elif kind == "online_reload":
                self._online_reload()
            elif kind == "key":
                self._key(cmd[1], now)

    def _key(self, key: int, now: float) -> None:
        engine, mouse, camera = self.engine, self.mouse, self.camera
        if self.registration is not None and self.registration.active and key in (27, ord(" ")):
            if key == 27:
                self._register_cancel()      # Space must not start the mouse in the middle of demonstrations
            return
        if key in (27, ord(" ")):
            was_paused = self.paused
            if not was_paused and now < getattr(self, "_recent_until", 0.0) + 1.0:
                self._record_negative_candidate(now, "user_cancelled", "Key pause immediately after action")
            self._pause()
            self.paused = key == 27 or not was_paused or self.ui.stage != "main"
            self._say("Mouse Control PAUSED" if self.paused else "Mouse Control RESUMED")
        elif key in (ord("m"), ord("M")):
            new = "relative" if str(engine.config.get("movement_mode", "relative")).lower() == "absolute" else "absolute"
            engine.set_movement_mode(new)
            mouse.release_all()
            self._say(f"Switched Movement Mode -> {new.upper()}")
        elif key in (ord("f"), ord("F")) and self._virtual_click_mark(now):
            pass
        elif key in (ord("f"), ord("F")):
            if self._rec is not None:
                self._rec.event(now, "mark")
            self._record_negative_candidate(now, "f_key", "User pressed F key")
            if self.failures.trigger(now, "manual"):
                self._say("실패·오작동 부정 후보 기록 (자동 재학습 미투입)")
        elif key in (ord("g"), ord("G")):
            if self._rec is not None:
                self._rec.event(now, "return_blocked_fp")
            if self.failures.mark_return_block_fp(now, note="User pressed G key (return block false positive)"):
                self._say("이동 차단 오탐 기록 (G 키)")
        elif key in (ord("n"), ord("N")):
            mouse.release_all()
            target = mouse.cycle_monitor()
            self._say(f"Monitor {mouse.screens.monitors.index(target) + 1}/{len(mouse.screens)}")
        elif key in (ord("+"), ord("="), ord("-"), ord("_")):
            step = .005 if key in (ord("+"), ord("=")) else -.005
            thr = max(.02, min(.12, float(engine.config.get("pinch_threshold", .055)) + step))
            engine.config["pinch_threshold"] = round(thr, 4)
            engine.config["release_threshold"] = round(thr + .02, 4)
            self._say(f"Pinch Threshold -> {thr:.3f}")
        elif key in (ord("["), ord("]")):
            cur = float(engine.config.get("fling_strength", 1.0))
            new = round(max(.1, min(5.0, cur * 1.2 if key == ord("]") else cur / 1.2)), 3)
            engine.config["fling_strength"] = new
            self._say(f"Fling Distance -> {new:.2f} ([S] to save)")
        elif key in (ord("r"), ord("R")):
            engine.load_config()
            self._say("Reloaded config/gestures.json")
        elif key in (ord("s"), ord("S")):
            self._say(f"Saved config to {engine.save_config().name}")
        elif key in (ord("p"), ord("P")):
            camera.switch_source("phone")
            self._say("Switched to Smartphone Browser Camera Mode", 2.5)
        elif key in (ord("c"), ord("C")):
            if camera.is_phone_web:
                camera.switch_source(0)
                self._say("Switched to USB Webcam 0")
            elif isinstance(camera.config.source, int):
                nxt = (camera.config.source + 1) % 3
                if camera.switch_source(nxt):
                    self._say(f"Switched to Camera Index {nxt}")
                else:
                    camera.switch_source(0)
                    self._say("Reverted to Camera Index 0")

    def _step(self) -> None:
        camera, tracker, engine, mouse, pointer = self.camera, self.tracker, self.engine, self.mouse, self.pointer
        self._drain(time.perf_counter())
        ui = self.ui
        ok, frame = camera.read()
        t0 = time.perf_counter()
        if not ok or frame is None:
            if self._guided is not None:
                self._guided.update(t0, available=False)
            pointer.frame_missing()
            if self._had_hand or mouse.is_dragging:
                # the camera stopped (unplugged, the phone app closed) in the middle of a drag: without this the mouse
                # button stayed down until Pause, because the "hand lost" release below is never reached
                mouse.close_switcher(confirm=False)
                mouse.release_all()
                engine.reset()
                self._had_hand = False
            time.sleep(.03)
            return
        # The preview is drawn on `frame` itself, later in this step. What keeps pixels for later needs the camera's picture.
        clean = frame.copy() if self._crop_rec is not None or (ui.hand_crop and self.roi_tracker.enabled) else None

        if ui.anchor_joints != self.engine.cursor_anchor_override:
            # the user picked other skeleton points as the cursor reference (both engines use it)
            self.engine.cursor_anchor_override = tuple(ui.anchor_joints)
            self.pointer.gestures.cursor_anchor_override = tuple(ui.anchor_joints)
        if ui.profile != self._applied_profile or ui.profile_epoch != getattr(self, "_profile_epoch", 0):
            self._profile_epoch = ui.profile_epoch
            # the user picked another calibration profile: both engines reload their config
            self._applied_profile = ui.profile
            self.engine.set_profile(ui.profile)
            self.pointer.gestures.set_profile(ui.profile)
            # ... and the profile's own bindings (the engines switched the registry): the detectors that read the
            # composite gestures start again on it, and a binding's remembered on/off is asked again
            reg = use_binding_profile(self.engine.profile_name)
            self.composite_detector = CompositeGestureDetector(reg)
            self.motion_composite_detector = CompositeGestureDetector(reg)
            self._binding_cache = {}
            try:
                ensure_draw_bindings(reg, self.draw_store)
            except Exception:
                pass
            self._say(f"프로필: {ui.profile or '없음'} (동작 연결도 이 프로필 것으로)", 2.0)
        should_detect = not camera.is_phone_web or (camera.phone_server is not None and camera.phone_server.has_client)
        roi = self.hand_crop.roi if ui.hand_crop else None
        if should_detect:
            detections = tracker.detect(frame, roi=roi)
            searching = roi is not None and self.hand_crop.searching
            self._det_path = "search" if searching else "crop" if roi is not None else "full"
            self._search_frames = self._search_frames + 1 if searching else 0
            if roi is not None and not detections and searching and self._search_frames % 6:
                pass   # a far hand is too small for the whole frame: it is only tried now and then during the search
            elif roi is not None and not detections:
                # the crop stays (HandCrop.miss) so the next frames try it again; this frame falls back to the full frame
                roi = None
                self._det_path = "search_miss>full" if searching else "crop_miss>full"
                detections = tracker.detect(frame)
        else:
            detections = []
            self._det_path = "skipped"
        all_detections = list(detections)
        # every hand MediaPipe returned this frame, before the control-hand filter below
        # (+ box centre x, y and longer side: 2026-11-11, to tell a flipped reading of the control hand from the other hand)
        self._raw_hands = [[d.handedness, round(float(d.score), 2),
                            *[round(v, 3) for v in (lambda c, s: (c[0], c[1], s))(*_center_and_size(d))]]
                           for d in all_detections]

        if ui.stage != "main":
            if not self.paused:
                self._pause()
            detections = []
            self._hand_follower.reset()
        else:
            if engine.config.get("hand_follow_enabled", True):
                chosen = self._hand_follower.select(detections, ui.control_hand, camera.config.mirror, t0)
                if self._hand_follower.followed:
                    self._det_path += "+follow"
            else:
                chosen = selected_detection(merge_duplicates(detections), ui.control_hand, camera.config.mirror)
            detections = [chosen] if chosen is not None else []
            if detections:
                self._hand_seen_t = t0
        self.mouse.hand_size = self._hand_width_fraction(detections[0].landmarks, frame.shape[1], frame.shape[0]) if detections else None
        live = ui.stage == "main" and not self.paused and not self.draw.active and not ui.calibrating
        # which hand the shapes of this frame are judged for: an open hand showing its back is told from its palm by it
        # (and the arm it sits on, from the last Pose look: shoulder - elbow - wrist say which hand it is by themselves)
        pose_now = self._pose_raw[1] if self._pose_raw is not None and t0 - self._pose_raw[0] < .5 else None
        set_hand_label(detections[0].handedness if detections else "",
                       arm_label(pose_now, detections[0].landmarks, frame.shape[0] / max(1, frame.shape[1])) if detections else "")
        in_motion = bool(self.motion.active)       # gestures marked "motion mode only" count only now
        # 2026-11-11 report ("드래그 … 중간에 스크롤이나 다른 신호들의 간섭이 많아서 중간에 끊어지는 경우가 많다. 엄지검지가
        # 떨어지기 전에는 웬만하면 간섭들은 무시하고 드래그 상태가 유지"): a hand that drags is a hand with its other
        # fingers curled, moving - it reads as a fist (the page scroll took the drag over), as the thumb + index + middle
        # right click, as a taught pose, a hand shape of a sequence or a composite gesture, as the pointing hand. While
        # the thumb + index drag is on (the virtual hand's, src/virtual_hand.ShapePinch) none of those count: only the
        # fingers parting (or the hand lost) ends it.
        drag_on = bool(self._pinch_drag and self.shape_pinch.closed)
        sequences = self.seq_store.active(in_motion) if live and not drag_on else {}
        path_gestures = self.path_store.active(in_motion) if live and not drag_on else {}
        posture = None
        if detections and (self.pose_probe.active or sequences or path_gestures):
            # the hand shape from the landmarks alone, in every mode (index pointer, motion mode, a held sign, paused)
            posture = hand_posture(detections[0].landmarks, frame.shape[0] / max(1, frame.shape[1]))
        if self.pose_probe.active and detections:
            # [손 모양 보여주기]: it used to be fed only inside the palm controls, which a thumbs-up or motion mode skip
            lm0 = detections[0].landmarks
            k = frame.shape[0] / max(1, frame.shape[1])           # x and y in the same units
            palm = palm_centre(lm0)
            size = hand_px(lm0, 1.0, k)                          # steady when the hand turns (src/virtual_hand.hand_px)
            angles = (math.degrees(math.atan2(-(lm0[9].y - lm0[0].y) * k, lm0[9].x - lm0[0].x)),
                      math.degrees(math.atan2(-(lm0[4].y - lm0[0].y) * k, lm0[4].x - lm0[0].x)))
            self.pose_probe.log_dir = self.log_dir / "pose_probe"
            self.pose_probe.step(t0, posture, (palm[0], palm[1] * k), size, angles,
                                 [[round(p.x, 4), round(p.y, 4), round(getattr(p, "z", 0.0), 4)] for p in lm0],
                                 shot=hand_shot(frame, lm0))     # the picture shown with the result (memory only)
        if sequences:
            if detections:
                fired = self.sequences.step(t0, posture, sequences)
                if fired is not None:
                    self._run_sequence(fired)
            else:
                self.sequences.lost(t0)
        if path_gestures:
            # shape-drawing gestures: a hand shape held while the palm draws a shape (src/path_gesture.py)
            if detections:
                lm0 = detections[0].landmarks
                k = frame.shape[0] / max(1, frame.shape[1])
                pc = palm_centre(lm0)
                size = hand_px(lm0, 1.0, k)
                tip = 4 if posture == "thumbs_up" else 9          # a thumbs-up turns with its thumb
                angle = math.degrees(math.atan2(-(lm0[tip].y - lm0[0].y) * k, lm0[tip].x - lm0[0].x))
                fired = self.paths.step(t0, posture, (pc[0], pc[1] * k), size, path_gestures, self.draw_store, angle)
            else:
                fired = self.paths.step(t0, None, None, 0.0, path_gestures, self.draw_store)
            if fired is not None:
                self._run_gesture_key(fired, self.path_store.items.get(fired, {}).get("name", fired), "손 모양 그리기")
        if ui.hand_crop and detections:
            self.hand_crop.update(detections[0].landmarks, frame.shape[1], frame.shape[0], now=t0)
            if self.roi_tracker.enabled and not self.hand_crop.collapsed:
                self.roi_tracker.good(clean, hand_box(detections[0].landmarks, frame.shape[1], frame.shape[0]))
        elif ui.hand_crop:
            followed = self.roi_tracker.lost(frame, t0) if self.roi_tracker.enabled else None
            if followed is not None:
                self.hand_crop.follow(followed, frame.shape[1], frame.shape[0], t0)
            else:
                self.hand_crop.miss(t0)
        else:
            self.hand_crop.reset()
            self.roi_tracker.reset()
        palm_calibrating = self._palm_axes(t0, ui, detections)
        guided_recording = self._recording_mode(t0, ui, detections)
        self._virtual_hand = None
        self._preview_hand = self._finger = None
        if not detections:
            # A fast hand blurs and is lost for a few frames: keep the drawn hand where it was (faded) and its filters, so it glides
            # on from there instead of vanishing and popping up elsewhere. Only a longer loss lets go of everything.
            if self._vh_lost is None:
                self._vh_lost = t0
                if self._vh_last is not None:
                    self._vh_last = {**self._vh_last, "lost": True, "action": "", "guides": []}
            if t0 - self._vh_lost <= VH_LOST_KEEP and self._vh_last is not None:
                self._virtual_hand = self._vh_last
            else:
                self._vh_last = None
                self.box_mapper.reset()
                self.view_smoother.reset()
                self.hand_size.reset()
                self.ratchet.reset()
                self._vh_anchor = None
            self._vh_click, self._vh_engaged = None, False
            self.grip.reset()
            self.shape_pinch.reset()
            self.shape_right.reset()
            self.shape_switch.reset()
            self._pinch_since, self._pinch_drag, self._pinch_double = None, False, False
        else:
            self._vh_lost = None
        command_hold = self._online_recognize(t0, ui, detections, frame, guided_recording)
        self._track_arm(t0, frame, ui, detections)
        if engine.config.get("elbow_pivot", False) and detections and not ui.use_index_pointer:
            self.elbow.observe(t0, engine.palm_anchor_point(detections[0].landmarks), mouse.frame_aspect)
            if self.elbow.source == "arcs" and not self._elbow_announced:
                self._elbow_announced = True
                self._say("팔꿈치 위치를 찾았어요: 위아래·좌우를 팔꿈치 기준으로 펴서 움직여요", 3.0)
        else:
            self.elbow.observe(t0, None, mouse.frame_aspect)
        if getattr(self, "_vh_mode", None) is None:
            self._vh_respond(t0, False)       # how closely the drawn hand follows (virtual_hand.RESPONSE); the box branch decides per frame
        gate = self._gate_for(ui) if not ui.use_index_pointer and ui.stage == "main" else None
        if gate is not None:
            gate.step(t0, detections[0] if detections else None, frame.shape[0] / max(1, frame.shape[1]))
        self._use_frame(t0, detections, frame.shape[0] / max(1, frame.shape[1]), gate,
                        ui.stage == "main" and not guided_recording and self.test is None)
        self._rule_action = "none"
        self._engine_raw = None     # what the rule engine itself said this frame (guided capture overwrites result.action)
        toggle_hold = (not palm_calibrating) and self._toggle_sign(t0, ui, detections)
        motion_active = (not toggle_hold) and self._motion(t0, ui, detections)
        if motion_active and detections and not guided_recording:
            self._motion_composites(t0, detections[0])
        else:
            self.motion_composite_detector.reset()
        close_hold =(not motion_active) and (not toggle_hold) and self._close_sign(t0, ui, detections)
        if self._had_hand and not detections:
            mouse.close_switcher(confirm=False)
            mouse.release_all()
            engine.reset()
        self._had_hand = bool(detections)

        fh, fw = frame.shape[:2]
        mouse.frame_aspect = fh / max(1, fw)
        engine.frame_aspect = mouse.frame_aspect
        if self.frames % 10 == 0:
            small = cv2.resize(frame, (64, 36), interpolation=cv2.INTER_AREA)
            level = int(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).mean())
            try:
                dark_below = float(engine.config.get("low_light_threshold", 70))
            except (TypeError, ValueError):
                dark_below = 70.0
            mode = camera.actual_mode()
            self._metrics = (f"{mode[0]}×{mode[1]} · {mode[2]:g}fps" if mode else "", level, level < dark_below)

        index_mode = ui.use_index_pointer
        draw_active = (self.draw.active and not index_mode and not motion_active and not toggle_hold
                       and not palm_calibrating and ui.stage == "main" and not guided_recording)
        if draw_active:
            self._draw_step(t0, ui, detections, fw, fh)
        # pointing mode (src/point_mode.py): no entry step, the finger-gun hand itself is the mode (settings can switch it off)
        point_active = False
        self._point_view = None
        if (getattr(ui, "point_mode", True) and not index_mode and not motion_active and not draw_active and not toggle_hold
                and not close_hold and not palm_calibrating and not guided_recording and ui.stage == "main"
                and not self.paused and not ui.calibrating and not drag_on):
            self.point.configure(getattr(ui, "point_settings", None))
            self.point_probe.area_px = int(self.point.settings["area_px"])
            point_active = self.point.step(t0, detections[0].landmarks if detections else None, mouse.frame_aspect)
            if point_active:
                self._point_seen = t0
            if self.point.started:
                mouse.close_switcher(confirm=False)
                mouse.release_all()                        # a drag or a held click does not carry into pointing
                engine.reset()
                self.shape_pinch.reset()
                self._pinch_since, self._pinch_drag, self._pinch_double = None, False, False
                self._say("포인팅 모드: 검지 끝으로 가리키고 파일·폴더 위에서 1초 멈추면 "
                          + ("더블클릭" if self.point.kind == "double" else "우클릭"), 2.0)
        elif self.point.active:
            self.point.reset()
        if getattr(self, "_point_drag", False) and not point_active:
            self._point_drop()                 # the pointing hand was let go (or the control went off): drop what it held
        if getattr(self, "_point_was", False) and not point_active and getattr(ui, "virtual_hand", False):
            # pointing mode ended: the cursor is where the index tip took it, the box would put it at the palm. It
            # stays, and the difference is given back as the hand moves (no jump across the screen).
            m = mouse.absolute_monitor
            self.box_mapper.resume_at(((mouse.last_screen_pos[0] - m.left) / max(1, m.width - 1),
                                       (mouse.last_screen_pos[1] - m.top) / max(1, m.height - 1)), t0)
        self._point_was = point_active
        tracking_only = self.test is not None
        contacts: Tuple[int, ...] = ()
        tip_xy = None
        result = GestureResult()
        frame_out = None
        if index_mode and not motion_active:
            if detections:
                tip = detections[0].landmarks[GestureEngine.INDEX_TIP]
                tip_xy = (tip.x, tip.y)
            frame_out = pointer.step(
                t0, detections[0].landmarks if detections else None, mouse.frame_aspect,
                PointerSettings(click_style=ui.click_style, anchor=ui.anchor, tracking_only=tracking_only,
                                axes=ui.axes, config=engine.config),
                active=not self.paused and not ui.calibrating, detecting=should_detect,
            )
        else:
            pointer.reset()

        if frame_out is not None:
            points = detections[0].landmarks
            contacts = frame_out.contacts
            if frame_out.action is not None:
                action = frame_out.action
                if frame_out.warp is not None:
                    mouse.warp_to(*frame_out.warp)
                result = GestureResult(action=action, cursor_point=frame_out.cursor_point,
                                       is_moving=frame_out.cursor_point is not None)
                mouse.apply(result, engine.config, index_tip=frame_out.pointer_point,
                            index_sensitivity=ui.sensitivity / 100, pointer_source=frame_out.pointer_source)
                pointer.record_cursor(t0, mouse.last_screen_pos)
                parts = [f"이동 {frame_out.speed:.2f}" + (" 유지" if frame_out.latched else "")]
                if self._metrics and self._metrics[0]:
                    parts.insert(0, "카메라 " + self._metrics[0])
                if tracking_only or ui.click_style == "off":
                    parts.append("클릭 끔")
                elif ui.click_style == "trigger":
                    r = frame_out.trigger_ratio
                    parts.append(f"방아쇠 {r:.2f}" if math.isfinite(r) else "방아쇠 —")
                if not frame_out.click_armed:
                    parts.append("클릭 대기: 엄지를 떼세요")
                self._say("  ·  ".join(parts), .5)
                self._use_action(t0, action, "", source="pointer")
                if action in ("left_click", "right_click"):
                    self._recent_action, self._recent_until = action, time.perf_counter() + .5
            x, y = frame_out.preview_point
            if not ui.show_fingertips and 0 <= x <= 1 and 0 <= y <= 1:
                cv2.circle(frame, (int(x * fw), int(y * fh)), 6, (189, 229, 70), -1, cv2.LINE_AA)
            for number, landmark_id in enumerate(FINGERTIPS if ui.show_fingertips else ()):
                p = points[landmark_id]
                if not (0 <= p.x <= 1 and 0 <= p.y <= 1):
                    continue
                px, py = int(p.x * fw), int(p.y * fh)
                color = (189, 229, 70) if number == 1 or number in contacts else (245, 245, 245)
                cv2.circle(frame, (px, py), 10, (49, 35, 17), -1, cv2.LINE_AA)
                cv2.putText(frame, str(number), (px - 5, py + 5), cv2.FONT_HERSHEY_SIMPLEX, .46, color, 1, cv2.LINE_AA)
        elif detections and point_active:
            result = self._point_step(t0, detections[0], ui)
        elif detections and not index_mode and not motion_active and not draw_active and not close_hold and not toggle_hold \
                and not palm_calibrating:
            glab = None
            gtask = None
            if self._guided is not None:
                from src.gesture_catalog import BY_KEY
                glab = self._guided.label(t0)
                gtask = BY_KEY.get(glab.get("task"))
                gtok = (glab.get("task"), glab.get("set"), glab.get("rep"), glab.get("phase") == "do")
                if gtok != self._guided_rep_token:
                    self._guided_rep_token = gtok
                    engine._desktop_armed = True
                    engine._desktop_since = None
                    engine._last_trigger_times.clear()
                    engine._last_curled_at = -1e9
                    engine._last_halffist_at = -1e9
                    engine._index_released_at = -1e9
                    engine._scroll_released_at = -1e9
                    engine._pinky_fired_at = -1e9
                    engine._desktop_fired_at = -1e9
                    engine._side_released_at = -1e9
                    engine._side_armed = {"index": True, "ring": True, "pinky": True}
                    engine._click_fresh = {"middle": True, "ring": True, "pinky": True}
                    engine._secondary_since.clear()
                    engine._secondary_off.clear()
                    engine._index_pinched = False
                    engine._middle_hold_pinched = False
            hand = detections[0]
            result = engine.process(hand.landmarks)
            self._engine_raw = (result.action, result.active_gesture)   # before the guided capture below sets the target
            self._guided_obs_targets = None
            draw_pinched = engine.pinched_fingers
            if self._guided is not None and glab is not None:
                obs_targets = self._capture_rules.observe(t0, hand, result, glab)
                self._guided_obs_targets = obs_targets
                if gtask is not None and not gtask.free and gtask.label != "none":
                    if glab.get("phase") == "do" and gtask.key in obs_targets:
                        result.action = gtask.action or gtask.label
                        if gtask.label in ("thumb_index", "thumb_middle", "thumb_ring", "thumb_pinky", "thumb_index_middle"):
                            result.active_gesture = f"{gtask.label}_pinch"
                            draw_pinched = (
                                {"index", "middle"}
                                if gtask.label == "thumb_index_middle"
                                else {gtask.label.replace("thumb_", "")}
                            )
                        else:
                            result.active_gesture = gtask.label
                            draw_pinched = set()
                    else:
                        result.action = "none"
                        result.active_gesture = "none"
                        draw_pinched = set()
                elif glab.get("phase") in ("prep", "rest", "waiting", "paused"):
                    result.action = "none"
                    result.active_gesture = "none"
                    draw_pinched = set()
            rule_action = result.action
            if gate is not None and not guided_recording:
                result = gate.filter(t0, result)
                if gate.last_note:
                    self._say(gate.last_note, 1.2)
                    gate.last_note = ""
            self._rule_action = rule_action
            if command_hold:
                result.action, result.cursor_point, result.is_moving = "none", None, False
            screen_point = None       # box mode: where the palm (the drawn hand) is on the monitor
            cursor_point = None       # where the OS cursor goes: the palm, or the drawn pinch point while a click finger is in
            vh = None
            fist_released = False     # this frame a fist's hold on the page ended
            apply_cfg = engine.config
            if getattr(ui, "virtual_hand", False) and valid_box(ui.virtual_box) and not guided_recording:
                if result.action in VIRTUAL_OFF_ACTIONS:
                    result.action = "none"                # index / middle pinches are off here (the fist grabs)
                early = virtual_guides(pinch_guides(result.distances, engine.config, draw_pinched, action=result.action,
                                                    gesture=result.active_gesture))
                switching = bool(mouse.switcher_open)    # the task switcher: no page scroll, no drag; the box still places the cursor
                # (a dragging hand curls its other fingers: it is not a fist that grabs the page)
                fist_seen = result.active_gesture == "fist" and not command_hold and not switching and not drag_on
                fist_mode, fist_fire = self.holds.step("vh_fist", fist_seen, self._move_binding("vh_fist") if fist_seen else None,
                                                       t0, Grip.START)
                if fist_fire:
                    self._run_default_move("vh_fist")
                grip = self.grip.step("fist" if fist_seen and fist_mode == "native" else None, t0)
                fist_released, self._was_grip = (getattr(self, "_was_grip", None) == "scroll" and grip is None), grip
                check = self._click_check(engine.config)
                if check is not None:
                    check.step(t0, hand, frame.shape[0] / max(1, frame.shape[1]))
                pinch_evt = None
                if grip is None and (drag_on or not command_hold):
                    quick = self._last_tap is not None and t0 - self._last_tap[0] <= DOUBLE_TAP   # a second tap: no waiting
                    if drag_on:
                        self.shape_right.reset()           # the middle finger nearing the thumb is not a right click now
                        right_evt = None
                    else:
                        right_evt = self.shape_right.step(hand.landmarks, frame.shape[1], frame.shape[0])
                    if right_evt == "down" or (self.shape_right.closed and self.shape_pinch.closed):
                        self._pinch_triple = True          # the index got there first: that press is the right click now
                    if right_evt == "up":
                        self._triple_open_t = t0
                    # while the three are together, and a moment after (the middle leaving looks like a thumb + index pinch)
                    settling = self.shape_right.closed or t0 - self._triple_open_t < .3
                    pinch_evt = None if settling and not self.shape_pinch.closed else self.shape_pinch.step(
                        hand.landmarks, frame.shape[1], frame.shape[0], frames=1 if quick else None,
                        dragging=self._pinch_drag, now=t0)       # a drag lets go only when the fingers clearly part
                else:
                    self.shape_pinch.reset()
                    self.shape_right.reset()
                    right_evt = None
                    self._pinch_triple = False
                    self._pinch_since, self._pinch_drag, self._pinch_double = None, False, False
                # how fast the palm is travelling (frame widths a second, over the last 0.2 s)
                pc = palm_centre(hand.landmarks)
                self._palm_trail.append((t0, pc[0], pc[1] * frame.shape[0] / max(1, frame.shape[1])))
                self._palm_trail = [p for p in self._palm_trail if t0 - p[0] <= .2]
                first = self._palm_trail[0]
                palm_speed = (math.hypot(self._palm_trail[-1][1] - first[1], self._palm_trail[-1][2] - first[2]) / (t0 - first[0])
                              if len(self._palm_trail) >= 3 and t0 - first[0] > 1e-3 else 0.0)
                if pinch_evt == "down":
                    # 2026-11-11 ("가상손이 … 뚝뚝 끊기는 경우가 잦다"): the fingers meeting holds the cursor (the click's aim).
                    # Of 198 logged thumb + index pinches 31 closed while the palm was travelling at 0.15 frame widths a
                    # second or more (a hand on its way, its fingers brushing): each stopped the cursor for a quarter to
                    # half a second and 10 of them clicked. A pinch that closes on a travelling hand holds nothing and
                    # is no click; held on, it still becomes a drag.
                    limit = float(engine.config.get("virtual_pinch_moving_speed", .15))
                    self._pinch_moving = limit > 0 and palm_speed >= limit and not (
                        self._last_tap is not None and t0 - self._last_tap[0] <= DOUBLE_TAP)
                second = None          # a second tap soon after a click: the double click's second click, at the same point
                if pinch_evt == "down":
                    self._pinch_since, self._pinch_drag, self._pinch_rejected = t0, False, False
                    last = self._last_tap
                    if last is not None and t0 - last[0] <= DOUBLE_TAP:
                        second, self._pinch_since = last[1], None      # no drag and no click on opening from this press
                        self._pinch_double = True
                    self._last_tap = None
                self._click_kind = "double" if second is not None else ""   # which kind of left click this frame's would be
                was_drag = self._pinch_drag
                if (self.shape_pinch.closed and self._pinch_since is not None and t0 - self._pinch_since >= PINCH_HOLD
                        and not switching and not self._pinch_triple and not self.shape_right.closed
                        and self._checked(check, t0)):
                    # 2026-11-12 ("끌기 바꾸기 만들기"): the held pinch is a move of its own now ("vh_drag"). Left at its
                    # default it drags; switched off it does nothing; connected to another command that runs once
                    # when the hold begins. Either way the held press is no click when the fingers part.
                    held_mode = default_moves.plan("vh_drag", self._move_binding("vh_drag"))
                    if held_mode == "native":
                        self._pinch_drag = True            # held closed: it is a drag, not a click
                    elif not self._pinch_rejected:
                        self._pinch_rejected = True
                        if held_mode == "command":
                            self._run_default_move("vh_drag")
                dragging = self.shape_pinch.closed and self._pinch_drag
                tap = pinch_evt == "up" and not self._pinch_drag and not self._pinch_double and not self._pinch_triple \
                    and not self._pinch_rejected and not self._pinch_moving and self._checked(check, t0)
                drop = pinch_evt == "up" and self._pinch_drag     # the button comes up between the fingers, not at the palm
                press_t = self._pinch_since                    # when the fingers met (for the click log)
                if pinch_evt == "up" or (not self.shape_pinch.closed and not self.shape_right.closed):
                    self._pinch_since, self._pinch_drag, self._pinch_double = None, False, False
                    self._pinch_triple = False
                    self._pinch_rejected = False
                    self._pinch_moving = False
                if right_evt == "down":
                    # 2026-11-11 report ("그냥 움직이기만 해도 우클릭 간섭이 심하다"): the three fingertips come together
                    # in the picture while the hand only travels (the camera sees them along one line). This PC's click
                    # log: the 37 left clicks were made with the palm at 0.02 frame widths a second (median; 92 % under
                    # 0.1), the 16 right clicks at 0.14 - 8 of them at 0.1 or more, which no meant click reaches. As with
                    # the thumb + index pinch: fingers that meet on a travelling hand hold nothing and click nothing.
                    limit = float(engine.config.get("virtual_right_moving_speed", .1))
                    self._triple_moving = limit > 0 and palm_speed >= limit
                elif not self.shape_right.closed:
                    self._triple_moving = False
                triple_moving = getattr(self, "_triple_moving", False)
                # 2026-11-11 (the person, after marking 5 stray right clicks made with a still hand: "0.15초 유지 규칙
                # 넣어줘"): the three fingers must stay together for "virtual_right_hold" seconds (0 = at once) before
                # it is a right click. Fingers that only pass each other are none. Then the person marked an hour of use
                # with F8: 33 of 40 right clicks were not meant, all with a still hand, held 0.04-1.01 s (median 0.22);
                # no measure of the hand shape told them from the rest. 0.15 s would have stopped 9 of them, 0.6 s 28 -
                # the person chose 0.6 ("일단 1번으로 하자"): a right click is three fingers held for 0.6 s.
                if right_evt == "down":
                    self._triple_since, self._triple_fired = t0, False
                elif not self.shape_right.closed:
                    self._triple_since = None
                right_fire = (self.shape_right.closed and not triple_moving and not getattr(self, "_triple_fired", True)
                              and getattr(self, "_triple_since", None) is not None
                              and t0 - self._triple_since >= float(engine.config.get("virtual_right_hold", RIGHT_HOLD)))
                aiming = (self.shape_pinch.closed and not dragging and not self._pinch_moving) or tap                     or (self.shape_right.closed and not triple_moving)
                # fast while the hand only moves, smooth while it makes a command (setting "auto", virtual_hand.Responder)
                vh_mode = self._vh_respond(t0, bool(
                    grip is not None or command_hold or switching or dragging or self.shape_pinch.closed
                    or self.shape_right.closed or self.shape_switch.holding or self.composite_detector.commanding()))
                # (keep: only a grip that was meant leaves the cursor where it is when it ends; after a few stray fist
                # frames the cursor goes back to the hand, so the box and the monitor stay lined up)
                nx, ny = self.box_mapper.target(hand.landmarks, ui.virtual_box, now=t0, aim=grip is None,
                                                keep=grip == "scroll" and self.grip.solid,
                                                hold=(command_hold and not dragging) or grip == "scroll" or aiming
                                                or (grip is None and not dragging
                                                    and holds_still(early, result.action, result.active_gesture)))
                if (tap or second is not None) and result.action in PASSIVE_ACTIONS:
                    result.action = "left_click"          # thumb + index closed and opened again: click between them
                elif right_fire and result.action in PASSIVE_ACTIONS:
                    self._triple_fired = True
                    result.action = "right_click"         # thumb, index and middle together: right click there
                switch_now = grip is None and not command_hold and not self.shape_pinch.closed and not self.shape_right.closed                     and self.shape_switch.step(hand.landmarks, frame.shape[1], frame.shape[0], t0)
                if switch_now and result.action in PASSIVE_ACTIONS:
                    result.action = "task_switcher"       # opens it; the same shape again while it is open picks the highlighted one
                elif dragging:
                    result.action = "drag_hold"           # held closed: the button stays down until the fingers open
                log = self._click_log(engine.config)
                if log is not None and not self.paused:
                    log.frame(t0, hand)
                    kind = ("double" if second is not None and result.action == "left_click"
                            else "left" if tap and result.action == "left_click"
                            else "right" if right_fire and result.action == "right_click"
                            else "drag" if dragging and not was_drag else None)
                    if kind is not None:
                        pressed = press_t if kind in ("left", "drag") else t0
                        peak = check.peak(pressed, t0) if check is not None and check.ready and pressed is not None else None
                        log.click(kind, t0, pressed, peak)
                m = mouse.absolute_monitor
                screen_point = (int(round(m.left + nx * (m.width - 1))), int(round(m.top + ny * (m.height - 1))))
                if grip == "scroll":
                    # a fist holds the page: hand down = browse down (the pinch scroll goes the other way, like a touch screen)
                    if self.grip.started:
                        self.ratchet.reset()
                        self._fist_y = None
                    # sideways is easier than up and down: fist right = browse down, left = up (fed to the scroll as up/down)
                    cx, cy = palm_centre(hand.landmarks)
                    # 2026-11-11 report ("스크롤하다가 손을 펴면 … 의도하지 않은 추가 스크롤"): the grip outlasts the fist by
                    # Grip.GRACE (a flickering fist must not drop the page), and for those 0.4 s the opening hand kept
                    # scrolling - 19 logged releases: 12-14 frames each, the palm moving up to 8 % of the frame. The page
                    # now follows the hand only while it IS a fist; with the fist gone it stands where it was (so the
                    # release also has no speed to coast on).
                    if result.active_gesture == "fist" or self._fist_y is None:
                        self._fist_y = self.ratchet.step(cx, t0)
                    result.action, result.cursor_point = "scroll_grab", (0.5, self._fist_y)
                    flip = not engine.config.get("virtual_fist_scroll_follows_page", False)
                    apply_cfg = {**engine.config, "scroll_invert": bool(engine.config.get("scroll_invert", False)) != flip,
                                 "scroll_gain": float(engine.config.get("scroll_gain", 36000.0))
                                 * float(engine.config.get("virtual_fist_scroll_speed", .5))}
                else:
                    self.ratchet.reset()
                vh = virtual_hand_view(hand.landmarks, frame.shape[1], frame.shape[0], early, result.action,
                                      size=self.hand_size(hand.landmarks, frame.shape[1], frame.shape[0], t0))
                if vh is not None:
                    vh["pts"] = self.view_smoother(vh["pts"], t0)
                    vh["glide"] = vh_response(vh_mode)["glide"]   # the window's glide between camera frames follows the mode too
                    vh["grip"] = grip is not None          # a fist holds the page: the drawn hand turns amber (manux)
                    if grip is not None:
                        vh["click"] = None
                    elif self.shape_pinch.closed or tap or drop:
                        vh["click"] = pinch_point(vh["pts"], "index")
                    elif self.shape_right.closed:
                        vh["click"] = triple_point(vh["pts"])
                    else:
                        vh["click"] = click_offset(vh["pts"], early, result.action)
                engaged = (self.box_mapper.held or dragging or drop or self.shape_pinch.closed or self.shape_right.closed
                           or tap or result.action in ("left_click", "right_click", "drag_hold"))
                # The cursor IS the clicking point: no jump to the pinch point when the fingers meet (manux measured 18.5
                # jumps >= 60 px a minute from that offset). The drawing is shifted instead, so that its thumb-index point
                # (`anchor`, followed slowly, frozen while clicking or gripping) sits on the cursor.
                if vh is not None:
                    aim_px = pinch_point(vh["pts"], "index")
                    if self._vh_anchor is None:
                        self._vh_anchor = list(aim_px)
                    elif not engaged and grip is None:
                        self._vh_anchor = [a + VH_ANCHOR_FOLLOW * (b - a) for a, b in zip(self._vh_anchor, aim_px)]
                self._vh_click = None
                cursor_point, jump = screen_point, False
                if second is not None:
                    cursor_point, jump = second, True      # exactly the first click's pixel: Windows pairs them as a double click
                if tap and result.action == "left_click":
                    self._last_tap = (t0, cursor_point)
                self._vh_engaged = engaged
                result.is_moving = False      # the box places the cursor below, not the relative movement
                if switching:
                    apply_cfg = {**apply_cfg, "switcher_external_cursor": True}
            if not self.paused and not guided_recording:      # guided recording: rules judge, the mouse stays still
                self._use_enforce(t0, result, screen_point is not None)
                if cursor_point is not None:
                    # the hand does the clicking: the cursor goes to the pinch point first (at once when the fingers meet)
                    if cursor_point != tuple(mouse.last_screen_pos):
                        mouse._move_os_cursor(*cursor_point, immediate=jump)
                    if result.action == "drag_hold" and not mouse._hold_dragging:
                        mouse._hold_dragging = True
                        mouse._mouse_down()
                comp_hit = self.composite_detector.step(
                    t0, hand.landmarks, result.active_gesture, draw_pinched, mouse.frame_aspect, scope="normal"
                )
                if comp_hit is not None and screen_point is not None and result.action == "drag_hold":
                    comp_hit = None                        # a drag is on: its hand shape is not a composite gesture
                if comp_hit is not None and t0 - self._point_seen < POINT_QUIET and str(
                        (get_action_registry().composite_gestures.get(comp_hit["key"]) or {}).get("base_posture")) in POINT_LIKE:
                    # the pointing hand (thumb up + index out) is one thumb away from "index only" / "ㄴ자": a hold of
                    # those shapes right after pointing mode is the same hand relaxing, not a command (as with the V sign)
                    comp_hit = None
                if comp_hit is not None:
                    self._log_composite_fire(comp_hit)
                    reg = get_action_registry()
                    fg = mouse.foreground_info() if not mouse.dry_run else {}
                    resolved = reg.resolve_effective_action(comp_hit["key"], fg)
                    self._use_names[comp_hit["key"]] = str(comp_hit.get("name") or comp_hit["key"])
                    ok, badge = self._run_resolved(reg, resolved)
                    if ok:
                        self._say(f"복합 동작 [{comp_hit['name']}] → {badge}", 1.5)
                        self._recent_action, self._recent_until = comp_hit["key"], time.perf_counter() + 0.8
                        result.action = "none"
                elif result.action in ("left_click", "right_click", "show_desktop", "task_switcher"):
                    # the hand on the screen clicks with its own hand shapes: its own bindings, not palm mode's
                    action_to_key = VIRTUAL_ACTION_KEYS if screen_point is not None else PALM_ACTION_KEYS
                    gkey = action_to_key.get(result.action, PALM_ACTION_KEYS[result.action])
                    reg = get_action_registry()
                    fg = mouse.foreground_info() if not mouse.dry_run else {}
                    resolved = reg.resolve_effective_action(gkey, fg)
                    default_b = DEFAULT_GESTURE_BINDINGS.get(gkey, {})
                    if (
                        bool(resolved.get("matched_app"))
                        or resolved.get("action_type") != default_b.get("action_type")
                        or resolved.get("action_value") != default_b.get("action_value")
                        or not reg.get_binding(gkey).get("enabled", True)
                    ):
                        ok, badge = self._run_resolved(reg, resolved)
                        if ok:
                            self._say(f"매핑 실행: {badge}", 1.2)
                        self._recent_action, self._recent_until = result.action, time.perf_counter() + 0.8
                        result.action = "none"
                if screen_point is None:
                    self._palm_held(t0, result)      # palm mode's grab scroll / drags connected to another command
                mouse.apply(result, apply_cfg)
                if fist_released:
                    mouse._stop_scroll_inertia()           # a fist that let go leaves the page where it is: no coasting on
                self._use_action(t0, result.action, result.active_gesture, virtual=screen_point is not None)
                if result.action in ONE_SHOT:
                    self._recent_action, self._recent_until = result.action, time.perf_counter() + .8
            guides = pinch_guides(result.distances, engine.config, draw_pinched,
                                  action=result.action, gesture=result.active_gesture)
            anchor = engine.palm_anchor_point(hand.landmarks)
            if self.qml_skeleton:
                # the skeleton is drawn by QML over the preview (src/HandSkeleton.qml, from manux-merged-20261110)
                self._preview_hand = preview_hand(hand.landmarks, guides, anchor, result.is_moving)
            else:
                HandTracker.draw_hand(frame, hand.landmarks, guides)
            self._finger = overlay_frame(hand.landmarks, camera.config.mirror, result.action, result.is_moving)
            label = self._recent_action if time.perf_counter() < self._recent_until else result.action
            if vh is None:
                vh = virtual_hand_view(hand.landmarks, frame.shape[1], frame.shape[0], guides, label,
                                      size=self.hand_size(hand.landmarks, frame.shape[1], frame.shape[0], t0))
                if vh is not None:
                    vh["pts"] = self.view_smoother(vh["pts"], t0)
            if vh is not None:
                if screen_point is not None:
                    guides = virtual_guides(guides)         # only the pinches that work here are drawn on the screen hand
                vh["guides"] = [[f, s] for f, s in guides]
                vh["action"] = HAND_ACTION_NAMES.get(label, "")
                vh["text"] = bool(getattr(ui, "signal_text", True))
                if self.paused:
                    vh["note"] = self._inspect_note(t0, hand, result, draw_pinched)
                if screen_point is not None and self._vh_anchor is not None:
                    vh["anchor"] = [round(v, 1) for v in self._vh_anchor]   # drawn on the cursor (the window centre)
                    vh["click"] = list(vh["anchor"])
                    vh["aim"] = not self._vh_engaged
                elif self._vh_click:
                    vh["click"] = list(self._vh_click)
                else:
                    vh["click"] = click_offset(vh["pts"], guides, label)
                if screen_point is not None:
                    vh["screen"] = list(screen_point)       # where it is drawn (the palm), also while paused
                    vh["switcher"] = bool(mouse.switcher_open)   # the window goes back above the task switcher
            self._virtual_hand = vh
            self._vh_last = vh
            if self._draw_cursor_anchor and not self.qml_skeleton:
                self._draw_cursor_anchor(frame, hand.landmarks, anchor, result.is_moving)
            self._draw_arm(frame, t0)
            if engine.config.get("elbow_pivot", False):
                self._draw_elbow(frame, engine.palm_anchor_point(hand.landmarks), mouse.frame_aspect)
            if self._draw_recording:
                self._draw_recording(frame, mouse.recorded_path)
            if mouse.fling_count != self._last_fling:
                self._last_fling = mouse.fling_count
                self._say(f"FLING! ~{mouse.last_fling_distance:.0f}px", .8)
        elif not index_mode:
            result = engine.process(None)

        if detections and not index_mode and self._virtual_hand is None and self._vh_last is not None:
            # A hand is seen but the controls are off for it (a V or close sign held, motion or draw mode, palm calibration):
            # the window used to be hidden for those frames (2026-11-11: "the virtual hand keeps vanishing"). Draw the
            # hand as it is now, faded, where it was.
            lm = detections[0].landmarks
            fw, fh = frame.shape[1], frame.shape[0]
            vh = virtual_hand_view(lm, fw, fh, (), "none", size=self.hand_size(lm, fw, fh, t0))
            if vh is not None:
                vh["pts"] = self.view_smoother(vh["pts"], t0)
                for key in ("screen", "anchor", "switcher"):
                    if key in self._vh_last:
                        vh[key] = self._vh_last[key]
                vh["lost"] = True
                if point_active:
                    # 2026-11-11 report ("포인팅 모드가 한번 되더니 그 이후로 안된다", a picture of the drawn index tip on a
                    # file's name and an empty ring beside it): in pointing mode the cursor follows the index tip, but
                    # the hand was drawn with its thumb-index point on the cursor (the anchor left from before the
                    # mode) - the drawn fingertip was half a hand away from the cursor, so a file "pointed at" in the
                    # picture was outside the cursor's reach. While pointing, the drawn INDEX TIP is on the cursor.
                    vh["anchor"] = [vh["pts"][2 * GestureEngine.INDEX_TIP], vh["pts"][2 * GestureEngine.INDEX_TIP + 1]]
                    vh["click"] = list(vh["anchor"])
                    vh["lost"] = False                     # the hand is doing something: drawn fully, not faded
                self._virtual_hand = self._vh_last = vh

        if roi is not None:
            cv2.rectangle(frame, roi[:2], roi[2:], (189, 229, 70), 2, cv2.LINE_AA)
        self._failures(t0, detections, roi, index_mode, ui, frame, result, frame_out)
        self._record_frame(t0, detections, result, clean)
        if ui.stage == "main" and not guided_recording and self.test is None:
            self._online_frame(t0, detections, frame)
        self._last_step_t = t0
        tracking = self._tracking(t0, detections, index_mode, ui)

        now = time.perf_counter()
        status = self._status if now <= self._status_until else ""
        if now < self._recent_until:
            action = self._recent_action
        elif result.action and result.action != "none":
            action = result.action
        elif self.mouse.switcher_open:
            action = "task_switcher"
        elif result.active_gesture in (
            "thumb_pinky_pinch",
            "thumb_ring_pinch",
            "thumb_middle_pinch",
            "thumb_index_pinch",
            "thumb_index_middle_pinch",
        ):
            action = str(engine._gesture_cfg(result.active_gesture).get("action", "move_cursor"))
        elif detections and not index_mode:
            action = "move_cursor"
        else:
            action = result.action
        self.frames += 1
        snap = Snapshot(
            seq=self.frames, frame=frame, detected=bool(detections), paused=self.paused, action=action,
            fps=camera.fps, detect_ms=tracker.last_detect_ms, status=status, contacts=contacts,
            tip=tip_xy, aspect=mouse.frame_aspect, source=camera.config.source,
            mirrored=camera.config.mirror, detections=all_detections if ui.stage == "capture" else [],
            metrics=self._metrics, tracking=tracking, failures=self._pending_failures,
            recent_line=self._pending_recent, message=self._pending_message,
            motion=(self.motion.active, self.motion.remaining(t0), self._motion_last, self.motion.entering(t0),
                    self.motion.leaving(t0)),
            toggle_progress=self.toggle_sign.progress(t0),
            close_sign=(self.close_sign.progress(t0), self.close_sign.pending(t0),
                        self._close_notice if time.perf_counter() < self._close_notice_until else ""),
            palm_axes=self._palm_view(t0),
            rec=self._rec_view(t0),
            gate_status=self.gate.status_summary() if (self.gate is not None and ui.tcn_gate) else None,
            registration=self._registration_view,
            online_gesture=self._online_gesture if t0 < self._online_gesture_until else "",
            virtual_hand=self._virtual_hand,
            preview_hand=self._preview_hand,
            pose_probe=self._pose_probe_view(t0),
            pose_probe_shot=((self.pose_probe.shot_seq, self.pose_probe.shot, self.pose_probe.clip)
                             if self.pose_probe.shot_seq else None),
            draw=self.draw.view(t0) if self.draw.active or self.draw.last is not None else None,
            finger=self._finger,
            point=self._point_view,
            admin_blocked=self._admin_window_in_front(t0),
            # (+ True when only the uses the person passed may be learned: src/use_review.py)
            learn_request=(self._learn_request, str(self.log_dir / "use_events"),
                           *([True] if self.engine.config.get("use_review_required", True) else [])),
            learn_note=self._learn_note,
            learn_advice=getattr(self, "_learn_advice", ""),
            base_request=getattr(self, "_base_request", 0),
            onnx_request=getattr(self, "_onnx_request", 0),
            learn_items=list(self._learn_items),
            hand_lost=(t0 - self._hand_seen_t) > float(self.engine.config.get("hand_lost_alert", 0.35)),
            arm_lost=bool(self.pose is not None and not ui.use_index_pointer
                          and (self._arm is None or t0 - self._arm_t > float(self.engine.config.get("arm_lost_alert", 0.8)))),
        )
        self._pending_failures = self._pending_recent = None
        self._pending_message = ""
        with self._cond:
            self._snap = snap
            self._cond.notify_all()
        if self.perf_log is not None:
            if ui.stage == "main":
                lms = detections[0].landmarks if detections else None
                self.perf_log.hand(
                    found=bool(detections), raw=bool(all_detections), followed=self._hand_follower.followed,
                    size=max(math.hypot(lms[k].x - lms[0].x, (lms[k].y - lms[0].y) * frame.shape[0] / frame.shape[1])
                             for k in (5, 9, 13, 17)) if lms else None)
            self.perf_log.frame(tracker.last_detect_ms if should_detect else None, (time.perf_counter() - t0) * 1000.0)
            self.perf_log.tick(camera.fps, camera.dropped_frames)

    def _online_frame(self, t0: float, detections, frame) -> None:
        """Everyday-use collection. A failure here switches collection off, it never stops the mouse."""
        if self._online_failed or not self.engine.config.get("online_learning_enabled", False):
            return
        try:
            if self.online is None:
                config = self.engine.config
                self.online = OnlineCollector(
                    SampleStore(self._online_root or ONLINE_DEFAULT_ROOT), pc=machine_info(str(config.get("pc_alias", "")))["pc"],
                    camera=str(config.get("camera_note", "")), aspect=frame.shape[0] / max(1, frame.shape[1]),
                    handedness=str(self.ui.control_hand))
                self._online_reload()
            hand = detections[0] if detections else None
            lm = world = None
            if hand is not None and getattr(hand, "world", None):
                lm, world = [(p.x, p.y, p.z) for p in hand.landmarks], hand.world
            if self.registration is not None and self.registration.active:
                self.registration.update(t0, lm, world)     # demonstrations are saved on approval, not as everyday use
                self._registration_view = self.registration.view()
                return
            self.online.frame(t0, hand, getattr(self, "_rule_action", None) if hand is not None else None)
        except Exception as exc:
            self._online_failed = True
            self.registration = None
            self._say(f"학습 데이터 수집을 껐어요: {exc}", 5.0)

    def _online_recognize(self, t0: float, ui, detections, frame, guided_recording: bool) -> bool:
        """Registered gestures, before the rules act on this frame. True = one is being made: the hand is giving a command, so the
        cursor stays where it is and no click is judged (otherwise the command lands somewhere else)."""
        if self._online_failed or not self.engine.config.get("online_learning_enabled", False):
            return False
        if ui.stage != "main" or guided_recording or self.test is not None or (self.registration is not None and self.registration.active):
            return False
        try:
            if self.recognizer is None:
                if not self._online_load():
                    return False
                self.recognizer = PoseRecognizer(self.online_memory, frame.shape[0] / max(1, frame.shape[1]))
            hand = detections[0] if detections else None
            lm = world = None
            if hand is not None and getattr(hand, "world", None):
                lm, world = [(p.x, p.y, p.z) for p in hand.landmarks], hand.world
            fired = self.recognizer.step(t0, lm, world, USER_SOURCE)
            if fired:
                self._online_gesture, self._online_gesture_until = fired, t0 + 1.0
            elif self.recognizer.current:
                self._online_gesture_until = max(self._online_gesture_until, t0 + .3)
            due = self.command_gate.step(t0, self.recognizer.current, allowed=not self.paused)
            if due:
                self._run_command(due, t0)
            if self.recognizer.candidate:
                self._freeze_until = t0 + FREEZE_SECONDS
            return t0 < self._freeze_until
        except Exception as exc:
            self._online_failed = True
            self._say(f"새 동작 인식을 껐어요: {exc}", 5.0)
            return False

    def _run_command(self, label: str, t0: float) -> None:
        """The command the person chose for a registered gesture. Nothing happens for a gesture without one."""
        value = command_of(label)
        if not value:
            return
        if foreground_window_title().startswith("Hand-Mouse"):
            # the keys would land in this app itself, where a letter can be a shortcut (Q quits)
            self._online_gesture, self._online_gesture_until = f"{label}: 앱 창에는 명령을 보내지 않아요", t0 + 1.5
            return
        if not self._use_allows(label, t0):
            return
        registry = get_action_registry()
        resolved = registry.resolve_effective_action(binding_key(label), self.mouse.foreground_info() if not self.mouse.dry_run else {})
        ok, badge = registry.execute_resolved_action(resolved, dry_run=self.mouse.dry_run, mouse_controller=self.mouse)
        if ok:
            self._use_event("registered", label, t0)
        self._online_gesture =f"{label} → {command_text(value)}" if ok else f"{label}: {badge}"
        self._online_gesture_until = t0 + 1.5
        self._say(f"새 동작 실행: {label} → {badge}", 1.5)

    def _gesture_delete(self, label: str) -> None:
        if not self._online_load() or self.online_memory.classes.get(label) is None or self.online_memory.classes[label].source != USER_SOURCE:
            return
        self.online_memory.remove_class(label)
        root = self._online_root or ONLINE_DEFAULT_ROOT
        self.online_memory.save(root / POSE_FILE)
        store = SampleStore(root)
        store.delete([s.sample_id for s in store.samples(label=label)])
        forget_command(label)
        if self.recognizer is not None:
            self.recognizer.reset()
        self.command_gate.reset()

    def _online_load(self) -> bool:
        """The poses of the known classes and the registered gestures (scripts/online_build_pose.py)."""
        if self.online_memory is not None:
            return True
        path = (self._online_root or ONLINE_DEFAULT_ROOT) / POSE_FILE
        if getattr(self, "_online_load_failed", False) or not path.is_file():
            return False
        try:
            self.online_memory = PoseMemory.load(path)
        except Exception as exc:
            self._online_load_failed = True
            self._say(f"새 동작 기능을 켜지 못했어요: {exc}", 5.0)
            return False
        return True

    def _register_start(self, name: str, now: float) -> None:
        if not self.engine.config.get("online_learning_enabled", False) or not self._online_load():
            self._registration_view = {"state": "failed", "message": "새 동작 기능이 꺼져 있거나 준비되지 않았어요"}
            return
        self._pause()
        try:
            config = self.engine.config
            aspect = self.mouse.frame_aspect
            self.registration = RegistrationSession(
                name, memory=self.online_memory, embed=lambda frames: pose_features(frames, aspect),
                store=SampleStore(self._online_root or ONLINE_DEFAULT_ROOT), config=self.registration_config,
                meta={"pc": machine_info(str(config.get("pc_alias", "")))["pc"], "camera": str(config.get("camera_note", "")),
                      "aspect": aspect, "handedness": str(self.ui.control_hand)})
            self._registration_view = self.registration.view()
        except RegistrationError as exc:
            self.registration = None
            self._registration_view = {"state": "failed", "message": str(exc)}

    def _register_approve(self) -> None:
        if self.registration is None:
            return
        try:
            self.registration.approve((self._online_root or ONLINE_DEFAULT_ROOT) / POSE_FILE)
            self._registration_view = self.registration.view()
            if self.recognizer is not None:
                self.recognizer.reset()
        except (RegistrationError, OSError, ValueError) as exc:
            self._registration_view = {"state": "failed", "message": str(exc)}
        self.registration = None

    def _register_cancel(self) -> None:
        if self.registration is not None:
            self.registration.cancel()
        self.registration, self._registration_view = None, None

    def _online_reload(self) -> None:
        """A new production model (or a rollback): the guesses come from it from now on. Without torch or a model: the rule engine's."""
        self._online_model_version += 1          # the gate reloads too, and holds actions for a moment (OnlineGate)
        self._watchers.pop("online", None)       # the watching copy too; what the old file had earned is decided again
        self._watch_loading.discard("online")
        if self.use_log is not None:
            self._use_decide(recount=True)
        if self.online is None:
            return
        try:
            from src.online.app_job import ProductionPredictor
            from src.online.versions import ModelManager
            root = self._online_root or ONLINE_DEFAULT_ROOT
            self.online.guess = ProductionPredictor(root).guess if ModelManager(root).has("production") else None
        except Exception:
            self.online.guess = None

    def take_correction(self):
        """A saved "last moments" sample waiting for the person's answer, or None. UI thread."""
        return self.online.take_manual() if self.online is not None else None

    def _point_step(self, t0: float, hand, ui) -> GestureResult:
        """One frame of pointing mode: the index tip moves the cursor; resting on a file / folder for PointMode.DWELL
        double-clicks (thumb + index) or right-clicks (thumb + index and middle together) it."""
        mouse = self.mouse
        # 2026-11-11 report ("이 자세에서 중지를 폈다 접었다 하면 가상손이 크게 튄다"): with the right-click shape the cursor
        # followed the point between the index and middle tips. While the middle finger folds or comes out that point
        # travels half the finger's way (the shape stays "right" for a few frames, and loosely once the mode is on) and
        # the cursor went with it: 78 px a frame in a replay of the pose. The cursor follows the index tip in both
        # shapes; the middle finger only says which click it is. (With the fingers together the two points are half a
        # finger's width apart, and the click goes to the file around the tip anyway.)
        tip = hand.landmarks[GestureEngine.INDEX_TIP]
        point_drag = bool(getattr(self, "_point_drag", False))     # holding a file taken by a pointing dwell (see below)
        result = GestureResult(action="drag_hold" if point_drag else "move_cursor", active_gesture="point",
                               cursor_point=(tip.x, tip.y), is_moving=True)
        mouse.apply(result, self.engine.config, index_tip=(tip.x, tip.y),
                    index_sensitivity=ui.sensitivity / 100 * float(self.point.settings.get("speed", 1.0)),
                    pointer_source="index")
        cur = (float(mouse.last_screen_pos[0]), float(mouse.last_screen_pos[1]))
        self.point_probe.ask(*cur)
        # the file / folder at or around the fingertip (2026-11-11: the wait is on the item, the tip may tremble)
        item = self.point_probe.target(*cur)
        on_file = True if item is not None else self.point_probe.answer(*cur)
        fire = "" if point_drag else self.point.dwell(t0, cur, on_file, item=item)   # while it drags nothing else is clicked
        centre = None
        if item is not None:
            left, top, right, bottom = item[1]
            centre = (int((left + right) / 2), int((top + bottom) / 2))
        if fire:
            if centre is not None and not mouse.dry_run:
                mouse._move_os_cursor(*centre, immediate=True)     # the click lands on the item, not where the tip shook to
            key = "point_double" if fire == "double" else "point_right"
            mode = default_moves.plan(key, self._move_binding(key))
            if mode == "native":
                mouse.point_click(fire)
                done = "double_click" if fire == "double" else "right_click"
                self._recent_action, self._recent_until = done, time.perf_counter() + .8
                self._say(("더블클릭" if fire == "double" else "우클릭") + (f": {self.point_probe.name}" if self.point_probe.name else ""), 1.2)
                self._use_action(t0, done, "point", source="point")
            elif mode == "command":
                self._run_default_move(key)          # connected to another command in the training center
            elif mode == "drag":
                # connected to the drag (2026-11-12): the button goes down on the file; it follows the fingertip
                # until the pointing hand is let go (see _point_drop, called when the mode ends)
                self._point_drag = True
                mouse._hold_dragging = True
                mouse._mouse_down()
                self._recent_action, self._recent_until = "drag_hold", time.perf_counter() + .8
                self._say("끌기 시작" + (f": {self.point_probe.name}" if self.point_probe.name else "")
                          + " · 손 모양을 풀면 놓아요", 2.0)
                self._use_action(t0, "drag_hold", "point", source="point")
        if self._vh_last is not None:
            self._vh_last = {**self._vh_last, "screen": [int(cur[0]), int(cur[1])]}   # the faded hand follows the cursor
        self._preview_hand = preview_hand(hand.landmarks, (), None, True)
        # why the ring is (not) filling, in words on the label and in logs/point_trace.jsonl (2026-11-11: the person held
        # the fingertip on a file and nothing happened, and nothing on the screen or in the logs said why)
        state = self.point_probe.state(*cur) if hasattr(self.point_probe, "state") else ("file" if on_file else "none")
        spent = item is not None and item == getattr(self.point, "_spent_item", None)
        why = ("끄는 중 · 손 모양을 풀면 놓아요" if getattr(self, "_point_drag", False)
               else "파일 확인을 쓸 수 없어요" if state == "off" else "방금 누른 파일 · 다른 곳을 가리켰다 오세요" if spent
               else str(item[0]) if item is not None else "파일 확인 중…" if state == "asking"
               else "파일·폴더 위가 아니에요" if state == "none" else "")
        self._point_view = {"kind": self.point.kind, "progress": round(self.point.progress, 3),
                            "on_file": bool(on_file), "screen": list(centre) if centre is not None else [int(cur[0]), int(cur[1])],
                            "name": item[0] if item is not None else "", "why": why}   # the ring sits on the item being waited on
        self._point_trace(t0, cur, state, item, on_file, spent, fire)
        return result

    def _point_drop(self) -> None:
        """End of a drag started by a pointing dwell: the button comes up where the cursor is."""
        self._point_drag = False
        self.mouse._mouse_up()
        self.mouse._hold_dragging = False
        self._say("놓았어요", 1.2)

    def _point_trace(self, t0: float, cur, state: str, item, on_file, spent: bool, fire: str) -> None:
        """Five lines a second while pointing (and every click) into logs/point_trace.jsonl: where the cursor is, what the
        file check answered and what Windows said was there, how full the wait is. Kept to the last ~2000 lines."""
        if not fire and t0 - getattr(self, "_point_trace_t", -1e9) < .2:
            return
        self._point_trace_t = t0
        probe = self.point_probe
        rec = {"wall": time.strftime("%H:%M:%S"), "t": round(t0, 2), "cursor": [int(cur[0]), int(cur[1])],
               "kind": self.point.kind, "state": state, "item": list(item) if item is not None else None,
               "on_file": on_file, "spent": spent, "progress": round(self.point.progress, 2), "fire": fire or "",
               "seen": str(getattr(probe, "seen", "")), "error": str(getattr(probe, "error", "")),
               "asked": int(getattr(probe, "asked", 0)), "answered": int(getattr(probe, "answered", 0)),
               "area_px": int(getattr(probe, "area_px", 0))}
        try:
            path = self.log_dir / "point_trace.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_file() and path.stat().st_size > 600_000:
                lines = path.read_text(encoding="utf-8").splitlines()[-1000:]
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _motion_blocked(self, t0: float) -> bool:
        """A pinch, scroll or drag is going on or has just ended: the entry pose does not count then."""
        quiet = float(self.motion.cfg("motion_enter_quiet"))
        for g in (self.engine, self.pointer.gestures):
            last = max(g._index_released_at, g._scroll_released_at, g._pinky_fired_at,
                       max(g._last_trigger_times.values(), default=-1e9))
            if g._index_pinched or g._secondary_since or (t0 - last) < quiet:
                return True
        return bool(self.mouse.is_dragging or self.mouse.scroll_coasting)

    def _toggle_sign(self, t0: float, ui, detections) -> bool:
        """The V sign held still switches the mouse control on / off (like the Space key). It keeps watching while the control is
        off. True while the sign is held with the control ON (the cursor and pinches are suspended, so the fingers do not move it)."""
        ready = ui.stage == "main" and not ui.calibrating and not ui.use_index_pointer and self.test is None and self._guided is None
        if not ready or not detections:
            if self.toggle_sign.progress(t0) > 0 or self.toggle_sign.last_pose:
                self.toggle_sign.update(t0, None)
            return False
        blocked = False
        if not self.paused:
            quiet = self.toggle_sign.cfg("toggle_sign_quiet")
            for g in (self.engine, self.pointer.gestures):
                last = max(g._index_released_at, g._scroll_released_at, g._pinky_fired_at,
                           max(g._last_trigger_times.values(), default=-1e9))
                if g._index_pinched or g._secondary_since or (t0 - last) < quiet:
                    blocked = True
            blocked = blocked or bool(self.mouse.is_dragging or self.mouse.scroll_coasting)
            # 2026-11-11 report ("포인팅 모드 더블클릭 되는 순간 비활성화 … V 동작 간섭"): the pointing hand is one finger away
            # from a V - the middle finger comes out for the right-click shape, or as the hand relaxes after the click -
            # and 0.6 s of that switched the control off (logs/failures 135722, 140004: the pointing shape, then a V).
            # While pointing mode is on, and for POINT_QUIET after it, the V sign does not count.
            if getattr(ui, "point_mode", True) and point_shape(detections[0].landmarks, self.mouse.frame_aspect, self.point.tilt, self.point.right):
                self._point_seen = t0              # (the shape itself, also before the mode has started or after it ended)
            blocked = blocked or self.point.active or (t0 - self._point_seen) < POINT_QUIET
        self.toggle_sign.aspect = self.mouse.frame_aspect
        was_holding = self.toggle_sign.holding(t0)
        v_model_ok = bool(
            self.gate is not None
            and self.ui.tcn_gate
            and "v_sign" in getattr(self.gate, "classes", ())
            and self.gate.allows("v_sign", t0)
        )
        event = self.toggle_sign.update(
            t0,
            detections[0].landmarks,
            blocked=blocked,
            model_confirmed=v_model_ok,
        )
        custom = self._sign_override("v_sign") if event is not None and not self.paused else None
        if custom is not None:
            # 2026-11-10: the V sign's binding was changed (e.g. by the AI helper) but this detector always toggled the
            # control, so the new command never ran. Now it runs the binding; while the control is OFF the V sign
            # still turns it on (else no hand gesture could switch the control back on).
            self.mouse.release_all()
            self.engine.reset()
            self.pointer.reset()
            if custom != "off":
                ok, badge = self._run_resolved(get_action_registry(), custom)
                self._close_notice, self._close_notice_until = f"V 손 모양 → {badge}", time.perf_counter() + 2.0
        elif event is not None:
            self.mouse.release_all()
            self.engine.reset()
            self.pointer.reset()
            self._key(ord(" "), t0)                         # same as the Space key: toggles the control
            text = "마우스 제어 꺼짐 (V 손 모양)" if self.paused else "마우스 제어 켜짐 (V 손 모양)"
            self._close_notice, self._close_notice_until = text, time.perf_counter() + 2.5
            self.failures.trigger(t0, "toggle_sign", note=text)
        holding = self.toggle_sign.holding(t0) and not self.paused
        if holding and not was_holding:
            self.mouse.release_all()
            self.engine.reset()
            self.pointer.reset()
        return holding

    def _close_result(self, t0: float) -> None:
        """What became of the last close request (mouse.close_outcome, set about a second after it was sent, from the
        rock sign or any gesture bound to Alt+F4). A window that stayed is said on the screen and kept in the failure
        log: "창 닫기 보냄" used to be the last word whether the window closed or not (2026-11-11 report)."""
        out = getattr(self.mouse, "close_outcome", None)
        if not out or out is getattr(self, "_close_seen", None):
            return
        self._close_seen = out
        title = str(out.get("title") or out.get("process") or "").strip()
        if out.get("result") == "still":
            self._close_notice = "창이 닫히지 않았어요" + (f": {title}" if title else "") + " · 그 창이 닫기 요청을 받지 않아요"
            self._close_notice_until = time.perf_counter() + 4.0
            self._say(self._close_notice, 4.0)
        try:
            self.failures.trigger(t0, "close_result", note=json.dumps(out, ensure_ascii=False))
        except Exception:
            pass

    def _close_sign(self, t0: float, ui, detections) -> bool:
        """The rock sign held still asks to close the window; once more within a few seconds sends Alt+F4.
        True while the sign is held (the pinch controls are suspended then, so the folded fingers do not run the cursor)."""
        self._close_result(t0)
        ready = ui.stage == "main" and not self.paused and not ui.calibrating and not ui.use_index_pointer
        # switched off on the action screen: the sign does nothing (it used to keep closing windows whatever the screen said)
        ready = ready and self._binding_on("rock_sign", t0)
        if not ready or not detections:
            if self.close_sign.progress(t0) > 0 or self.close_sign.last_pose:
                self.close_sign.update(t0, None)
            return False
        quiet = self.close_sign.cfg("close_sign_quiet")
        blocked = not self._intent("rock_sign", t0)
        for g in (self.engine, self.pointer.gestures):
            last = max(g._index_released_at, g._scroll_released_at, g._pinky_fired_at,
                       max(g._last_trigger_times.values(), default=-1e9))
            if g._index_pinched or g._secondary_since or (t0 - last) < quiet:
                blocked = True
        blocked = blocked or bool(self.mouse.is_dragging or self.mouse.scroll_coasting)
        was_holding = self.close_sign.holding(t0)
        event = self.close_sign.update(t0, detections[0].landmarks, blocked=blocked)
        custom = self._sign_override("rock_sign") if event is not None else None
        if event is not None and isinstance(custom, dict):
            # another command was connected to the sign: asked for twice like the close, then that command runs
            if event.kind == "ask":
                self._say(f"{custom.get('badge') or '연결한 명령'}: 4초 안에 같은 손(검지·새끼만 펴기)을 한 번 더 하면 실행합니다", 4.0)
            elif event.kind == "close":
                ok, badge = self._run_resolved(get_action_registry(), custom)
                event.info.update({"sent": bool(ok), "command": str(badge)})
                if ok:
                    self._say(f"검지·새끼 펴기 → {badge}", 2.0)
        elif event is not None:
            if event.kind == "ask":
                self._say("창을 닫을까요? 4초 안에 같은 손(검지·새끼만 펴기)을 한 번 더 하면 닫습니다", 4.0)
            elif event.kind == "close":
                sent = self.mouse.send_motion_action("close_window")
                info = dict(getattr(self.mouse, "last_close_info", {}) or {})
                event.info.update({"sent": bool(sent), "window": info})
                if sent:
                    title = str(info.get("title") or info.get("process") or "").strip()
                    self._close_notice = "창 닫기 보냄" + (f": {title}" if title else "")     # which window it went to
                    self._close_notice_until = time.perf_counter() + 2.0
                elif info.get("own"):
                    self._close_notice, self._close_notice_until = "이 앱이 앞에 있어 닫지 않음: 닫을 창을 앞에 두세요", time.perf_counter() + 3.0
                else:
                    self._close_notice, self._close_notice_until = "닫을 수 없는 창 (바탕화면·작업표시줄)", time.perf_counter() + 3.0
                self._say(self._close_notice, 3.0)
            if event.kind in ("ask", "close"):
                self.failures.trigger(t0, f"close_{event.kind}", note=json.dumps(event.info, ensure_ascii=False))
        holding = self.close_sign.holding(t0)
        if holding and not was_holding:
            self.mouse.release_all()
            self.engine.reset()
            self.pointer.reset()
        return holding

    def _track_arm(self, t0: float, frame, ui, detections) -> None:
        """Pose every `pose_every` frames in palm mode; a visible elbow goes to the elbow pivot."""
        if self.pose is None or ui.use_index_pointer or not detections:
            return
        every = max(1, int(self.engine.config.get("pose_every", 3)))
        if self.frames % every:
            return
        lms = self.pose.detect(frame)
        if lms:
            self._pose_raw = (t0, [list(lms[i]) for i in range(11, 17)])
        hand_wrist = detections[0].landmarks[0]
        arm = pick_arm(lms, (hand_wrist.x, hand_wrist.y)) if lms else None
        if arm is None:
            return
        # Pose joints jitter a lot from frame to frame (the shoulder and elbow sat still but jumped on the preview):
        # average them, and keep the last good position of a joint the model is unsure of.
        k = max(0.05, min(1.0, float(self.engine.config.get("pose_smooth", 0.25))))
        min_vis = float(self.engine.config.get("pose_min_visibility", 0.5))
        prev = self._arm if (self._arm is not None and t0 - self._arm_t < 1.0) else None
        smooth = {"side": arm["side"]}
        for name in ("shoulder", "elbow", "wrist"):
            x, y, v = arm[name]
            if prev is None:
                smooth[name] = (x, y, v)
            elif v < min_vis:
                px, py, _ = prev[name]
                smooth[name] = (px, py, v)
            else:
                px, py, pv = prev[name]
                kk = k if pv >= min_vis else 1.0
                smooth[name] = (px + kk * (x - px), py + kk * (y - py), v)
        arm = smooth
        self._arm, self._arm_t = arm, t0
        ex, ey, ev = arm["elbow"]
        if ev >= float(self.engine.config.get("pose_min_visibility", 0.5)) and self.engine.config.get("elbow_pivot", False):
            self.elbow.set_pose((ex, ey), self.mouse.frame_aspect, t0)

    def _draw_arm(self, frame, t0: float) -> None:
        """Shoulder - elbow - wrist of the cursor arm (Pose). Joints the model is unsure of are drawn hollow."""
        if self._arm is None or t0 - self._arm_t > 0.5:
            return
        fh, fw = frame.shape[:2]
        min_vis = float(self.engine.config.get("pose_min_visibility", 0.5))
        pts = [self._arm["shoulder"], self._arm["elbow"], self._arm["wrist"]]
        xy = [(int(x * fw), int(y * fh)) for x, y, _ in pts]
        teal = (200, 200, 60)
        for (a, b), (_, _, va), (_, _, vb) in zip(zip(xy, xy[1:]), pts, pts[1:]):
            if min(va, vb) >= min_vis:
                cv2.line(frame, a, b, teal, 3, cv2.LINE_AA)
        for (x, y), (_, _, v), name in zip(xy, pts, ("shoulder", "elbow", "wrist")):
            if not (0 <= x < fw and 0 <= y < fh):
                continue
            cv2.circle(frame, (x, y), 9, teal, -1 if v >= min_vis else 2, cv2.LINE_AA)
            if name != "wrist":
                cv2.putText(frame, name, (x + 12, y - 8), cv2.FONT_HERSHEY_SIMPLEX, .55, teal, 2, cv2.LINE_AA)

    def _draw_elbow(self, frame, palm, aspect: float) -> None:
        """Estimated elbow (src/elbow_pivot.py) on the preview: a ring at it and the forearm line to the palm point.
        Off-screen (the usual case, below the frame) it is drawn at the frame edge with the line pointing to it."""
        fh, fw = frame.shape[:2]
        orange = (40, 160, 255)
        if self.elbow.source == "pose":
            return                                  # the Pose arm (_draw_arm) already shows the real elbow
        if self.elbow.elbow is None:
            cv2.putText(frame, "elbow: move left/right to find it", (12, fh - 14), cv2.FONT_HERSHEY_SIMPLEX, .55,
                        orange, 2, cv2.LINE_AA)
            return
        ex, ey = self.elbow.elbow[0] * fw, self.elbow.elbow[1] / max(1e-6, aspect) * fh
        if palm is not None:
            px, py = palm[0] * fw, palm[1] * fh
            cv2.line(frame, (int(px), int(py)), (int(ex), int(ey)), orange, 2, cv2.LINE_AA)
        inside = 0 <= ex < fw and 0 <= ey < fh
        mx, my = int(min(max(ex, 8), fw - 8)), int(min(max(ey, 8), fh - 8))
        cv2.circle(frame, (mx, my), 11, orange, 3 if inside else 2, cv2.LINE_AA)
        label = "elbow (estimated)"
        cv2.putText(frame, label if inside else label + " (off screen)", (mx + 14, max(18, my - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, .55, orange, 2, cv2.LINE_AA)

    def _click_log(self, config) -> Optional[ClickLog]:
        """Everyday clicks of the virtual hand and the F marks (src/click_log.py); None when switched off."""
        if not config.get("virtual_click_log", True):
            return None
        if self.click_log is None:
            self.click_log = ClickLog(self.log_dir / "virtual_clicks", pc=machine_info(str(config.get("pc_alias", "")))["pc"],
                                      camera=str(config.get("camera_note", "")))
        return self.click_log

    def _virtual_click_mark(self, now: float) -> bool:
        """F right after a virtual hand click: that click was not meant. True = handled (no "what was it?" question)."""
        kind = self.click_log.mark_last(now) if self.click_log is not None else None
        if kind is None:
            return False
        self._use_mark(now, "f_key")
        self._say(f"방금 {CLICK_NAMES.get(kind, kind)}: '클릭 아님'으로 기록했어요", 1.5)
        return True

    # ------------------------------------------------------------------ use log: joints around every command (src/use_log.py)
    def _use_frame(self, t0: float, detections, aspect: float, gate: Optional[GestureGate], active: bool) -> None:
        """Every frame, before anything acts on it. The TCN watches (the real checker when it is on, otherwise a copy that
        blocks nothing) and its probabilities go into the log's frames. A failure here switches the log off, never the mouse."""
        self._use_t = t0
        self._click_kind = ""
        self._use_watchers = {}
        self._use_real_kind = ""
        config = self.engine.config
        if not active or not config.get("use_event_log", True) or getattr(self, "_use_failed", False):
            return
        try:
            if self.use_log is None:
                self.use_log = UseLog(self.log_dir / "use_events", pc=machine_info(str(config.get("pc_alias", "")))["pc"],
                                      camera=str(config.get("camera_note", "")),
                                      max_mb=float(config.get("use_event_log_max_mb", 300.0)))
                self._use_round_t = t0
                self._use_decide(recount=True)
            hand = detections[0] if detections else None
            if hand is None:
                self._use_prev_action = "none"
            if gate is not None:
                self._use_real_kind = "online" if isinstance(gate, _online_gate_class()) else "tcn"
            watchers: Dict[str, GestureGate] = {}
            for kind in use_gate.KINDS:
                if kind == self._use_real_kind:
                    watchers[kind] = gate
                    self._watch_stale.add(kind)      # the copy missed these frames: it starts over when it watches again
                elif config.get("use_event_shadow", True):
                    copy = self._watcher(kind)
                    if copy is not None:
                        if kind in self._watch_stale:
                            copy.reset()
                            self._watch_stale.discard(kind)
                        copy.step(t0, hand, aspect)
                        watchers[kind] = copy
            self._use_watchers = watchers
            tcn = watchers.get("tcn")
            self.use_log.frame(t0, hand, None if tcn is None else tcn.last)
            self._use_auto(t0)
        except Exception as exc:
            self._use_failed = True
            self._say(f"사용 기록을 껐어요: {exc}", 5.0)

    def _model_version(self, kind: str, label: str = "") -> str:
        """Which model file a verdict came from: a verdict of another file says nothing about the one in use. For a taught
        gesture the verdict is its own checking model's (src/online/verifier.py), so that file's time is part of it."""
        path = GATE_MODEL if kind == "tcn" else (self._online_root or ONLINE_DEFAULT_ROOT) / "versions" / "production.pt"
        try:
            version = f"{kind}:{int(path.stat().st_mtime)}"
        except OSError:
            return ""
        verifier = getattr(self._watchers.get(kind), "verifiers", {}).get(label) if label else None
        return f"{version}+v{int(verifier.created)}" if verifier is not None else version

    def _hand_dir(self) -> str:
        """Which way the hand points now (the last half second of the use log's frames), "" when unknown."""
        log = self.use_log
        if log is None:
            return ""
        try:
            frames = list(log._frames)[-15:]
        except Exception:
            return ""
        return hand_dir.of_frames(frames)

    def _verifier(self, key: str):
        """(the watching model learned from this person, the taught gesture's checking model in it), or (None, None)."""
        watcher = self._use_watchers.get("online")
        verifier = getattr(watcher, "verifiers", {}).get(key) if watcher is not None else None
        return (watcher, verifier) if verifier is not None else (None, None)

    def _watcher(self, kind: str) -> Optional[GestureGate]:
        """The watching copy of a checker ("tcn" = the trained model, "online" = the model learned from this person), loaded in a
        thread on first use. None until then, or when it cannot load (no model, no onnxruntime / torch)."""
        if kind not in self._watchers and kind not in self._watch_loading and not self.dry_run:
            if kind == "online" and not (self.engine.config.get("online_learning_enabled", False) and self._model_version(kind)):
                return None
            self._watch_loading.add(kind)

            def load() -> None:
                try:
                    if kind == "online":
                        from src.online.safety import OnlineGate
                        made: GestureGate = OnlineGate(self._online_root or ONLINE_DEFAULT_ROOT, self.engine.config)
                    else:
                        predict, info = load_predictor(GATE_MODEL)
                        made = GestureGate(predict, info, self.engine.config)
                    self._watchers[kind] = made
                except Exception:
                    pass                           # the log still keeps the joints
                # a failed load stays in _watch_loading: it is not tried again every frame (a model swap clears it)

            threading.Thread(target=load, name=f"watcher-{kind}-load", daemon=True).start()
        return self._watchers.get(kind)

    @staticmethod
    def _use_label(action: str, gesture: str, virtual: bool) -> str:
        """The model label of the hand gesture behind a rule action ("" = the models know none for it)."""
        if virtual:
            return USE_LABELS_VIRTUAL.get(action, "")
        if action == "drag_hold":
            return "thumb_index_middle" if gesture == "thumb_index_middle_pinch" else "thumb_middle"
        return USE_LABELS.get(action, "")

    def _use_enforce(self, t0: float, result, virtual: bool) -> None:
        """Step 2: a command that a watching model has earned the right to stop (src/use_gate.py) is dropped when that model does
        not see its gesture as it starts: exactly the verdict the log counted. Nothing else is touched."""
        action = result.action
        if action not in USE_ACTIONS:
            self._use_blocking = None
            return
        if self._use_blocking == action:
            result.action = "none"                 # the grab that was stopped at its start stays stopped until it ends
            return
        self._use_blocking = None
        if action == self._use_prev_action:
            return
        label = self._use_label(action, result.active_gesture, virtual)
        # a left / right click with its own checking model (learned from this person's clicks, src/online/verifier.py): that
        # model decides, the way a taught gesture's does - the third try within a few seconds goes through
        click = self._click_model(click_key("rule", action, label, self._click_kind))
        if click and self._verifier(click)[1] is not None and self.engine.config.get("click_verifier_enforce", True):
            if not self._use_allows(click, t0, setting="click_verifier_enforce"):
                result.action = "none"
                self._use_blocking = action
            return
        if not self._use_gate:
            return
        rule = self._use_gate.get(use_gate.gate_key(action, label))
        if not rule:
            return
        kind = rule.get("model", "")
        watcher = self._use_watchers.get(kind)
        if watcher is None or rule.get("version") != self._model_version(kind):
            return                                 # that model is not watching now, or is not the file that earned it
        try:
            verdict = shadow_verdict(watcher, label, t0)
        except Exception:
            return
        if verdict is not None and verdict.get("would_pass") is False:
            result.action = "none"
            self._use_blocking = action
            self.use_blocked += 1
            self._say(f"{HAND_ACTION_NAMES.get(action) or action}: 의도한 동작으로 보이지 않아 실행하지 않았어요", 1.0)

    def _use_action(self, t0: float, action: str, gesture: str, virtual: bool = False, source: str = "rule") -> None:
        """A rule (or index pointer) action this frame: logged when it starts, not on every frame of a grab."""
        prev, self._use_prev_action = self._use_prev_action, action
        if action == prev or action not in USE_ACTIONS:
            return
        label = self._use_label(action, gesture, virtual) if source == "rule" else ""
        extra = {"click_kind": self._click_kind} if source == "rule" and action == "left_click" else {}
        self._use_event(source, action, t0, label=label, gesture=gesture, virtual=virtual, **extra)

    def _click_model(self, key: str) -> str:
        """The checking model that answers for a click: its kind's own (the second tap of a double click) once the app has
        trained one, else the plain click's (src/online/verifier.py pools a kind with too few uses into it)."""
        if key and self._verifier(key)[1] is None:
            return click_base(key)
        return key

    def _use_event(self, source: str, key: str, t0: Optional[float] = None, label: str = "", **extra) -> None:
        log = self.use_log
        if log is None or self.paused or getattr(self, "_use_failed", False):
            return
        try:
            now = self._use_t if t0 is None else t0
            taught = use_import_learnable(source, key)
            if taught:                             # which way the hand pointed: its own category (src/hand_direction.py)
                extra = {**extra, "dir": self._hand_dir()}
            split_key = hand_dir.split(key, extra.get("dir", "")) if taught else key
            verdicts: Dict[str, Any] = {}
            for kind, watcher in self._use_watchers.items():
                verdict = shadow_verdict(watcher, label or split_key, now)
                if verdict is not None:
                    verdict["model"] = self._model_version(kind, label or split_key)
                    verdicts[kind] = verdict
            enforced = self._use_gate.get(use_gate.gate_key(key, label or key), {}).get("model", "")
            click = click_key(source, key, label, str(extra.get("click_kind") or ""))   # which click, which mode, which kind
            checked, setting = ((self._click_model(click), "click_verifier_enforce") if click
                                else (split_key, "taught_verifier_enforce"))
            if self._verifier(checked)[1] is not None and self.engine.config.get(setting, True):
                enforced = "online"                # its own checking model decides: this run says nothing about that model
                extra = {**extra, "forced": self._use_forced == checked}
                self._use_forced = None
            log.event(source, key, now, label=label, shadow=verdicts.get("tcn"),
                      extra={**extra, "shadow_online": verdicts.get("online"), "gate_on": self._use_real_kind,
                             "enforced": enforced, "index_pointer": bool(self.ui.use_index_pointer)})
            if taught or click:
                self._use_pending[click or split_key] = self._use_pending.get(click or split_key, 0) + 1
                self._use_note()
        except Exception as exc:
            self._use_failed = True
            self._say(f"사용 기록을 껐어요: {exc}", 5.0)

    def _use_decide(self, recount: bool = False) -> None:
        """Reads the log's index in a thread and sets which commands a watching model may stop. New ones are announced.
        `recount` (at the start, and after a learning round): the taught gestures' uses no round has taken yet, from the log."""
        if self._use_deciding:
            return
        self._use_deciding = True
        folder = self.log_dir / "use_events"
        config = self.engine.config
        pc = machine_info(str(config.get("pc_alias", "")))["pc"]
        models = {kind: self._model_version(kind) for kind in use_gate.KINDS}
        root = self._online_root or ONLINE_DEFAULT_ROOT

        def work() -> None:
            try:
                if recount and config.get("online_learning_enabled", False):
                    from src.online.use_import import pending_detail
                    from src.online.verifier import read_status
                    composites = get_action_registry().composite_gestures      # a deleted gesture's old uses do not count
                    detail = {k: v for k, v in pending_detail(folder, root).items()
                              if not k.startswith("comp_") or hand_dir.base(k) in composites}
                    # only the uses the person passed count towards a learning round (src/use_review.py, 2026-11-11);
                    # the ones not looked at yet are counted apart, for the "검토 필요" card
                    review = bool(config.get("use_review_required", True))
                    self._use_pending = {k: v["ok"] + (0 if review else v["new"]) for k, v in detail.items()}
                    self._use_new = {k: v["new"] for k, v in detail.items()} if review else {}
                    self._use_status = read_status(root)
                if recount:
                    # the uses the exported gesture model (models/gesture_tcn.onnx) has not been trained on yet: enough
                    # of them and the app makes a candidate by itself (scripts/onnx_auto_update.py, src/use_training.py)
                    try:
                        from src import use_training
                        from src.gesture_catalog import CLASSES as GESTURE_CLASSES
                        state = use_training.read_state(root)
                        total = sum(use_training.counts(folder, GESTURE_CLASSES).values())
                        self._onnx_fresh = total - int(state.get("events", 0))
                        self._onnx_done = int(state.get("events", 0))
                        self._onnx_last = float(state.get("when", 0.0))
                        self._onnx_waiting = (Path(__file__).resolve().parents[1] / "models" / "candidate" / "summary.json").is_file()
                    except Exception:
                        self._onnx_fresh = 0
                if config.get("use_gate_auto", True):
                    decision = use_gate.decide(read_use_events(folder, frames=False), pc, models)
                    use_gate.save(folder / "gate.json", decision)
                    new = sorted(set(decision) - set(self._use_gate))
                    self._use_gate = decision
                    if new:
                        names = ", ".join(HAND_ACTION_NAMES.get(k.split(":")[0]) or self._use_name(k.split(":")[0]) for k in new)
                        self._say(f"이제 학습 모델이 확인해요: {names} (표시한 오작동을 절반 넘게 막았을 것으로 측정됨)", 5.0)
                else:
                    self._use_gate = {}
                self._use_note()
            except Exception:
                pass
            finally:
                self._use_deciding = False

        if self.dry_run:
            work()                                 # tests: no thread to wait for
        else:
            threading.Thread(target=work, name="use-gate-decide", daemon=True).start()

    def _vh_respond(self, t0: float, commanding: bool) -> str:
        """Sets the virtual hand's filters for this frame: config "virtual_hand_response" = "auto" (fast while moving, smooth
        while a command is made), "fast" or "smooth". Returns the mode in use."""
        mode = self.vh_responder.step(self.engine.config.get("virtual_hand_response", "auto"), commanding, t0)
        if mode != getattr(self, "_vh_mode", None):
            self._vh_mode = mode
            self.box_mapper.set_response(mode)
            self.view_smoother.set_response(mode)
        return mode

    def _use_name(self, key: str) -> str:
        """What the person calls a taught gesture (the composite's name), for the notices. A click: "좌클릭" / "우클릭"."""
        d = hand_dir.of_key(key)
        if d:                                      # one direction of a taught gesture: "손 펴기 유지 · ↑ 위쪽"
            return f"{self._use_name(hand_dir.base(key))} · {hand_dir.name(d)}"
        if key not in self._use_names and key.split(":")[0] in CLICK_ACTIONS:
            self._use_names[key] = click_name(key)     # "좌클릭 · 가상 손 (엄지+검지) · 더블클릭의 두 번째"
        if key not in self._use_names:
            try:
                reg = get_action_registry()
                self._use_names[key] = str((reg.composite_gestures.get(key) or {}).get("name")
                                           or reg.get_binding(key).get("name") or key)
            except Exception:
                self._use_names[key] = key
        return self._use_names[key]

    def _use_note(self) -> None:
        """One line for the main screen: what the app is collecting or has learned from the taught gestures' uses."""
        known = set(getattr(self._watchers.get("online"), "classes", ()) or ())
        parts = []
        items: List[Dict[str, Any]] = []         # the same, one card per gesture (2026-11-11: the line was hard to read)
        fresh_all = getattr(self, "_use_new", {})    # uses the person has not looked at yet (review required)
        base_ready = self._use_base_ready()
        total = {k: self._use_pending.get(k, 0) + fresh_all.get(k, 0) for k in set(self._use_pending) | set(fresh_all)}
        for key, n in sorted(total.items(), key=lambda kv: (self._is_click(kv[0]), -kv[1])):
            if n <= 0 or len(parts) >= 2:
                continue
            name = self._use_name(key)
            need = self._use_need(key)
            fresh, passed = fresh_all.get(key, 0), self._use_pending.get(key, 0)
            if fresh and passed < need <= n and not ((self._use_status.get(key) or {}).get("status") == "waiting"):
                # enough were collected: the person looks through them first, and only the passed ones are learned
                parts.append(f"'{name}' 사용 사례 {n}개가 모였어요 · 오탐지를 골라내면 TCN 학습을 시작해요")
                items.append({"key": key, "name": name, "state": "review", "n": n, "need": need, "review": fresh,
                              "text": f"검토하면 통과한 사례로 학습해요 (안 본 것 {fresh}개)", "hint": ""})
                continue
            if fresh:
                n = passed + fresh                   # still collecting: everything gathered so far
            else:
                n = passed
            again = " 다시" if key in known else ""
            if (self._use_status.get(key) or {}).get("status") == "waiting" and key not in known:
                continue                           # said below: it waits for another day, not for more uses today
            # a click's model learns what is NOT a click from the ones the person marks: say how, where it is collected
            how = " · 잘못 눌린 클릭은 5초 안에 F8(어느 창에서든)을 누르면 '아님'으로 배워요" if self._is_click(key) else ""
            if n >= need and not base_ready:
                # enough passed, but there is no base model to learn on: said, instead of "곧 학습" that never comes
                parts.append(f"'{name}' 사용 사례 {n}개가 모였어요 · 기본 모델이 없어 아직 학습을 시작하지 못해요")
                items.append({"key": key, "name": name, "state": "nobase", "n": n, "need": need,
                              "text": "기본 모델을 만든 뒤 학습을 시작해요 (자동, 1~2분)" if getattr(self, "_base_asked", False)
                              else "기본 모델이 없어 아직 학습을 시작하지 못해요", "hint": ""})
                continue
            parts.append(f"'{name}' 사용 사례 {n}개가 모였어요 · 곧 TCN 학습을{again} 시작해요" if n >= need
                         else f"'{name}' 사용 사례를 모으는 중 {n}/{need} · {need}번이 되면 TCN 학습을{again} 자동으로 시작해요{how}")
            items.append({"key": key, "name": name, "state": "ready" if n >= need else "collecting", "n": n, "need": need,
                          "text": (f"곧 TCN 학습을{again} 시작해요" if n >= need else f"{need}번이 되면 TCN 학습을{again} 자동으로 시작"),
                          "hint": "잘못 눌린 클릭은 5초 안에 F8 (어느 창에서든)" if self._is_click(key) else ""})
        for key, state in self._use_status.items():
            if key.startswith("comp_") and not hand_dir.of_key(key):
                continue                           # made before uses were split by direction: replaced by the per-direction ones
            if state.get("status") == "waiting" and key not in known and len(parts) < 3:
                today = self._use_pending.get(key, 0)
                fresh = fresh_all.get(key, 0)
                total = int(state.get('uses', 0)) + today
                one_day = state.get("reason") == "one_day"
                if fresh and today < WAITING_USES <= today + fresh and self._use_waiting(key):
                    parts.append(f"'{self._use_name(key)}' 새 사용 사례 {today + fresh}개 · 오탐지를 골라내면 검사를 시작해요")
                    items.append({"key": key, "name": self._use_name(key), "state": "review", "n": today + fresh,
                                  "need": WAITING_USES, "review": fresh,
                                  "text": f"검토하면 통과한 사례로 검사해요 (안 본 것 {fresh}개)", "hint": ""})
                    continue
                parts.append(f"'{self._use_name(key)}' 사용 사례 {total}개 저장됨 · "
                             + ("다른 날에도 쓰면 그날 사용으로 검사한 뒤 TCN 확인을 시작해요" if one_day
                                else f"최근 날의 사용이 {WAITING_USES}번 모이면 검사해요"))
                items.append({"key": key, "name": self._use_name(key), "state": "waiting", "n": total, "need": 0,
                              "text": "다른 날에도 쓰면 검사 후 TCN 확인 시작" if one_day
                              else f"최근 날의 사용 {WAITING_USES}번이 모이면 검사", "hint": ""})
        learned = sorted(k for k in (getattr(self._watchers.get("online"), "verifiers", {}) or {})
                         if not k.startswith("comp_") or hand_dir.of_key(k))      # (whole-gesture ones from before: unused now)
        if learned:
            does = "확인하는" if self.engine.config.get("taught_verifier_enforce", True) else "지켜보는"
            parts.append(f"TCN이 {does} 자세: " + ", ".join(self._use_name(k) for k in learned[:4])
                         + (f" 외 {len(learned) - 4}개" if len(learned) > 4 else ""))
            for k in learned[:4]:
                items.append({"key": k, "name": self._use_name(k), "state": "learned", "n": 0, "need": 0,
                              "text": f"TCN이 {does} 중", "hint": ""})
        onnx = self._onnx_item()
        if onnx is not None:
            items.append(onnx)
        self._learn_note = "   ·   ".join(parts)
        self._learn_items = items

    @staticmethod
    def _is_click(key: str) -> bool:
        return key.split(":")[0] in CLICK_ACTIONS and ":" in key

    def _use_need(self, key: str) -> int:
        """Uses of a gesture that start a learning round: clicks come many times a minute, so twice as many of them."""
        need = int(self.engine.config.get("auto_learn_min_events", 20))
        return need * 2 if self._is_click(key) else need

    def _use_waiting(self, key: str) -> bool:
        """This taught gesture's checking model is waiting for uses of another day to be tested on (src/online/verifier.py), and
        today is such a day: a few uses are enough to ask for a round."""
        state = self._use_status.get(key) or {}
        return state.get("status") == "waiting" and (state.get("reason") == "few_recent"
                                                     or state.get("newest_day") != time.strftime("%Y%m%d"))

    ONNX_KEY = "__onnx__"        # the card of the exported gesture model among the learning cards

    def _onnx_need(self) -> int:
        """Judged uses (passed clicks, rejected or marked commands) that start a candidate of the exported gesture model.
        The first time 50: every fifth is kept out to compare the old and the new model, and ten of those are the least
        that says anything (the first candidate of 2026-11-12 had 54 and 10). After that 30 new ones each time.
        Starting points, not measured: the person sees them on the card."""
        config = self.engine.config
        first = int(getattr(self, "_onnx_done", 0)) <= 0
        return int(config.get("onnx_auto_first_events", 50)) if first else int(config.get("onnx_auto_min_events", 30))

    def _onnx_item(self) -> Optional[Dict[str, Any]]:
        """The exported gesture model's card: how many judged uses of how many, or that a candidate waits."""
        if not self.engine.config.get("onnx_auto", True):
            return None
        fresh, need = max(0, int(getattr(self, "_onnx_fresh", 0))), self._onnx_need()
        if getattr(self, "_onnx_waiting", False):
            return {"key": self.ONNX_KEY, "name": "기본 손짓 모델 (onnx)", "state": "candidate", "n": 0, "need": 0,
                    "text": "새 후보가 준비됐어요 · 비교해 보고 적용하세요", "hint": ""}
        if fresh <= 0 and int(getattr(self, "_onnx_done", 0)) <= 0:
            return None
        return {"key": self.ONNX_KEY, "name": "기본 손짓 모델 (onnx)", "state": "ready" if fresh >= need else "collecting",
                "n": fresh, "need": need,
                "text": ("곧 후보를 학습해요 (약 10분)" if fresh >= need
                         else f"통과·오탐지로 판정한 사례가 {need}개 모이면 후보를 자동 학습 (약 10분)"), "hint": ""}

    def _onnx_auto(self, config) -> None:
        """Ask the UI thread for a candidate of the exported gesture model (Snapshot.onnx_request) once enough new uses
        were passed or rejected by the person, none is waiting to be looked at, and the last one is an hour old. The
        candidate replaces nothing: the person applies it in the app (2026-11-12, "내가 확인 후 교체")."""
        fresh = int(getattr(self, "_onnx_fresh", 0))
        if not config.get("onnx_auto", True):
            return
        if not getattr(self, "_onnx_cut_checked", False):
            # a candidate training the app was closed in the middle of (its mark is there, its process is gone): asked
            # for again once, whatever the counts say; the training reuses the parts it had finished
            self._onnx_cut_checked = True
            try:
                from src.online.round_marker import _alive
                mark = json.loads((Path(__file__).resolve().parents[1] / "models" / "candidate" / "running.json")
                                  .read_text(encoding="utf-8"))
                if not _alive(int(mark.get("pid", 0) or 0)):
                    self._onnx_request = getattr(self, "_onnx_request", 0) + 1
                    self._say("지난번에 끝나지 못한 기본 손짓 모델 후보 학습을 이어서 해요", 5.0)
                    return
            except (OSError, ValueError):
                pass
        if fresh == getattr(self, "_onnx_asked", None):
            return
        if fresh < self._onnx_need() or getattr(self, "_onnx_waiting", False):
            return
        if time.time() - float(getattr(self, "_onnx_last", 0.0)) < float(config.get("onnx_auto_cooldown_seconds", 3600.0)):
            return
        self._onnx_asked = fresh
        self._onnx_request = getattr(self, "_onnx_request", 0) + 1
        self._say(f"쓰면서 모은 사례 {fresh}개로 기본 손짓 모델 후보를 학습해요 (약 10분, 끝나면 확인 후 적용)", 5.0)

    def _use_base_ready(self) -> bool:
        """Is there a base model for the learning rounds (data/online: made by scripts/online_make_base.py)?"""
        root = self._online_root or ONLINE_DEFAULT_ROOT
        return (root / "encoder.json").is_file() or (root / "versions" / "production.pt").is_file()

    def _use_auto(self, t0: float) -> None:
        """A learning round is asked for (the UI thread owns the learning process: Snapshot.learn_request) when a taught gesture
        has been used often enough, or enough commands were marked as not meant; a few seconds after the last command, so its
        mark can still arrive. Now and then the decision above is taken again as well."""
        config = self.engine.config
        log = self.use_log
        if log is None:
            return
        if log.last is not None and t0 - log.last["t"] < float(config.get("auto_learn_idle_seconds", 6.0)):
            return
        need = int(config.get("auto_learn_min_events", 20))
        if log.events - self._use_round_events >= need:
            self._use_round_events = log.events
            self._use_decide()
        ready = [k for k, n in self._use_pending.items()
                 if n >= self._use_need(k) or (n >= WAITING_USES and self._use_waiting(k))]
        marks = log.marks - self._use_round_marks >= int(config.get("auto_learn_min_marks", 5))
        # a round the app was closed in the middle of (src/online/round_marker.py): looked for once, when the app starts,
        # and started again - its uses were already taken out of the log, so nothing else would ask for it
        if not getattr(self, "_use_cut_checked", False):
            self._use_cut_checked = True
            try:
                from src.online import round_marker
                marker_root = self._online_root or ONLINE_DEFAULT_ROOT
                self._use_cut_off = round_marker.unfinished(marker_root)
                # the cut-off round goes into the times record, and the app says what it makes of the last rounds:
                # leave the app open that long / saving in the middle would help / keep the prepared data instead
                if round_marker.note_cut(marker_root):
                    self._learn_advice = str(round_marker.advice(marker_root).get("text") or "")
                    if self._learn_advice:
                        self._say(self._learn_advice, 8.0)
            except Exception:
                self._use_cut_off = False
        cut_off = getattr(self, "_use_cut_off", False)
        self._onnx_auto(config)
        if not (ready or marks or cut_off) or (self._use_rounds and t0 - self._use_round_t < float(config.get("auto_learn_cooldown_seconds", 600.0))):
            return
        if not (config.get("online_learning_enabled", False) and config.get("auto_learn", True)):
            return
        if not self._use_base_ready():
            # No base model (a fresh copy of the project: data/ is not in git). The round cannot start, and the card used
            # to say "곧 학습" for good (2026-11-11). The app makes the base model itself, once per run
            # (scripts/online_make_base.py, a minute or two), and the cards say so meanwhile.
            if not getattr(self, "_base_asked", False):
                self._base_asked = True
                self._base_request = getattr(self, "_base_request", 0) + 1
                self._say("학습에 필요한 기본 모델이 없어 먼저 만들어요 (1~2분)", 5.0)
                self._use_note()
            return
        self._use_round_t, self._use_round_marks = t0, log.marks
        self._use_rounds += 1
        if cut_off and not (ready or marks):
            self._say("지난번에 앱을 끄면서 끝나지 못한 TCN 학습을 다시 시작해요", 5.0)
        self._use_cut_off = False
        for key in ready:
            self._use_pending[key] = 0             # handed to the round (counted again from the log when it ends)
        self._learn_request += 1
        self._use_note()

    def _use_allows(self, key: str, t0: Optional[float] = None, setting: str = "taught_verifier_enforce") -> bool:
        """A taught gesture's command: does its checking model (src/online/verifier.py) see the gesture now? Without one: yes,
        unless a watching model earned the right to stop that command (src/use_gate.py).
        The quick model already said yes to get here, so a no means the two disagree. A person who really means it tries again:
        the third try within RETRY_SECONDS goes through, and is logged as a use the checking model missed (it learns from it)."""
        now = self._use_t if t0 is None else t0
        plain = key
        if setting == "taught_verifier_enforce":   # a taught gesture is checked by the model of the way the hand points now
            key = hand_dir.split(key, self._hand_dir())
        watcher, verifier = self._verifier(key)
        direct = verifier is not None and self.engine.config.get(setting, True)
        if not direct:
            rule = self._use_gate.get(use_gate.gate_key(plain, plain))
            if not rule:
                return True
            kind = rule.get("model", "")
            watcher = self._use_watchers.get(kind)
            key = plain                            # those rules are made per gesture, not per direction
            if watcher is None or rule.get("version") != self._model_version(kind, key):
                return True
        try:
            verdict = shadow_verdict(watcher, key, now)
        except Exception:
            return True
        if verdict is None or verdict.get("would_pass") is not False:
            self._use_retries.pop(key, None)
            return True
        tries = [t for t in self._use_retries.get(key, []) if now - t <= RETRY_SECONDS] + [now]
        if direct and len(tries) >= RETRY_PASS:
            self._use_retries.pop(key, None)
            self._use_forced = key
            return True
        self._use_retries[key] = tries
        self.use_blocked += 1
        self._say(f"{self._use_name(key)}: 의도한 동작으로 보이지 않아 실행하지 않았어요"
                  + (f" (다시 하면 {RETRY_PASS}번째에 실행돼요)" if direct else ""), 1.5)
        return False

    def _use_mark(self, now: float, reason: str) -> None:
        """F (or pausing right after a command): the latest command in the use log was not meant."""
        if self.use_log is not None:
            try:
                self.use_log.mark_last(now, reason)
            except Exception:
                pass

    def _click_check(self, config) -> Optional[ClickCheck]:
        """The TCN's look at the virtual hand's thumb + index clicks (src/click_check.py); None when switched off."""
        if not config.get("virtual_click_check", False):     # off by default: see CLICK_CHECK_THRESHOLD
            return None
        if self.click_check is None and not self.dry_run:
            self.click_check = ClickCheck(float(config.get("virtual_click_threshold", CLICK_CHECK_THRESHOLD)))
        return self.click_check

    def _checked(self, check: Optional[ClickCheck], t0: float) -> bool:
        """Does the model see this thumb + index press as one? (No model: yes.) Says so when it drops one."""
        if check is None or check.allows(self._pinch_since, t0):
            return True
        self._pinch_since = None           # this press is done: no drag later, no click on opening
        self._pinch_rejected = True        # (allows() says yes to a press without a start time, so remember the no)
        self._say("집기로 보이지 않아 클릭하지 않았어요", .8)
        return False

    def _gate_for(self, ui) -> Optional[GestureGate]:
        """The intent checker when it is switched on (and the model loads), else None. `gate_model` "online" uses the model learned from
        this person (src/online/safety.py); a promoted model or a rollback reloads it."""
        key = (getattr(ui, "model_version", 0), getattr(ui, "gate_model", "tcn"), self._online_model_version)
        reload = key != getattr(self, "_gate_key", None)
        if reload:
            self._gate_key = key
            self._gate_failed = False
        if not ui.tcn_gate or self._gate_failed:
            return None
        if self.gate is None or reload:
            try:
                if key[1] == "online":
                    from src.online.safety import OnlineGate
                    replacement = OnlineGate(self._online_root or ONLINE_DEFAULT_ROOT, self.engine.config)
                    note = f"손짓 확인: 내 모델 켜짐 ({len(replacement.classes) - 1}종 동작)"
                else:
                    predict, info = load_predictor(GATE_MODEL)
                    replacement = GestureGate(predict, info, self.engine.config)
                    note = f"손짓 확인(TCN) 켜짐: 학습된 {len(info['classes']) - 1}종 동작을 확인해요"
                self.mouse.release_all()
                self.engine.reset()
                self.pointer.reset()
                self.gate = replacement
                self._say(note, 3.0)
            except Exception as exc:
                # a failed reload keeps the checker that was working; only a first load that fails leaves none
                switched = self.gate is not None and isinstance(self.gate, _online_gate_class()) != (key[1] == "online")
                if switched:
                    self.gate = None          # the other kind was asked for: never keep confirming with the wrong model
                self._gate_failed = self.gate is None
                self._say(f"손짓 확인을 켜지 못했어요: {exc}", 5.0)
                return self.gate
        return self.gate
        return self.gate

    def _intent(self, target, now):
        gate = self.gate if self.ui.tcn_gate and not self.ui.use_index_pointer else None
        return gate is None or gate.allows(target, now)

    # ------------------------------------------------------------------ dataset recording
    def _rec_meta(self, mode: str) -> Dict[str, Any]:
        cam = self.camera
        cfg = self.engine.config
        try:
            real = cam.actual_mode()
        except Exception:
            real = None
        keys = ("pinch_threshold", "release_threshold", "click_threshold", "ring_click_threshold", "pinky_click_threshold",
                "pinch_size_ratio", "click_size_ratio", "ring_click_size_ratio", "pinky_click_size_ratio",
                "fist_dpi_multiplier", "shape_dpi_curve", "side_rearm_ratio", "curled_click_size_ratio")
        return {
            "camera": {"source": str(cam.config.source), "mode": list(real) if real else None,
                       "mirror": bool(cam.config.mirror), "phone_web": bool(cam.is_phone_web),
                       "note": str(cfg.get("camera_note", ""))},
            "frame_aspect": round(float(self.mouse.frame_aspect), 5),
            "control_hand": self.ui.control_hand, "profile": self.engine.profile_name or "",
            "pose": self.pose is not None,
            "rules": {k: cfg.get(k) for k in keys if k in cfg},
            "pose_joints": "MediaPipe Pose 11-16: left shoulder, right shoulder, left elbow, right elbow, left wrist, "
                           "right wrist (x, y, visibility)",
        }

    def _recording_mode(self, t0: float, ui, detections=()) -> bool:
        """Start / stop / steer the recording. True while a guided recording runs (the mouse must not move)."""
        discard_req = getattr(ui, "rec_discard", 0)
        if discard_req != getattr(self, "_rec_discard_seen", 0):
            self._rec_discard_seen = discard_req
            self._discard_recording(t0)
            self._rec_mode = "off"
            self._rec_focus = ""
            return False
        mode = ui.rec_mode if ui.stage == "main" and not ui.use_index_pointer else "off"
        focus = getattr(ui, "rec_focus", "") if mode == "guided" else ""
        if mode != self._rec_mode or focus != getattr(self, "_rec_focus", ""):
            self._stop_recording(t0)
            self._rec_mode = mode
            self._rec_focus = focus
            if mode in ("guided", "free"):
                self.mouse.release_all()
                meta = self._rec_meta(mode)
                meta["focus"] = focus
                meta["pc_alias"] = str(self.engine.config.get("pc_alias", ""))
                plan = getattr(ui, "rec_plan", None) if mode == "guided" else None
                self._guided = GuidedSession(self.engine.config, tasks=tasks_for(focus), plan=plan) if mode == "guided" else None
                if self._guided is not None:
                    from src.capture_rules import CaptureRules
                    self._capture_rules = CaptureRules(self.engine.config)
                    self._pause()
                    if self._guided.plan:
                        meta["capture_plan"] = self._guided.plan
                self._rec = SessionRecorder(self.rec_dir, mode, meta, now=t0)
                self._crop_rec = CropRecorder() if (mode == "guided" and self.engine.config.get("rec_save_crops")) else None
                self._rec_adv_seen = ui.rec_advance
        if self._guided is not None:
            if not self.paused:
                self._pause()
            self._guided.paused = getattr(ui, "rec_paused", False)
            if ui.rec_advance != self._rec_adv_seen:
                self._rec_adv_seen = ui.rec_advance
                self._guided.advance(t0)
            available = True
            if self._guided.plan:
                available = bool(detections and getattr(detections[0], "world", None))
            if self._guided.update(t0, available=available) and self._rec is not None:
                self._rec.event(t0, "set_done", {"set": self._guided.index - 1})
        return self._guided is not None

    def _discard_recording(self, t0: float) -> None:
        if self._rec is None:
            return
        rec = self._rec
        rec.discard()
        self._rec, self._guided, self._crop_rec = None, None, None
        self._rec_mode = "off"
        self._last_pipeline_result = {
            "path": "",
            "status": "discarded",
            "score": 0.0,
            "retrain_eligible": False,
            "retrain_started": False,
            "message": f"녹화를 취소하고 버렸습니다 ({rec.frames}프레임 삭제됨)",
        }
        self._rec_note = self._last_pipeline_result["message"]
        self._rec_note_until = t0 + 6.0
        self._say(self._rec_note, 4.0)

    def _stop_recording(self, t0: float) -> None:
        if self._rec is None:
            return
        rec = self._rec
        path = rec.close()
        self._rec, self._guided = None, None
        crops, self._crop_rec = self._crop_rec, None
        kept = ", ".join(f"{k} {v}" for k, v in sorted(rec.counts.items()))
        base_note = f"녹화 저장: {path.name} ({rec.frames}프레임: {kept}, 표시 {rec.marks})"
        # The quality check, cleaning and augmentation of the finished file took ~4 s on this thread and froze the camera loop
        # (loop_max 4215 ms, 111 camera frames lost, 2026-11-09): they run on their own thread now. The screen shows
        # "품질 검사 중" until they are done.
        self._pipeline_token = getattr(self, "_pipeline_token", 0) + 1
        token = self._pipeline_token
        self._last_pipeline_result = {
            "path": str(path), "status": "pending", "score": None, "frames": rec.frames, "marks": rec.marks,
            "retrain_eligible": False, "retrain_started": False, "message": "품질 검사 중…",
        }
        self._rec_note = f"{base_note} · 품질 검사 중…"
        self._rec_note_until = t0 + 600.0
        self._say(self._rec_note, 6.0)
        threading.Thread(target=self._finish_recording_pipeline, args=(token, path, rec.frames, rec.marks, base_note, crops),
                         daemon=True).start()

    def _finish_recording_pipeline(self, token: int, path, frames: int, marks, base_note: str, crops=None) -> None:
        if crops is not None and len(crops):
            try:
                crops.save(crops_path(path))          # saved here, not on the camera thread: it compresses a few MB
            except Exception:
                pass
        try:
            from src.training_center import run_post_recording_pipeline, set_recording_selected
            pipeline_res = run_post_recording_pipeline(
                path,
                self.engine.config,
                training_job=getattr(self, "training_job", None),
            )
            pipeline_res["frames"] = frames
            pipeline_res["marks"] = marks
            if pipeline_res.get("status") == "fail":
                set_recording_selected(path.name, False, path.parent)
            q_msg = pipeline_res.get("message", "")
            note = f"{base_note} · {q_msg}" if q_msg else base_note
        except Exception:
            # the check itself failed: that is not a pass (it used to be shown as "pass", score 1.0)
            base_note = f"{base_note} · 품질 검사를 하지 못했어요"
            pipeline_res = {
                "path": str(path),
                "status": "warning",
                "score": None,
                "frames": frames,
                "marks": marks,
                "retrain_eligible": False,
                "retrain_started": False,
                "message": base_note,
            }
            note = base_note
        if token != getattr(self, "_pipeline_token", 0):
            return                      # another recording was saved meanwhile: this result is stale
        self._last_pipeline_result = pipeline_res
        self._rec_note = note
        self._rec_note_until = time.perf_counter() + 8.0
        self._say(note, 6.0)

    def _record_frame(self, t0: float, detections, result, frame=None) -> None:
        if self._rec is None:
            return
        hand = detections[0] if detections else None
        if self._crop_rec is not None and hand is not None and frame is not None:
            self._crop_rec.add(self._rec.frames, frame, hand.landmarks)      # the picture of the frame about to be written
        pose = self._pose_raw[1] if self._pose_raw is not None and t0 - self._pose_raw[0] < 0.25 else None
        if self._guided is not None:
            label = self._guided.label(t0)
        elif getattr(self.ui, "rec_paused", False):
            label = {"target": "idle", "phase": "paused"}
        else:
            label = {"target": "none", "phase": "use"}
        rule = None
        if result is not None:
            dd = result.distances or {}
            rule = {"action": getattr(self, "_rule_action", result.action), "gesture": result.active_gesture,
                    "gated": result.action if self.gate is not None and ui_gate_on(self) else None,
                    "dpi": round(float(getattr(result, "dpi_multiplier", 1.0) or 1.0), 2),
                    "curl": round(float(self.engine._curl_s), 3) if self.engine._curl_s is not None else None,
                    "size": round(float(dd.get("hand_size", 0.0)), 4),
                    "mode": getattr(result, "hand_shape_mode", "normal"),
                    "clutch": getattr(self.mouse, "clutch_state", "inactive"),
                    "return": getattr(self.mouse, "return_state", "none")}
            if self._hand_follower.followed:
                rule["followed"] = True      # kept only by HandFollower: lets a recording measure what the rule adds
            if self._guided is not None:
                from types import SimpleNamespace
                from src.gesture_catalog import BY_KEY
                from src.capture_rules import detect_interfering_signals
                gtask = BY_KEY.get(label.get("task"))
                raw_action = rule["action"]
                raw_gesture = result.active_gesture
                observed = SimpleNamespace(action=raw_action, active_gesture=raw_gesture)
                rule["evaluated"] = True
                engine_raw = getattr(self, "_engine_raw", None)
                if engine_raw is not None:
                    # the real engine reading: rule.action / raw_action are replaced by the target in `do` (see docs/far-hand-loss.md)
                    rule["engine_action"], rule["engine_gesture"] = engine_raw
                rule["raw_action"] = raw_action
                rule["raw_gesture"] = raw_gesture
                obs_targets = getattr(self, "_guided_obs_targets", None)
                if obs_targets is None:
                    obs_targets = self._capture_rules.observe(t0, hand, observed, label)
                if gtask is not None and not gtask.free and gtask.label != "none":
                    lm_hand = hand.landmarks if hand else None
                    # Interference = what the engine itself read besides the target. `observed` holds the target action that
                    # guided capture put in (see above), which can never match another gesture, so use the real reading.
                    engine_seen = (SimpleNamespace(action=engine_raw[0], active_gesture=engine_raw[1])
                                   if engine_raw is not None else observed)
                    rule["interfering_targets"] = (
                        detect_interfering_signals(lm_hand, engine_seen, gtask.key)
                        if label.get("phase") == "do"
                        else []
                    )
                    if label.get("phase") == "do":
                        rule["targets"] = [t for t in obs_targets if t == gtask.key]
                        if gtask.key in rule["targets"]:
                            rule["action"] = gtask.action or gtask.label
                            rule["gesture"] = (
                                f"{gtask.label}_pinch"
                                if gtask.label in ("thumb_index", "thumb_middle", "thumb_ring", "thumb_pinky", "thumb_index_middle")
                                else gtask.label
                            )
                        else:
                            rule["action"] = "none"
                            rule["gesture"] = "none"
                    else:
                        rule["targets"] = []
                        rule["action"] = "none"
                        rule["gesture"] = "none"
                elif label.get("phase") in ("prep", "rest", "waiting", "paused"):
                    rule["interfering_targets"] = []
                    rule["targets"] = []
                    rule["action"] = "none"
                    rule["gesture"] = "none"
                else:
                    rule["interfering_targets"] = []
                    rule["targets"] = list(obs_targets)
        self._rec.frame(t0, hand, pose, label, rule, self.mouse.last_screen_pos)

    def _rec_view(self, t0: float) -> Optional[Dict[str, Any]]:
        if self._rec is None:
            if t0 < self._rec_note_until:
                view: Dict[str, Any] = {
                    "mode": "off", "prompt": "", "sub": self._rec_note, "progress": 0.0, "overall": 0.0,
                    "waiting": False, "frames": 0,
                }
                if self._last_pipeline_result is not None:
                    view["quality_status"] = self._last_pipeline_result.get("status")
                    view["quality_score"] = self._last_pipeline_result.get("score")
                    view["quality_message"] = self._last_pipeline_result.get("message")
                    view["retrain_eligible"] = bool(self._last_pipeline_result.get("retrain_eligible"))
                    view["retrain_started"] = bool(self._last_pipeline_result.get("retrain_started"))
                    view["file"] = Path(self._last_pipeline_result.get("path", "")).name
                return view
            return None
        if self._guided is not None:
            v = dict(self._guided.view(t0))
        else:
            free_paused = bool(getattr(self.ui, "rec_paused", False))
            v = {
                "prompt": (
                    "일시정지 · 팔을 올리고 자세를 잡은 뒤 스페이스바(또는 [계속])를 눌러 녹화를 시작하세요"
                    if free_paused
                    else "평소처럼 쓰세요 (스페이스바: 일시정지 · 이상하면 F)"
                ),
                "sub": "",
                "progress": 0.0,
                "overall": 0.0,
                "waiting": False,
                "paused": free_paused,
            }
        v.update(mode=self._rec_mode, frames=self._rec.frames, file=self._rec.path.name, marks=self._rec.marks)
        v["sub"] = (v.get("sub") or "") + f"  ·  {self._rec.frames}프레임 녹화 중"
        return v

    def _admin_window_in_front(self, t0: float) -> bool:
        """Task Manager and other admin windows drop this app's input unless the app is admin too (src/elevation.py).
        Asked twice a second: it is a few Windows calls."""
        if t0 - self._admin_checked_t >= 0.5:
            self._admin_checked_t = t0
            try:
                from src.elevation import blocked_by_elevated_window
                self._admin_blocked = bool(blocked_by_elevated_window())
            except Exception:
                self._admin_blocked = False
        return self._admin_blocked

    @staticmethod
    def _hand_width_fraction(landmarks, width: int, height: int) -> float:
        """Hand size as in docs/far-hand-loss.md: wrist to the farthest finger base (5, 9, 13, 17), in frame widths."""
        wrist = landmarks[0]
        aspect = height / max(1, width)
        return max(math.hypot(landmarks[k].x - wrist.x, (landmarks[k].y - wrist.y) * aspect) for k in (5, 9, 13, 17))

    def _palm_axes(self, t0: float, ui, detections) -> bool:
        """Cursor direction wizard for the palm / fist cursor (src/palm_axes.py). True while it records (no cursor moves)."""
        start, cancel, reset = ui.palm_axes_request, ui.palm_axes_cancel, ui.palm_axes_reset
        seen_start, seen_cancel, seen_reset = self._palm_seen
        self._palm_seen = (start, cancel, reset)
        ready = ui.stage == "main" and not ui.use_index_pointer and self.test is None
        if reset != seen_reset:
            self._palm_cal = None
            self.engine.config.pop("palm_axes", None)
            self.engine.save_config()
            self._palm_note, self._palm_note_until = "커서 방향 보정을 지웠어요", t0 + 3.0
        if cancel != seen_cancel or not ready:
            self._palm_cal = None
        if start != seen_start and ready:
            self.mouse.release_all()
            self.engine.reset()
            self._palm_cal = PalmAxesCalibration(self.engine.config, start=t0)
        cal = self._palm_cal
        if cal is None:
            return False
        palm = self.engine.palm_anchor_point(detections[0].landmarks) if detections else None
        if cal.update(t0, palm, self.mouse.frame_aspect):
            self._palm_cal = None
            if cal.axes is not None:
                self.engine.config["palm_axes"] = [round(a, 4) for a in cal.axes]
                self.engine.save_config()
                self._palm_note = "커서 방향 보정 완료. " + cal.error
            else:
                self._palm_note = "커서 방향 보정 실패: " + cal.error
            self._palm_note_until = t0 + 5.0
            self.mouse.release_all()
        return self._palm_cal is not None

    def _palm_view(self, t0: float) -> Tuple[bool, str, float, str, bool]:
        saved = valid_axes(self.engine.config.get("palm_axes"))
        if self._palm_cal is not None:
            prompt, progress, note = self._palm_cal.view(t0)
            return True, prompt, progress, note, saved
        return False, self._palm_note if t0 < self._palm_note_until else "", 0.0, "", saved

    # ------------------------------------------------------------------ drawing mode (src/draw_mode.py)
    def _set_draw(self, on: bool) -> None:
        if on == self.draw.active:
            return
        self.draw.set_active(on)
        self.mouse.release_all()
        self.engine.reset()
        self._say("그리기 모드 켜짐 · 검지를 펴서 그리고, 손을 펴거나 쥐면 끝" if on else "그리기 모드 꺼짐", 2.0)

    INSPECT_HOLD = 1.5       # s a signal's name stays on the drawn hand while the control is off

    def _inspect_note(self, t0: float, hand, result, pinched) -> str:
        """The control is OFF: what the hand's signal would do, written beside the drawn hand so a gesture can be checked
        without anything happening (2026-11-11 request: "제어 상태가 아닌 상태에서 가상 손에서 보면서 검수할 수 있게 명령
        신호 정보들이 다 나오도록"). Nothing is run and nothing is logged. A command that fired stays INSPECT_HOLD
        seconds; otherwise the pointing shape or the hand shape the app sees now."""
        from src.action_bindings import POSTURE_NAMES_KO
        lm, aspect = hand.landmarks, self.mouse.frame_aspect
        fired = ""
        try:
            name = HAND_ACTION_NAMES.get(result.action, "")
            if name and result.action in USE_ACTIONS:
                fired = name                                   # a click, a drag, a scroll grab, the task switcher …
            reg = get_action_registry()
            if self._inspect_detector is None or self._inspect_detector.registry is not reg:
                self._inspect_detector = CompositeGestureDetector(reg)
            hit = self._inspect_detector.step(t0, lm, result.active_gesture, pinched, aspect, scope="normal")
            if hit is not None:                                # a gesture the person connected (hold / swipe / double pinch)
                badge = str(reg.resolve_effective_action(hit["key"], {}).get("badge") or "")
                fired = f"{hit.get('name') or hit['key']}" + (f" → {badge}" if badge else "")
            posture = hand_posture(lm, aspect)
            sequences = self.seq_store.active(bool(self.motion.active))
            if sequences:
                done = self.sequences.step(t0, posture, sequences)
                if done is not None:
                    badge = str(reg.resolve_effective_action(done, {}).get("badge") or "")
                    fired = f"이어 하기: {self.seq_store.items.get(done, {}).get('name', done)}" + (f" → {badge}" if badge else "")
            if fired:
                self._inspect = (fired, t0 + self.INSPECT_HOLD)
            if t0 < self._inspect[1]:
                return self._inspect[0]
            pointing = point_shape(lm, aspect, self.point.tilt, self.point.right) if getattr(self.ui, "point_mode", True) else ""
            if pointing:
                return "포인팅: " + ("더블클릭 모양" if pointing == "double" else "우클릭 모양")
            return ("손 모양: " + POSTURE_NAMES_KO.get(posture, posture)) if posture else ""
        except Exception:
            return ""

    def _run_sequence(self, key: str) -> None:
        self._run_gesture_key(key, self.seq_store.items.get(key, {}).get("name", key), "이어 하기")

    def _run_gesture_key(self, key: str, name: str, kind: str) -> None:
        reg = get_action_registry()
        fg = self.mouse.foreground_info() if not self.mouse.dry_run else {}
        resolved = reg.resolve_effective_action(key, fg)
        ok, badge = self._run_resolved(reg, resolved)
        self._recent_action, self._recent_until = "none", time.perf_counter() + .8
        self._say(f"{kind} [{name}] → {badge}", 1.5)

    # palm mode's held moves, by what the rule engine reports (src/default_moves.py)
    PALM_HELD = {("scroll_grab", "thumb_index_pinch"): "thumb_index",
                 ("drag_hold", "thumb_middle_pinch"): "thumb_middle_drag",
                 ("drag_hold", "thumb_index_middle_pinch"): "thumb_index_middle"}

    def _move_binding(self, key: str) -> Dict[str, Any]:
        """What a default move is connected to now. The foreground window is asked only when the move has app commands
        (this runs every frame of a held move)."""
        reg = get_action_registry()
        fg = (self.mouse.foreground_info() if reg.get_binding(key).get("app_overrides") and not self.mouse.dry_run else {})
        return reg.resolve_effective_action(key, fg)

    def _run_default_move(self, key: str) -> None:
        """A default move connected to another command: run it (once) and say so."""
        reg = get_action_registry()
        fg = self.mouse.foreground_info() if not self.mouse.dry_run else {}
        ok, badge = self._run_resolved(reg, reg.resolve_effective_action(key, fg))
        if ok:
            name = default_moves.NAMES.get(key) or key
            self._say(f"{name} → {badge}", 1.5)
            self._recent_action, self._recent_until = key, time.perf_counter() + .8

    def _palm_held(self, t0: float, result) -> None:
        now_key = self.PALM_HELD.get((result.action, result.active_gesture))
        for key in ("thumb_index", "thumb_middle_drag", "thumb_index_middle"):
            on = key == now_key
            mode, fire = self.holds.step(key, on, self._move_binding(key) if on else None, t0)
            if fire:
                self._run_default_move(key)
            if on and mode != "native":
                result.action, result.is_moving = "none", False

    def _run_resolved(self, reg, resolved):
        """Run a binding; the mode switches the registry cannot reach are done here."""
        if not self._use_allows(str(resolved.get("gesture_key", ""))):
            return False, "의도한 동작으로 보이지 않음"
        if resolved.get("action_type") == "mouse_action" and resolved.get("action_value") == "toggle_draw":
            self._set_draw(not self.draw.active)
            out = (True, "그리기 모드 " + ("켜짐" if self.draw.active else "꺼짐"))
        else:
            out = reg.execute_resolved_action(resolved, dry_run=self.mouse.dry_run, mouse_controller=self.mouse)
        if not out[0] and resolved.get("action_type") == "launch_app":
            self._say(str(out[1]), 4.0)          # a program that could not be started is said, not swallowed
        if out[0] and resolved.get("action_type") != "none":
            # the binding key and the kind of command only: never what is typed or opened
            self._use_event("binding", str(resolved.get("gesture_key", "")), action_type=str(resolved.get("action_type", "")))
        return out

    def _draw_step(self, t0: float, ui, detections, fw: int, fh: int) -> None:
        box = ui.virtual_box if valid_box(ui.virtual_box) else DEFAULT_BOX
        m = self.mouse.absolute_monitor
        if not detections:
            judged = self.draw.lost(t0)
        else:
            judged = self.draw.step(t0, detections[0].landmarks, box, fw, fh, aspect=m.width / max(1, m.height))
        if judged is None:
            return
        if not judged["ok"]:
            self._say(f"그림을 알아보지 못했어요 ({judged['why']})", 1.2)
            return
        if self.paused:
            self._say(f"그림 [{judged['name']}] · 일시정지 중이라 실행 안 함", 1.2)
            return
        reg = get_action_registry()
        fg = self.mouse.foreground_info() if not self.mouse.dry_run else {}
        resolved = reg.resolve_effective_action(judged["key"], fg)
        ok, badge = self._run_resolved(reg, resolved)
        if self.draw.last is not None:
            self.draw.last["action"] = badge
        self._say(f"그림 [{judged['name']}] → {badge}", 1.5)

    def _log_composite_fire(self, comp: Dict[str, Any], detector=None) -> None:
        """The 3 s of joints before a composite gesture fired (logs/composite_fires, the last 50; joints only): to see
        afterwards WHY a command ran - the looks shown to the camera do not show what happens in use (2026-11-11)."""
        try:
            import json
            d = self.log_dir / "composite_fires"
            d.mkdir(parents=True, exist_ok=True)
            frames = [{"t": round(t, 3), "posture": p, "engine": g,
                       "lm": [[round(q.x, 4), round(q.y, 4), round(getattr(q, "z", 0.0) or 0.0, 4)] for q in lm]}
                      for t, p, g, lm in list((detector or self.composite_detector).trace)]
            name = time.strftime("%Y%m%d-%H%M%S") + f"-{comp['key']}.json"
            (d / name).write_text(json.dumps({"key": comp["key"], "posture": comp.get("base_posture"),
                                              "trigger": comp.get("trigger_type"), "frames": frames}), encoding="utf-8")
            for old in sorted(d.glob("*.json"))[:-50]:
                old.unlink()
        except Exception:
            pass

    def _pose_teach_save(self, label: str) -> None:
        """The last [보여주기] look's joints as an example of `label` (src/posture_teach.py). The result then says so."""
        result = self.pose_probe.result or {}
        frames = [f["lm"] for f in getattr(self.pose_probe, "_log", []) if f.get("lm")]
        if result.get("state") != "done" or not frames or not label:
            return
        from types import SimpleNamespace
        from src.posture_teach import save_example
        aspect = self.pose_probe.aspect
        rule = [hand_posture([SimpleNamespace(x=p[0], y=p[1], z=p[2]) for p in lm], aspect, taught=False) for lm in frames]
        try:
            save_example(label, frames, rule)
        except OSError:
            return
        self.pose_probe.result = relabelled(result, label)

    def _pose_probe_view(self, t0: float):
        self.pose_probe.finish_if_due(t0)       # also when the hand is gone (too few frames -> "failed")
        return self.pose_probe.view(t0)

    def _sign_override(self, key: str):
        """A sign with its own detector (V = control on/off, thumbs-up = motion mode): its binding if the user changed
        it ("off" when switched off), else None (the sign does its built-in job)."""
        try:
            reg = get_action_registry()
            b = reg.get_binding(key)
            if not b.get("enabled", True):
                return "off"
            fg = self.mouse.foreground_info() if not self.mouse.dry_run else {}
            resolved = reg.resolve_effective_action(key, fg)
        except Exception:
            return None
        default = DEFAULT_GESTURE_BINDINGS.get(key, {})
        if not resolved.get("matched_app") and (resolved.get("action_type"), resolved.get("action_value")) == \
                (default.get("action_type"), default.get("action_value")):
            return None
        return resolved

    def _binding_on(self, key: str, t0: float) -> bool:
        """Whether the action screen's binding for `key` is switched on (read again at most twice a second)."""
        cache = getattr(self, "_binding_cache", None)
        if cache is None:
            cache = self._binding_cache = {}
        hit = cache.get(key)
        if hit is None or t0 - hit[0] > .5:
            try:
                from src.action_bindings import get_action_registry
                on = bool(get_action_registry().get_binding(key).get("enabled", True))
            except Exception:
                on = True
            hit = cache[key] = (t0, on)
        return hit[1]

    def _motion(self, t0: float, ui, detections) -> bool:
        """Run motion mode for this frame. True while it is on (the pinch controls are then suspended).
        With the mouse control off it runs as a simulation (2026-11-11 request): it can be entered and its swipes are told on the
        screen, but no key is sent and no command run."""
        ready = ui.stage == "main" and not ui.calibrating
        sim = self.paused
        request = ""
        if ui.motion_request != self._motion_seen:
            self._motion_seen = ui.motion_request
            request = "toggle" if ready else ""
        if not ready:
            if self.motion.active:
                self.motion.update(t0, None, request="off")
            return False
        lm = detections[0].landmarks if detections else None
        # the thumbs-up binding switched off on the action screen: the sign no longer turns motion mode on
        sign_off = not self.motion.active and not request and not self._binding_on("thumbs_up", t0)
        blocked = self._motion_blocked(t0) or sign_off or (not self.motion.active and not request and not self._intent("thumbs_up", t0))
        event = self.motion.update(t0, lm, request=request, blocked=blocked)
        if self._motion_last.startswith("창 닫기?") and self.motion.close_pending(t0) <= 0:
            self._motion_last = ""            # the question ran out
        if event is not None:
            custom = self._sign_override("thumbs_up") if event.kind == "enter" and not request else None
            if custom is not None:
                # the thumbs-up's binding was changed: run it instead of motion mode (the button still opens motion mode)
                self.motion.update(t0, None, request="off")
                if sim:
                    if custom != "off":
                        self._say(f"시뮬레이션 · 엄지 위로 → {custom.get('badge', '')} (실행 안 함)", 1.5)
                    return False
                self.mouse.release_all()
                if custom != "off":
                    ok, badge = self._run_resolved(get_action_registry(), custom)
                    self._say(f"엄지 위로 → {badge}", 1.5)
                return False
            if event.kind == "enter":
                if not sim:
                    self.mouse.release_all()
                    self.engine.reset()
                    self.pointer.reset()
                self._motion_last = ""
                self._say("모션 모드 켜짐 (시뮬레이션: 키는 보내지 않아요)" if sim
                          else "모션 모드 켜짐: 손을 펴고 좌우로 쓸어 보세요", 3.0)
            elif event.kind == "exit":
                self._say(f"모션 모드 꺼짐 ({event.info.get('why')})", 2.0)
            elif event.kind == "close_ask":
                self._motion_last = "창 닫기? 한 번 더 아래로"
                self._say("창을 닫을까요? 3초 안에 손을 올렸다 한 번 더 아래로 쓸면 닫습니다", 3.0)
            elif event.kind == "swipe":
                from src.gesture_catalog import BY_KEY, MOTION_TARGETS
                target_key = MOTION_TARGETS.get(event.action, event.action)
                confirmed = self._intent(target_key, t0)
                if sim:                            # what it would have sent, nothing sent
                    self._motion_last = "시뮬레이션: " + self._motion_would(event.action, target_key, BY_KEY)
                    sent = None
                else:
                    sent = confirmed and self.mouse.send_motion_action(event.action)
                if sent is None:
                    pass
                elif sent:
                    if event.action in ACTION_LABELS:
                        self._motion_last = ACTION_LABELS[event.action]
                    elif target_key in BY_KEY:
                        self._motion_last = BY_KEY[target_key].name
                    else:
                        self._motion_last = event.action
                else:
                    self._motion_last = "TCN 동작 확인 안 됨" if not confirmed else "실행 안 됨"
                self._say(f"모션: {self._motion_last}" + (" (실행 안 함)" if sent is None else ""), 1.5)
            if self.failures.trigger(t0, f"motion_{event.kind}", note=json.dumps(event.info, ensure_ascii=False)):
                pass
        return self.motion.active

    def _motion_composites(self, t0: float, hand) -> None:
        """Motion mode is on: the composite gestures marked "motion mode only" (2026-11-11 request: a gesture made in
        [말·글로 연결] that works only in motion mode). The rule engine does not run here, so the hand shape comes from
        the joints alone (as for the sequences). With the control off it is told on the screen, not run."""
        reg = get_action_registry()
        det = self.motion_composite_detector
        if det.registry is not reg:
            det = self.motion_composite_detector = CompositeGestureDetector(reg)
        if not any(c.get("motion_only") and c.get("enabled", True) for c in reg.composite_gestures.values()):
            det.reset()
            return
        aspect = self.mouse.frame_aspect
        hit = det.step(t0, hand.landmarks, "", set(), aspect, scope="motion", posture=hand_posture(hand.landmarks, aspect))
        if hit is None:
            return
        name = str(hit.get("name") or hit["key"])
        self.motion._last_activity = t0                # a command ran: motion mode does not time out under it
        if self.paused:
            badge = str(reg.resolve_effective_action(hit["key"], {}).get("badge") or "")
            self._motion_last = f"시뮬레이션: {name}" + (f" → {badge}" if badge else "")
            self._say(f"모션: {self._motion_last} (실행 안 함)", 1.5)
            return
        self._log_composite_fire(hit, det)
        fg = self.mouse.foreground_info() if not self.mouse.dry_run else {}
        self._use_names[hit["key"]] = name
        ok, badge = self._run_resolved(reg, reg.resolve_effective_action(hit["key"], fg))
        self._motion_last = f"{name} → {badge}" if ok else f"{name}: {badge}"
        self._say(f"모션 모드 동작 [{name}] → {badge}", 1.5)

    def _motion_would(self, action: str, target_key: str, by_key) -> str:
        """What a motion-mode swipe would run: the command connected to it on the action screen, else its built-in key."""
        try:
            resolved = get_action_registry().resolve_effective_action(target_key, {})
            if resolved.get("action_type") not in (None, "none") and resolved.get("badge"):
                name = by_key[target_key].name if target_key in by_key else ACTION_LABELS.get(action, action)
                return f"{name.split(' (')[0]} → {resolved['badge']}"
        except Exception:
            pass
        return ACTION_LABELS.get(action) or (by_key[target_key].name if target_key in by_key else action)

    def _gesture_fields(self, t0, index_mode, result, frame_out) -> Dict[str, Any]:
        """Click / drag state of this frame, so a misfired click or drag can be read back afterwards."""
        action = (frame_out.action if (index_mode and frame_out is not None) else getattr(result, "action", None))
        g = self.engine
        since = getattr(g, "_secondary_since", {}) or {}
        held = {f: round((t0 - v) * 1000) for f, v in since.items()}
        d = getattr(result, "distances", None) or {}
        fields: Dict[str, Any] = {
            "act": action if action not in (None, "none") else None,
            "gest": getattr(result, "active_gesture", None) if not index_mode else None,
            "held_ms": held or None,
            "long": bool(getattr(g, "_long_fired", {}).get("middle")) or None,
            "browse": (list(self.mouse.browse_target) if getattr(self.mouse, "_browse_centered", False)
                       and self.mouse.browse_target else None),   # browsing: [x, y, "region:..."|"window:..."] it is centred on
            "dk": getattr(g, "last_desktop", None),            # show-desktop posture: tuck, hold, activity
            "motion": True if self.motion.active else None,
            "mo_miss": self.motion.last_miss if self.motion.active else None,   # biggest refused stroke and why
            "sign": [self.close_sign.last_pose, round(self.close_sign.progress(t0), 2), round(self.toggle_sign.progress(t0), 2)],   # rock sign pose?, its hold progress, V sign progress
            "pk": getattr(g, "last_pinky", None),               # thumb+pinky acceptance conditions
            "hold": getattr(g, "last_hold", None),   # thumb+index: (hold dist, release thr, tip dist)
            "d": {k: round(float(v), 3) for k, v in d.items()} if isinstance(d, dict) and d else None,
            "click_style": ui_style(self.ui) if index_mode else None,
            "clutch_state": getattr(self.mouse, "clutch_state", "inactive"),
            "return_state": getattr(self.mouse, "return_state", "none"),
            "hand_shape_mode": getattr(result, "hand_shape_mode", "normal") if not index_mode else None,
        }
        # Win+D fired: keep the seconds before it (a firing used to leave no record unless another event was near)
        if action == "show_desktop":
            if self.failures.trigger(t0, "desktop", note=json.dumps(getattr(g, "last_desktop", None))):
                self._say("기록: 바탕화면 보기")
        # a right / left click fired: keep the seconds before it too (a false click used to leave no record)
        if action in ("right_click", "left_click") and not self.paused:
            if self.failures.trigger(t0, "click", note=f"{action} {json.dumps(d, ensure_ascii=False) if isinstance(d, dict) else ''}"):
                self._say("기록: 클릭")
        # a drag starting (button down) is an event worth keeping with the seconds before it
        dragging = action == "drag_hold"
        if dragging and not self._was_dragging and not self.paused:
            if self.failures.trigger(t0, "drag_started", note=f"held_ms={held}"):
                self._say("기록: 드래그 시작")
        # a drag ending: keep the last seconds too (a stroke longer than the 3 s before drag_started was lost)
        if dragging and not self._was_dragging:
            self._drag_began = t0
        if self._was_dragging and not dragging and not self.paused and t0 - getattr(self, "_drag_began", t0) >= 0.3:
            if self.failures.trigger(t0, "drag_ended", note=f"seconds={t0 - self._drag_began:.2f}"):
                self._say("기록: 드래그 끝", 1.0)
        self._was_dragging = dragging
        # scroll inertia: keep the numbers of every launch / refusal (raw vs used speed, axis, directions)
        li = getattr(self.mouse, "last_inertia", None)
        if li is not None and li is not self._seen_inertia:
            self._seen_inertia = li
            fields["inertia"] = li
            if self.failures.trigger(t0, "inertia", note=json.dumps(li)):
                self._say("기록: 관성 스크롤")
        fields["coast"] = bool(getattr(self.mouse, "scroll_coasting", False)) or None
        total = list(getattr(self.mouse, "scroll_total", [0, 0]))
        sent = [total[0] - self._last_scroll_total[0], total[1] - self._last_scroll_total[1]]
        self._last_scroll_total = total
        fields["wheel"] = sent if any(sent) else None          # units handed to the pump this frame
        pv, ph = getattr(self.mouse, "_pump", None).pending() if getattr(self.mouse, "_pump", None) else (0, 0)
        fields["wheel_pending"] = round(pv) if abs(pv) >= 1 else None
        return fields

    def _failures(self, t0, detections, roi, index_mode, ui, frame, result=None, frame_out=None) -> None:
        if not ui.calibrating:
            hand = detections[0] if detections else None
            kind = self.failures.record(
                t0, landmarks=hand.landmarks if hand else None, score=hand.score if hand else 0.0,
                moving=(self.pointer.latch.latched if index_mode else bool(getattr(result, "is_moving", False)))
                and not self.paused,
                crop=list(roi) if roi else None, cursor=list(self.mouse.last_screen_pos),
                speed=round(self.pointer.latch.speed, 3), mode="index" if index_mode else "palm",
                **self._gesture_fields(t0, index_mode, result, frame_out),
                brightness=self._metrics[1] if self._metrics else None,
                fps=round(self.camera.fps, 1), detect_ms=round(self.tracker.last_detect_ms, 1), paused=self.paused,
                path=self._det_path, raw=self._raw_hands, latched=bool(self.pointer.latch.latched),
                armed=bool(self.pointer.click_armed), trig=self.pointer.trigger.state,
                dropped=self.camera.dropped_frames, dt_ms=round((t0 - self._last_step_t) * 1000, 1)
                if self._last_step_t else None,
            )
            if kind:
                self._say(f"실패 기록: {kind}")
        saved = self.failures.poll(t0, {
            "anchor": ui.anchor, "anchor_joints": list(ui.anchor_joints), "click_style": ui.click_style, "hand_crop": ui.hand_crop,
            "frame_px": [frame.shape[1], frame.shape[0]], "camera_mode": list(self.camera.actual_mode() or ()),
            "tracker": self.tracker.options, "sensitivity_pct": ui.sensitivity,
            "control_hand": ui.control_hand, "dry_run": self.dry_run,
            "camera_source": str(self.camera.config.source), "mirror": bool(self.camera.config.mirror),
            "crop_params": {**{k: getattr(self.hand_crop, k) for k in ("scale", "min_px", "recenter", "resize", "max_hand_frac",
                                                                       "search_seconds", "collapse_ratio")},
                            "tracker": self.roi_tracker.kind, "track_seconds": self.roi_tracker.seconds},
            "config": {k: v for k, v in self.engine.config.items() if isinstance(v, (int, float, str, bool))},
        })
        if saved is not None:
            self._pending_failures = (self.failures.summary_text(), saved.name)
            self._pending_message = f"[Failure] saved {saved}"

    def _tracking(self, t0, detections, index_mode, ui) -> Optional[Dict[str, Any]]:
        test = self.test
        if test is None:
            return None
        pos = self.mouse.last_screen_pos
        test.update(
            t0, pos,
            hand=bool(detections),
            active=(index_mode or True) and not self.paused and not ui.calibrating,
            fps=self.camera.fps,
            detect_ms=self.tracker.last_detect_ms,
            clutch_state=getattr(self.mouse, "clutch_state", "inactive"),
            return_state=getattr(self.mouse, "return_state", "none"),
            hand_shape_mode=getattr(self.engine, "_shape_mode", "normal"),
        )
        if test.done and not getattr(test, "saved", False):
            test.saved = True
            primary = self.mouse.screens.primary
            scheme = str(self.engine.config.get("movement_scheme", "legacy_shape"))
            ret_supp = str(self.engine.config.get("return_suppression", "off"))
            run = {
                "anchor": ui.anchor, "anchor_joints": list(ui.anchor_joints), "sensitivity_pct": ui.sensitivity,
                "movement_scheme": scheme, "return_suppression": ret_supp,
                "condition": f"{scheme}+{ret_supp}",
                "direction_calibrated": ui.axes is not None, "control_hand": ui.control_hand,
                "camera_source": self.camera.config.source, "monitor_px": f"{primary.width}x{primary.height}",
                "monitors": len(self.mouse.screens), "dry_run": self.dry_run,
                "camera_mode": "x".join(map(str, self.camera.actual_mode() or ())) or "unknown",
                "hand_crop": ui.hand_crop,
                **{f"tracker_{k}": v for k, v in self.tracker.options.items()},
            }
            text = test.summary_text()
            try:
                saved = test.save_csv(self.log_dir, run)
                text += f" · {saved.name}"
            except OSError as exc:
                text += f" · 저장 실패: {exc}"
            test.result_text = text
            self._pending_recent = result_line({**run, **test.summary()}, time.strftime("%m/%d %H:%M"))
            self._pending_message = f"[Tracking] {text}"
        view = tracking_view(test, pos)
        if test.done:
            view["summary"] = getattr(test, "result_text", view["summary"])
        return view
