"""
MediaPipe Hand Landmarker Wrapper (Tasks Vision API)
Detects 21 3D hand landmarks in real time and draws visual skeletons & pinch indicators.
"""

from __future__ import annotations

import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import cv2
import mediapipe as mp
import numpy as np

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/latest/hand_landmarker.task"
)
DEFAULT_MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "hand_landmarker.task"

# Standard MediaPipe 21 hand landmark connections
HAND_CONNECTIONS: List[Tuple[int, int]] = [
    (0, 1), (1, 2), (2, 3), (3, 4),        # Thumb
    (0, 5), (5, 6), (6, 7), (7, 8),        # Index
    (5, 9), (9, 10), (10, 11), (11, 12),   # Middle
    (9, 13), (13, 14), (14, 15), (15, 16), # Ring
    (13, 17), (0, 17), (17, 18), (18, 19), (19, 20), # Pinky & Palm
]


@dataclass
class HandLandmark:
    x: float
    y: float
    z: float = 0.0


@dataclass
class HandDetection:
    landmarks: List[HandLandmark]
    handedness: str  # "Left" or "Right"
    score: float


def ensure_model_exists(model_path: Path = DEFAULT_MODEL_PATH) -> Path:
    """Ensure the MediaPipe hand_landmarker.task model exists locally; download if missing."""
    model_path.parent.mkdir(parents=True, exist_ok=True)
    if not model_path.exists() or model_path.stat().st_size < 100_000:
        print(f"[HandTracker] Downloading MediaPipe model to {model_path} ...")
        urllib.request.urlretrieve(MODEL_URL, str(model_path))
    return model_path


class HandTracker:
    """Real-time hand tracker built on Google MediaPipe Tasks Vision API."""

    def __init__(
        self,
        model_path: Optional[Path] = None,
        num_hands: int = 1,
        min_detection_confidence: float = 0.6,
        min_presence_confidence: float = 0.6,
        min_tracking_confidence: float = 0.6,
    ) -> None:
        resolved_model = ensure_model_exists(model_path or DEFAULT_MODEL_PATH)

        BaseOptions = mp.tasks.BaseOptions
        HandLandmarker = mp.tasks.vision.HandLandmarker
        HandLandmarkerOptions = mp.tasks.vision.HandLandmarkerOptions
        VisionRunningMode = mp.tasks.vision.RunningMode

        options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(resolved_model)),
            running_mode=VisionRunningMode.VIDEO,
            num_hands=num_hands,
            min_hand_detection_confidence=min_detection_confidence,
            min_hand_presence_confidence=min_presence_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        self._landmarker = HandLandmarker.create_from_options(options)
        self._last_timestamp_ms: int = 0

    def detect(self, frame_bgr: np.ndarray) -> List[HandDetection]:
        """Detect hands in a BGR frame and return 21 normalized landmarks per hand."""
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)

        timestamp_ms = int(time.perf_counter() * 1000)
        if timestamp_ms <= self._last_timestamp_ms:
            timestamp_ms = self._last_timestamp_ms + 1
        self._last_timestamp_ms = timestamp_ms

        result = self._landmarker.detect_for_video(mp_image, timestamp_ms)
        detections: List[HandDetection] = []

        if not result.hand_landmarks:
            return detections

        for idx, hand_lms in enumerate(result.hand_landmarks):
            landmarks = [HandLandmark(x=lm.x, y=lm.y, z=lm.z) for lm in hand_lms]
            handedness = "Right"
            score = 1.0
            if result.handedness and idx < len(result.handedness) and result.handedness[idx]:
                handedness = result.handedness[idx][0].category_name or "Right"
                score = float(result.handedness[idx][0].score or 1.0)
            detections.append(HandDetection(landmarks=landmarks, handedness=handedness, score=score))

        return detections

    @staticmethod
    def draw_hand(
        frame: np.ndarray,
        landmarks: Sequence[HandLandmark],
        is_pinched: bool = False,
        active_action: str = "none",
    ) -> None:
        """Draw hand skeleton, joints, and highlight thumb-index pinch interaction."""
        h, w = frame.shape[:2]
        pts = [(int(lm.x * w), int(lm.y * h)) for lm in landmarks]

        # Draw connections
        line_color = (0, 230, 118) if is_pinched else (220, 220, 220)
        for i, j in HAND_CONNECTIONS:
            cv2.line(frame, pts[i], pts[j], line_color, 2, cv2.LINE_AA)

        # Draw all joints
        for idx, (px, py) in enumerate(pts):
            if idx in (4, 8):
                continue
            cv2.circle(frame, (px, py), 4, (255, 180, 0), -1, cv2.LINE_AA)

        # Highlight Thumb Tip (#4) and Index Tip (#8)
        thumb_pt = pts[4]
        index_pt = pts[8]
        mid_pt = ((thumb_pt[0] + index_pt[0]) // 2, (thumb_pt[1] + index_pt[1]) // 2)

        pinch_color = (0, 255, 0) if is_pinched else (0, 140, 255)
        if active_action in ("left_click", "right_click", "drag_hold", "drag_toggle"):
            pinch_color = (0, 60, 255)

        cv2.circle(frame, thumb_pt, 8, pinch_color, -1, cv2.LINE_AA)
        cv2.circle(frame, index_pt, 8, pinch_color, -1, cv2.LINE_AA)
        cv2.line(frame, thumb_pt, index_pt, pinch_color, 2, cv2.LINE_AA)

        if is_pinched:
            cv2.circle(frame, mid_pt, 12, (0, 255, 128), 2, cv2.LINE_AA)
            cv2.circle(frame, mid_pt, 5, (0, 255, 128), -1, cv2.LINE_AA)

    def close(self) -> None:
        if self._landmarker is not None:
            self._landmarker.close()
            self._landmarker = None
