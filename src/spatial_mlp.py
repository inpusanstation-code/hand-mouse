"""Lightweight Spatial MLP (Multi-Layer Perceptron) classifier & fast trainer.

Designed for instantaneous single-frame posture classification (`window = 1`, 0-frame lag)
in pure NumPy without requiring PyTorch or ONNX runtime overhead.
Plugs directly into `GestureGate` as a 0-lag posture guard and hybrid ensemble partner with TCN.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from src.spatial_features import SPATIAL_FEATURES, SPATIAL_FEATURE_VERSION, extract_spatial_features

DEFAULT_SPATIAL_MLP_PATH = Path(__file__).resolve().parents[1] / "models" / "spatial_mlp.json"

STUDIO_CLASSES: Tuple[str, ...] = (
    "none",
    "thumb_middle",
    "thumb_ring",
    "thumb_index",
    "thumb_pinky",
    "palm_side",
    "thumbs_up",
    "v_sign",
)

# Static / pinch / sign postures where single-frame 96-dim geometry is highly discriminative
STATIC_POSTURE_LABELS = frozenset({
    "none",
    "thumb_index",
    "thumb_middle",
    "thumb_ring",
    "thumb_pinky",
    "thumb_index_middle",
    "palm_side",
    "v_sign",
    "rock_sign",
    "thumbs_up",
})


@dataclass(frozen=True)
class SpatialMlpMetrics:
    train_accuracy: float
    test_accuracy: float
    total_samples: int
    train_samples: int
    test_samples: int
    elapsed_ms: float
    per_class: Mapping[str, Mapping[str, Any]]
    trained_at: str


class SpatialMlpModel:
    """2-Layer Spatial MLP (`feat_dim -> hidden_units -> num_classes`) with LeakyReLU(0.05) + Softmax,
    plus optional per-gesture binary specialist MLPs (`self.specialists[label]`).
    """

    def __init__(
        self,
        w1: np.ndarray,
        b1: np.ndarray,
        w2: np.ndarray,
        b2: np.ndarray,
        classes: Sequence[str] = STUDIO_CLASSES,
        feature_version: str = SPATIAL_FEATURE_VERSION,
        metadata: Optional[Mapping[str, Any]] = None,
        specialists: Optional[Mapping[str, SpatialMlpModel]] = None,
    ) -> None:
        self.w1 = np.asarray(w1, dtype=np.float64)  # (H, D)
        self.b1 = np.asarray(b1, dtype=np.float64)  # (H,)
        self.w2 = np.asarray(w2, dtype=np.float64)  # (C_base, H)
        self.b2 = np.asarray(b2, dtype=np.float64)  # (C_base,)
        self.base_classes: Tuple[str, ...] = tuple(classes)
        self.specialists: Dict[str, SpatialMlpModel] = {}
        merged_classes = list(self.base_classes)
        if specialists:
            for lbl, spec in specialists.items():
                if isinstance(spec, SpatialMlpModel) and lbl != "none":
                    self.specialists[str(lbl)] = spec
                    if str(lbl) not in merged_classes:
                        merged_classes.append(str(lbl))
        self.classes: Tuple[str, ...] = tuple(merged_classes)
        self.feature_version = feature_version
        self.metadata: Dict[str, Any] = dict(metadata or {})

    @property
    def feat_dim(self) -> int:
        return int(self.w1.shape[1])

    @property
    def hidden_units(self) -> int:
        return int(self.w1.shape[0])

    def _predict_base_proba(self, x_2d: np.ndarray) -> np.ndarray:
        z1 = x_2d @ self.w1.T + self.b1
        h = np.where(z1 > 0.0, z1, z1 * 0.05)
        logits = h @ self.w2.T + self.b2
        logits = logits - np.max(logits, axis=1, keepdims=True)
        exp_logits = np.exp(logits)
        return exp_logits / np.sum(exp_logits, axis=1, keepdims=True)

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        """Single feature vector `(D,)` or batch `(N, D)` -> probabilities `(C,)` or `(N, C)`."""
        x = np.asarray(features, dtype=np.float64)
        single = x.ndim == 1
        if single:
            x = x[None, :]
        base_probs = self._predict_base_proba(x)
        if not self.specialists:
            return base_probs[0] if single else base_probs

        n_rows = x.shape[0]
        probs = np.zeros((n_rows, len(self.classes)), dtype=np.float64)
        probs[:, : len(self.base_classes)] = base_probs

        for label, spec_model in self.specialists.items():
            if label == "none" or label not in self.classes:
                continue
            ci = self.classes.index(label)
            spec_out = spec_model._predict_base_proba(x)
            if spec_out.shape[1] < 2:
                continue
            spec_pos = spec_out[:, 1]
            is_independent = bool(spec_model.metadata.get("independent")) or (ci >= len(self.base_classes))
            if is_independent:
                probs[:, ci] = spec_pos
            else:
                base_p = probs[:, ci]
                blended = 0.35 * base_p + 0.65 * spec_pos
                # Suppress competing-finger false positives when the binary specialist rejects the gesture
                veto_mask = (spec_pos < 0.18) & (base_p < 0.80)
                blended = np.where(veto_mask, blended * 0.35, blended)
                probs[:, ci] = blended

        if "none" in self.classes:
            none_idx = self.classes.index("none")
            other_indices = [i for i, name in enumerate(self.classes) if name != "none"]
            if other_indices:
                max_other = np.max(probs[:, other_indices], axis=1)
                probs[:, none_idx] = np.clip(1.0 - max_other, 0.0, 1.0)
        row_sum = np.sum(probs, axis=1, keepdims=True)
        probs = np.where(row_sum > 1e-8, probs / row_sum, probs)
        return probs[0] if single else probs

    def predict(self, features: np.ndarray) -> Dict[str, Any]:
        """Predict top class, confidence, and probability map for a single frame `(D,)`."""
        probs = self.predict_proba(features)
        best_idx = int(np.argmax(probs))
        return {
            "action": self.classes[best_idx],
            "confidence": float(probs[best_idx]),
            "probabilities": {cls: float(probs[i]) for i, cls in enumerate(self.classes)},
        }

    def __call__(self, window: np.ndarray) -> np.ndarray:
        """Accepts `(D,)`, `(W, D)`, or `(1, W, D)` and predicts on the latest frame."""
        arr = np.asarray(window, dtype=np.float64)
        if arr.ndim == 3:
            arr = arr[0, -1]
        elif arr.ndim == 2:
            arr = arr[-1]
        return self.predict_proba(arr)

    def to_dict(self) -> Dict[str, Any]:
        doc: Dict[str, Any] = {
            "schema": "manux-spatial-mlp/1",
            "feature_version": self.feature_version,
            "feat_dim": self.feat_dim,
            "hidden_units": self.hidden_units,
            "classes": list(self.base_classes),
            "metadata": self.metadata,
            "weights": {
                "W1": np.round(self.w1, 6).tolist(),
                "b1": np.round(self.b1, 6).tolist(),
                "W2": np.round(self.w2, 6).tolist(),
                "b2": np.round(self.b2, 6).tolist(),
            },
        }
        if self.specialists:
            doc["specialists"] = {
                lbl: spec.to_dict() for lbl, spec in self.specialists.items()
            }
        return doc

    def save(self, path: Path = DEFAULT_SPATIAL_MLP_PATH) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @classmethod
    def from_dict(cls, doc: Mapping[str, Any]) -> SpatialMlpModel:
        if not isinstance(doc, Mapping) or doc.get("schema") != "manux-spatial-mlp/1":
            raise ValueError("invalid spatial MLP document")
        weights = doc["weights"]
        raw_specs = doc.get("specialists") or {}
        parsed_specs: Dict[str, SpatialMlpModel] = {}
        if isinstance(raw_specs, Mapping):
            for lbl, sdoc in raw_specs.items():
                if isinstance(sdoc, Mapping) and sdoc.get("schema") == "manux-spatial-mlp/1":
                    try:
                        parsed_specs[str(lbl)] = cls.from_dict(sdoc)
                    except Exception:
                        pass
        return cls(
            w1=np.asarray(weights["W1"], dtype=np.float64),
            b1=np.asarray(weights["b1"], dtype=np.float64),
            w2=np.asarray(weights["W2"], dtype=np.float64),
            b2=np.asarray(weights["b2"], dtype=np.float64),
            classes=tuple(doc["classes"]),
            feature_version=str(doc.get("feature_version", SPATIAL_FEATURE_VERSION)),
            metadata=dict(doc.get("metadata") or {}),
            specialists=parsed_specs,
        )

    @classmethod
    def load(cls, path: Path = DEFAULT_SPATIAL_MLP_PATH) -> SpatialMlpModel:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(doc)


def train_binary_spatial_specialist(
    x_all: np.ndarray,
    y_all: np.ndarray,
    classes: Sequence[str],
    target_label: str,
    *,
    hidden_units: int = 48,
    epochs: int = 45,
    batch_size: int = 128,
    lr: float = 0.003,
    l2: float = 1e-4,
    seed: int = 42,
    hard_negative_weight: float = 1.65,
    independent: bool = False,
    feature_version: str = SPATIAL_FEATURE_VERSION,
    device: Optional[str] = None,
) -> Tuple[SpatialMlpModel, SpatialMlpMetrics]:
    """Train a dedicated binary Spatial MLP (`['none', target_label]`) for a single gesture.

    Competing gesture postures (`label != 'none'` and `label != target_label`) receive
    `hard_negative_weight` so adjacent finger pinches are sharply separated.
    """
    cls_list = list(classes)
    if target_label not in cls_list or target_label == "none":
        raise ValueError(f"유효하지 않은 대상 동작: {target_label}")
    target_idx = cls_list.index(target_label)
    none_idx = cls_list.index("none") if "none" in cls_list else -1

    y_orig = np.asarray(y_all, dtype=np.int64)
    y_bin = (y_orig == target_idx).astype(np.int64)

    counts = np.bincount(y_bin, minlength=2).astype(np.float64)
    cls_w = (counts.sum() / np.maximum(counts, 1.0)) ** 0.5
    cls_w = cls_w / np.maximum(cls_w.mean(), 1e-8)
    sample_weights = cls_w[y_bin].copy()

    # Emphasize competing non-neutral gestures as hard negatives
    competing_mask = (y_orig != target_idx) & (y_orig != none_idx) & (y_orig >= 0)
    if np.any(competing_mask):
        sample_weights[competing_mask] *= float(hard_negative_weight)

    spec_model, spec_metrics = train_spatial_mlp(
        x_all,
        y_bin,
        weights_all=sample_weights,
        classes=("none", target_label),
        hidden_units=hidden_units,
        epochs=epochs,
        batch_size=batch_size,
        lr=lr,
        l2=l2,
        seed=seed,
        class_balance=False,
        feature_version=feature_version,
        device=device,
        train_specialists=False,
    )
    spec_model.metadata["target"] = target_label
    spec_model.metadata["model_kind"] = "spatial_binary_specialist"
    spec_model.metadata["independent"] = bool(independent)
    return spec_model, spec_metrics


def train_spatial_mlp(
    x_all: np.ndarray,
    y_all: np.ndarray,
    weights_all: Optional[np.ndarray] = None,
    *,
    classes: Sequence[str] = STUDIO_CLASSES,
    hidden_units: int = 64,
    epochs: int = 45,
    batch_size: int = 128,
    lr: float = 0.003,
    l2: float = 1e-4,
    seed: int = 42,
    class_balance: bool = True,
    feature_version: str = SPATIAL_FEATURE_VERSION,
    device: Optional[str] = None,
    train_specialists: bool = True,
) -> Tuple[SpatialMlpModel, SpatialMlpMetrics]:
    """Train a 2-layer Spatial MLP + per-gesture binary specialist MLPs using CUDA or vectorized NumPy Adam."""
    t0 = time.perf_counter()
    x_arr = np.asarray(x_all, dtype=np.float64)
    y_arr = np.asarray(y_all, dtype=np.int64)
    n_samples, feat_dim = x_arr.shape
    num_classes = len(classes)
    if n_samples < 2:
        raise ValueError("학습하려면 최소 2개 이상의 표본이 필요합니다.")

    if weights_all is not None:
        sample_weights = np.asarray(weights_all, dtype=np.float64)
    elif class_balance:
        counts = np.bincount(y_arr, minlength=num_classes).astype(np.float64)
        cls_w = (counts.sum() / np.maximum(counts, 1.0)) ** 0.5
        cls_w = cls_w / np.maximum(cls_w.mean(), 1e-8)
        sample_weights = cls_w[y_arr]
    else:
        sample_weights = np.ones(n_samples, dtype=np.float64)

    rng = np.random.default_rng(seed)
    perm = rng.permutation(n_samples)
    x_arr = x_arr[perm]
    y_arr = y_arr[perm]
    sample_weights = sample_weights[perm]

    # 80/20 train/test split (if small dataset < 10, evaluate on all as well)
    if n_samples >= 10:
        split = max(1, min(n_samples - 1, int(n_samples * 0.8)))
        x_train, x_test = x_arr[:split], x_arr[split:]
        y_train, y_test = y_arr[:split], y_arr[split:]
        w_train = sample_weights[:split]
    else:
        x_train = x_test = x_arr
        y_train = y_test = y_arr
        w_train = sample_weights

    # He Initialization
    w1 = rng.standard_normal((hidden_units, feat_dim)) * math.sqrt(2.0 / feat_dim)
    b1 = np.full(hidden_units, 0.01, dtype=np.float64)
    w2 = rng.standard_normal((num_classes, hidden_units)) * math.sqrt(2.0 / hidden_units)
    b2 = np.zeros(num_classes, dtype=np.float64)

    n_train = len(x_train)
    req_dev = str(device or "auto").strip().lower()
    use_cuda = False
    if req_dev != "cpu":
        try:
            import torch
            if torch.cuda.is_available() and (req_dev in ("gpu", "cuda") or n_train >= 256):
                use_cuda = True
        except Exception:
            use_cuda = False

    if use_cuda:
        import torch
        t_dev = torch.device("cuda")
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)

        tw1 = torch.tensor(w1, dtype=torch.float32, device=t_dev, requires_grad=True)
        tb1 = torch.tensor(b1, dtype=torch.float32, device=t_dev, requires_grad=True)
        tw2 = torch.tensor(w2, dtype=torch.float32, device=t_dev, requires_grad=True)
        tb2 = torch.tensor(b2, dtype=torch.float32, device=t_dev, requires_grad=True)

        tx_train = torch.from_numpy(np.ascontiguousarray(x_train, dtype=np.float32)).to(t_dev)
        ty_train = torch.from_numpy(np.ascontiguousarray(y_train, dtype=np.int64)).to(t_dev)
        tw_train = torch.from_numpy(np.ascontiguousarray(w_train, dtype=np.float32)).to(t_dev)

        use_large_bs = n_train >= 4096 and batch_size <= 256
        eff_batch_size = 2048 if use_large_bs else min(batch_size, max(4, n_train // 8))
        eff_lr = lr * 1.5 if use_large_bs else lr
        opt = torch.optim.Adam([tw1, tb1, tw2, tb2], lr=eff_lr)

        for _ in range(max(1, epochs)):
            ep_perm = torch.randperm(n_train, device=t_dev)
            x_ep = tx_train[ep_perm]
            y_ep = ty_train[ep_perm]
            w_ep = tw_train[ep_perm]

            for b_start in range(0, n_train, eff_batch_size):
                xb = x_ep[b_start : b_start + eff_batch_size]
                yb = y_ep[b_start : b_start + eff_batch_size]
                wb = w_ep[b_start : b_start + eff_batch_size]

                opt.zero_grad(set_to_none=True)
                z1 = xb @ tw1.t() + tb1
                h = torch.nn.functional.leaky_relu(z1, negative_slope=0.05)
                logits = h @ tw2.t() + tb2
                per_sample = torch.nn.functional.cross_entropy(logits, yb, reduction="none")
                reg = 0.5 * l2 * (torch.sum(tw1 * tw1) + torch.sum(tw2 * tw2))
                loss = torch.mean(per_sample * wb) + reg
                loss.backward()
                opt.step()

        w1 = tw1.detach().cpu().numpy().astype(np.float64)
        b1 = tb1.detach().cpu().numpy().astype(np.float64)
        w2 = tw2.detach().cpu().numpy().astype(np.float64)
        b2 = tb2.detach().cpu().numpy().astype(np.float64)
    else:
        # Adam Optimizer State (Pure NumPy fallback)
        mw1, vw1 = np.zeros_like(w1), np.zeros_like(w1)
        mb1, vb1 = np.zeros_like(b1), np.zeros_like(b1)
        mw2, vw2 = np.zeros_like(w2), np.zeros_like(w2)
        mb2, vb2 = np.zeros_like(b2), np.zeros_like(b2)

        beta1, beta2, eps = 0.9, 0.999, 1e-8
        step = 0
        eff_batch_size = min(batch_size, max(4, n_train // 8))

        for _ in range(max(1, epochs)):
            ep_perm = rng.permutation(n_train)
            x_ep = x_train[ep_perm]
            y_ep = y_train[ep_perm]
            w_ep = w_train[ep_perm]

            for b_start in range(0, n_train, eff_batch_size):
                xb = x_ep[b_start : b_start + eff_batch_size]
                yb = y_ep[b_start : b_start + eff_batch_size]
                wb = w_ep[b_start : b_start + eff_batch_size]
                b_len = len(xb)
                step += 1

                # Forward pass (vectorized)
                z1 = xb @ w1.T + b1                              # (B, H)
                h = np.where(z1 > 0.0, z1, z1 * 0.05)            # (B, H)
                logits = h @ w2.T + b2                           # (B, C)
                logits = logits - np.max(logits, axis=1, keepdims=True)
                exp_l = np.exp(logits)
                probs = exp_l / np.sum(exp_l, axis=1, keepdims=True)  # (B, C)

                # Backward pass
                d_logits = probs.copy()
                d_logits[np.arange(b_len), yb] -= 1.0
                d_logits *= (wb[:, None] / b_len)                # (B, C)

                gw2 = d_logits.T @ h + l2 * w2                   # (C, H)
                gb2 = np.sum(d_logits, axis=0)                   # (C,)

                dh = d_logits @ w2                               # (B, H)
                dz1 = np.where(z1 > 0.0, dh, dh * 0.05)          # (B, H)
                gw1 = dz1.T @ xb + l2 * w1                       # (H, D)
                gb1 = np.sum(dz1, axis=0)                       # (H,)

                # Adam update
                b1_corr = 1.0 - beta1 ** step
                b2_corr = 1.0 - beta2 ** step

                mw1 = beta1 * mw1 + (1.0 - beta1) * gw1
                vw1 = beta2 * vw1 + (1.0 - beta2) * (gw1 * gw1)
                w1 -= lr * (mw1 / b1_corr) / (np.sqrt(vw1 / b2_corr) + eps)

                mb1 = beta1 * mb1 + (1.0 - beta1) * gb1
                vb1 = beta2 * vb1 + (1.0 - beta2) * (gb1 * gb1)
                b1 -= lr * (mb1 / b1_corr) / (np.sqrt(vb1 / b2_corr) + eps)

                mw2 = beta1 * mw2 + (1.0 - beta1) * gw2
                vw2 = beta2 * vw2 + (1.0 - beta2) * (gw2 * gw2)
                w2 -= lr * (mw2 / b1_corr) / (np.sqrt(vw2 / b2_corr) + eps)

                mb2 = beta1 * mb2 + (1.0 - beta1) * gb2
                vb2 = beta2 * vb2 + (1.0 - beta2) * (gb2 * gb2)
                b2 -= lr * (mb2 / b1_corr) / (np.sqrt(vb2 / b2_corr) + eps)

    spec_models: Dict[str, SpatialMlpModel] = {}
    spec_meta_summary: Dict[str, Any] = {}
    if train_specialists and num_classes > 2 and "none" in classes:
        spec_hidden = min(48, max(24, hidden_units))
        spec_epochs = max(20, int(epochs * 0.85))
        for c_idx, cls_name in enumerate(classes):
            if cls_name == "none":
                continue
            if int(np.sum(y_arr == c_idx)) < 1 or int(np.sum(y_arr != c_idx)) < 1:
                continue
            try:
                sp_spec, sp_spec_m = train_binary_spatial_specialist(
                    x_arr,
                    y_arr,
                    classes=classes,
                    target_label=cls_name,
                    hidden_units=spec_hidden,
                    epochs=spec_epochs,
                    batch_size=batch_size,
                    lr=lr,
                    l2=l2,
                    seed=seed + c_idx + 1,
                    independent=False,
                    feature_version=feature_version,
                    device=device,
                )
                spec_models[cls_name] = sp_spec
                spec_meta_summary[cls_name] = {
                    "hidden_units": sp_spec.hidden_units,
                    "train_accuracy": sp_spec_m.train_accuracy,
                    "test_accuracy": sp_spec_m.test_accuracy,
                }
            except Exception:
                pass

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    trained_at = time.strftime("%Y-%m-%d %H:%M:%S")

    temp_model = SpatialMlpModel(
        w1, b1, w2, b2,
        classes=classes,
        feature_version=feature_version,
        specialists=spec_models,
    )
    train_preds = np.argmax(temp_model.predict_proba(x_train), axis=1)
    test_preds = np.argmax(temp_model.predict_proba(x_test), axis=1)
    all_preds = np.argmax(temp_model.predict_proba(x_arr), axis=1)

    train_acc = float(np.mean(train_preds == y_train) * 100.0)
    test_acc = float(np.mean(test_preds == y_test) * 100.0)

    per_class: Dict[str, Dict[str, Any]] = {}
    for c_idx, cls_name in enumerate(classes):
        mask = y_arr == c_idx
        total_c = int(np.sum(mask))
        correct_c = int(np.sum(all_preds[mask] == c_idx)) if total_c > 0 else 0
        per_class[cls_name] = {
            "total": total_c,
            "correct": correct_c,
            "accuracy": round((correct_c / total_c) * 100.0, 1) if total_c > 0 else None,
        }

    metrics = SpatialMlpMetrics(
        train_accuracy=round(train_acc, 2),
        test_accuracy=round(test_acc, 2),
        total_samples=int(n_samples),
        train_samples=int(len(x_train)),
        test_samples=int(len(x_test)),
        elapsed_ms=round(elapsed_ms, 1),
        per_class=per_class,
        trained_at=trained_at,
    )

    model = SpatialMlpModel(
        w1, b1, w2, b2,
        classes=classes,
        feature_version=feature_version,
        metadata={
            "train_accuracy": metrics.train_accuracy,
            "test_accuracy": metrics.test_accuracy,
            "total_samples": metrics.total_samples,
            "elapsed_ms": metrics.elapsed_ms,
            "per_class": per_class,
            "specialists": spec_meta_summary,
            "trained_at": trained_at,
        },
        specialists=spec_models,
    )
    return model, metrics


def compose_spatial_mlp(
    model_path: Path,
    base_spatial: Optional[SpatialMlpModel] = None,
) -> Optional[SpatialMlpModel]:
    """Compose `base_spatial` (`models/spatial_mlp.json`) with per-gesture specialist MLPs in `models/gestures/`."""
    model_path = Path(model_path)
    if base_spatial is None:
        sp_candidate = model_path.parent / "spatial_mlp.json"
        if sp_candidate.is_file():
            try:
                base_spatial = SpatialMlpModel.load(sp_candidate)
            except Exception:
                base_spatial = None

    bank_dir = model_path.parent / "gestures"
    bank_specs: Dict[str, SpatialMlpModel] = {}
    if (bank_dir / "manifest.json").is_file():
        try:
            from src.gesture_models import read_bank
            entries = read_bank(bank_dir)
            for label, entry in entries.items():
                card_path = bank_dir / entry["card"]
                if not card_path.is_file():
                    continue
                card_doc = json.loads(card_path.read_text(encoding="utf-8"))
                sp_doc = card_doc.get("spatial_mlp")
                if isinstance(sp_doc, Mapping) and sp_doc.get("schema") == "manux-spatial-mlp/1":
                    spec_m = SpatialMlpModel.from_dict(sp_doc)
                    spec_m.metadata["independent"] = True
                    spec_m.metadata["target"] = label
                    bank_specs[label] = spec_m
        except Exception:
            pass

    if base_spatial is None and not bank_specs:
        return None

    if base_spatial is None:
        # Build a neutral base wrapper so the bank specialists can still run independently
        first_spec = next(iter(bank_specs.values()))
        f_dim = first_spec.feat_dim
        h_dim = first_spec.hidden_units
        w1 = np.zeros((h_dim, f_dim), dtype=np.float64)
        b1 = np.zeros(h_dim, dtype=np.float64)
        w2 = np.zeros((1, h_dim), dtype=np.float64)
        b2 = np.array([1.0], dtype=np.float64)
        return SpatialMlpModel(
            w1, b1, w2, b2,
            classes=("none",),
            feature_version=first_spec.feature_version,
            metadata={"composed_from_bank": True},
            specialists=bank_specs,
        )

    if not bank_specs:
        return base_spatial

    merged_specs = dict(base_spatial.specialists)
    merged_specs.update(bank_specs)
    return SpatialMlpModel(
        base_spatial.w1.copy(),
        base_spatial.b1.copy(),
        base_spatial.w2.copy(),
        base_spatial.b2.copy(),
        classes=base_spatial.base_classes,
        feature_version=base_spatial.feature_version,
        metadata={
            **base_spatial.metadata,
            "independent_spatial_gestures": sorted(bank_specs.keys()),
        },
        specialists=merged_specs,
    )


def ensure_session_spatial_features(session: Dict[str, Any]) -> np.ndarray:
    """Attach and return `(N, 96)` `spatial_features` on a session dict loaded by `capture_dataset`."""
    if "spatial_features" in session and isinstance(session["spatial_features"], np.ndarray):
        return session["spatial_features"]
    frames = session.get("frames") or []
    n = len(frames)
    s_feats = np.zeros((n, SPATIAL_FEATURES), dtype=np.float32)
    # If frames were slimmed in disk cache, reload raw landmarks from session["path"] if available
    need_reload = n > 0 and "lm" not in frames[0] and "world" not in frames[0]
    raw_frames = frames
    if need_reload and session.get("path") and Path(session["path"]).is_file():
        try:
            from src.recorder import read_session
            _, raw_frames, _ = read_session(Path(session["path"]))
        except Exception:
            raw_frames = frames
    for i, f in enumerate(raw_frames[:n]):
        lm = f.get("lm") if isinstance(f, Mapping) else None
        if lm is None and isinstance(f, Mapping):
            lm = f.get("world")
        vec = extract_spatial_features(lm)
        if vec is not None:
            s_feats[i] = vec
    session["spatial_features"] = s_feats
    return s_feats


def pick_spatial_from_sessions(
    sessions: Sequence[Dict[str, Any]],
    conds: Optional[Sequence[int]] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Extract `(x_spatial, y)` arrays from sessions for the given condition group indices."""
    xs: List[np.ndarray] = []
    ys: List[np.ndarray] = []
    for s in sessions:
        s_feats = ensure_session_spatial_features(s)
        valid_vec = np.any(s_feats != 0.0, axis=1)
        m = (s["y"] >= 0) & valid_vec
        if conds is not None:
            in_cond = np.isin(s["cond"], conds)
            if (s.get("meta") or {}).get("mode") == "free":
                in_cond = in_cond | ((s["cond"] == -1) & (s["y"] == 0))
            m = m & in_cond
        if np.any(m):
            xs.append(s_feats[m])
            ys.append(s["y"][m])
    if not xs:
        return np.zeros((0, SPATIAL_FEATURES), dtype=np.float32), np.zeros((0,), dtype=np.int64)
    return np.concatenate(xs, axis=0), np.concatenate(ys, axis=0)


