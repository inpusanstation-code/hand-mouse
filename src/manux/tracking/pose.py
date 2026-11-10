"""Optional measured body landmarks, port of Dan b3c3025 PoseTracker. Lazy vision imports.

`detect_all` gives the whole 33-point skeleton (head, arms, hips, legs; `tracking.body`, preview);
`detect` gives the six arm points that recordings store (contracts section 9, unchanged).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

MODEL_SHA256 = "59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a"   # Lite: recordings (contracts section 9)
FULL_SHA256 = "5134a3aad27a58b93da0088d431f366da362b44e3ccfbe3462b3827a839011b1"    # Full: body skeleton (tracking.body)
KNOWN_SHA256 = (MODEL_SHA256, FULL_SHA256)
ARM = (11, 12, 13, 14, 15, 16)


def arm(points):
    """The recorded six arm points of a 33-point Pose (or None)."""
    return tuple(points[i] for i in ARM) if points else None


class PoseTracker:
    def __init__(self, path: Path):
        data = Path(path).read_bytes()
        if hashlib.sha256(data).hexdigest() not in KNOWN_SHA256:
            raise ValueError("Pose model checksum differs")
        import mediapipe as mp
        self.mp = mp
        self.landmarker = mp.tasks.vision.PoseLandmarker.create_from_options(mp.tasks.vision.PoseLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_buffer=data),
            running_mode=mp.tasks.vision.RunningMode.VIDEO, num_poses=1,
            min_pose_detection_confidence=.5, min_pose_presence_confidence=.5, min_tracking_confidence=.5))
        self.last_ms = 0

    def detect(self, image, now):
        """Shoulders, elbows, wrists as (x, y, visibility), or None."""
        return arm(self.detect_all(image, now))

    def detect_all(self, image, now):
        """All 33 Pose points (head 0-10, arms 11-22, hips and legs 23-32) as (x, y, visibility), or None."""
        import cv2
        h, w = image.shape[:2]
        if w > 640: image = cv2.resize(image, (640, max(1, round(h * 640 / w))))
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        timestamp = max(self.last_ms + 1, int(now * 1000))
        self.last_ms = timestamp
        result = self.landmarker.detect_for_video(self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb), timestamp)
        if not result.pose_landmarks: return None
        return tuple((float(p.x), float(p.y), float(p.visibility or 0)) for p in result.pose_landmarks[0])

    def close(self): self.landmarker.close()
