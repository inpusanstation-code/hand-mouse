"""The production online model as the mouse's safety gate (online-learning plan, section 10).

It reuses the app's intent checker (GestureGate): a click or the start of a scroll/drag that the rule engine proposes goes through only when
the model has seen the same gesture for k frames in a row above its threshold, the hand is tracked well, and (for risky gestures) it was held.
On top of that, for this model: a clear winner (top-1 minus top-2), and nothing passes for a moment after the model was swapped.
Pointer movement is not gated; gestures the model does not know keep their rule behaviour (as with the existing checker).

Taught gestures (2026-11-11): each has its own small checking model on this model's embedding (src/online/verifier.py). Their
probabilities are appended after the model's classes, under the gesture's key, so `confirmed(key, now)` answers for them too:
the verifier's own threshold, FRAMES windows in a row, no "clear winner" test (a verifier is not one of the softmax classes).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

from src.gesture_gate import GestureGate

MARGIN = .2              # top-1 minus top-2 probability
SWAP_BLOCK_SECONDS = 1.0


class OnlineGate(GestureGate):
    def __init__(self, root: Path | str, config: Optional[Dict[str, Any]] = None, *, margin: float = MARGIN,
                 swap_block: float = SWAP_BLOCK_SECONDS, predictor: Any = None, verifiers: Optional[Dict[str, Any]] = None) -> None:
        if predictor is None:
            from src.online.app_job import ProductionPredictor
            predictor = ProductionPredictor(root)
        import torch
        # One thread: this tiny model runs every camera frame. With torch's default (20 threads on this PC) the camera loop
        # had spikes up to 100 ms (99 % 20.0 -> 14.8 ms, max 99.6 -> 19.4 ms with one), and those threads compete with the
        # hand detector. Training runs in its own process and is not affected.
        try:
            torch.set_num_threads(1)
        except Exception:
            pass
        model = predictor.model
        if verifiers is None:
            try:
                from src.online.verifier import encoder_fingerprint, load_verifiers
                verifiers = load_verifiers(root, encoder_fingerprint(model.state_dict()))
            except Exception:
                verifiers = {}                     # a model without an embedding, or unreadable files: no taught gestures
        self.verifiers: Dict[str, Any] = {k: v for k, v in verifiers.items() if k not in predictor.classes}
        self.base_classes = len(predictor.classes)
        taught = list(self.verifiers.values())
        # a checking model may look further back than the encoder's window (verifier.LAG_OPTIONS): the embeddings of
        # the last frames are kept for it. Until that history is there it answers 0 (the first seconds after a start).
        from collections import deque
        reach = max((max(getattr(v, "lags", ()) or (0,)) for v in taught), default=0)
        past: Any = deque(maxlen=reach + 1)

        def taught_prob(v: Any, e: np.ndarray) -> float:
            lags = tuple(getattr(v, "lags", ()) or ())
            if not lags:
                return float(v.prob(e)[0])
            if len(past) <= max(lags):
                return 0.0
            return float(v.prob(np.concatenate([e] + [past[-1 - lag] for lag in lags], axis=1))[0])

        def predict(x: np.ndarray) -> np.ndarray:
            with torch.no_grad():
                t = torch.from_numpy(np.ascontiguousarray(x, dtype=np.float32))
                if not taught:
                    return torch.softmax(model(t), 1).numpy()[0]
                emb = model.embed(t)
                probs = torch.softmax(model.head(emb), 1).numpy()[0]
                e = emb.numpy()
                past.append(e)
                return np.concatenate([probs, [taught_prob(v, e) for v in taught]])

        info = {"classes": list(predictor.classes) + list(self.verifiers), "window": predictor.window, "threshold": .7,
                "frames_in_a_row": 3}
        super().__init__(predict, info, {**(config or {}), "spatial_mlp_enabled": False})
        from src.online.verifier import FRAMES
        for key, verifier in self.verifiers.items():
            self.thresholds[key] = float(verifier.threshold)
            self.frame_counts[key] = FRAMES
            self.hold_seconds[key] = 0.0
        self.margin, self.swap_block = margin, swap_block
        self.blocked_until: Optional[float] = None
        self.model_loaded = getattr(predictor, "loaded", time.time())

    def step(self, now: float, hand: Any, aspect: float):
        if self.blocked_until is None:
            self.blocked_until = now + self.swap_block      # just swapped in: its first frames have no history yet
        return super().step(now, hand, aspect)

    def _clear_winner(self) -> bool:
        p = self.last
        if p is None or len(p) < 2:
            return False
        top = np.sort(np.asarray(p)[:self.base_classes])[::-1]
        return float(top[0] - top[1]) >= self.margin

    def confirmed(self, name: str, now: float) -> bool:
        if self.blocked_until is None or now < self.blocked_until:
            self.last_rejection_reason = "model_swap"
            return False
        if not super().confirmed(name, now):
            return False
        if name not in self.verifiers and not self._clear_winner():
            self.last_rejection_reason = "close_call"
            return False
        return True

    def rejection_reason_ko(self) -> str:
        if self.last_rejection_reason == "model_swap":
            return "모델을 막 바꿔서 잠시 보류"
        if self.last_rejection_reason == "close_call":
            return "두 동작 사이에서 확실하지 않음"
        return super().rejection_reason_ko()