def blend_tcn_and_spatial_probs(
    tcn_probs: np.ndarray,
    tcn_classes: Sequence[str],
    spatial_probs: Optional[np.ndarray],
    spatial_classes: Sequence[str],
    *,
    alpha: float = 0.42,
    veto_threshold: float = 0.80,
    boost_threshold: float = 0.85,
) -> np.ndarray:
    """Combine TCN temporal probabilities with 0-lag 96-dim Spatial MLP posture probabilities.

    Supports both 1D `(C,)` single-frame and 2D `(N, C)` batch probability arrays.
    - For static/pinch gestures present in both models, blends TCN and Spatial MLP (`(1-alpha)*TCN + alpha*MLP`).
    - When Spatial MLP is strongly confident in `"none"` (`>= veto_threshold`) while TCN is below `0.85`,
      suppresses false-positive pinch spikes during half-fist cursor movement.
    - When Spatial MLP is strongly confident in a static posture (`>= boost_threshold`) and TCN is already
      moderately active (`>= 0.35`), boosts the combined probability for faster response.
    """
    out = np.asarray(tcn_probs, dtype=np.float64).copy()
    if spatial_probs is None:
        return out
    sp = np.asarray(spatial_probs, dtype=np.float64)
    single = out.ndim == 1
    if single:
        out = out[None, :]
        sp = sp[None, :] if sp.ndim == 1 else sp

    tcn_map = {name: i for i, name in enumerate(tcn_classes)}
    sp_map = {name: i for i, name in enumerate(spatial_classes)}
    none_tcn = tcn_map.get("none")
    none_sp = sp_map.get("none")

    for cls_name in STATIC_POSTURE_LABELS:
        if cls_name == "none":
            continue
        ti = tcn_map.get(cls_name)
        si = sp_map.get(cls_name)
        if ti is None or si is None:
            continue
        p_t = out[:, ti]
        p_s = sp[:, si]
        blended = (1.0 - alpha) * p_t + alpha * p_s

        # 0-lag fast confirmation boost when both agree
        boost_mask = (p_s >= boost_threshold) & (p_t >= 0.35)
        blended = np.where(boost_mask, np.maximum(blended, 0.78 * p_s + 0.22 * p_t), blended)

        # Veto suppression when Spatial MLP is confident the hand is in neutral/moving posture ('none')
        if none_sp is not None:
            p_none_s = sp[:, none_sp]
            veto_mask = (p_none_s >= veto_threshold) & (p_s < 0.15) & (p_t < 0.88)
            blended = np.where(veto_mask, blended * 0.35, blended)

        out[:, ti] = blended

    if none_tcn is not None:
        other_Indices = [i for i, name in enumerate(tcn_classes) if name != "none"]
        if other_Indices:
            max_other = np.max(out[:, other_Indices], axis=1)
            out[:, none_tcn] = np.clip(1.0 - max_other, 0.0, 1.0)
        row_sum = np.sum(out, axis=1, keepdims=True)
        out = np.where(row_sum > 1e-8, out / row_sum, out)

    return out[0] if single else out
