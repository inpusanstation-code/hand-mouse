"""Consistent condition groups and valid temporal windows for training and export."""
import hashlib
import os
import pickle
from pathlib import Path

import numpy as np

from src.finger_kinematics import reconstruct_hand_sequence
from src.recorder import finished_recordings, read_session
from src.recording_plan import label_condition_key
from src.spatial_features import SPATIAL_FEATURES, SPATIAL_FEATURE_VERSION, extract_spatial_features
from src.tcn_features import FEATURE_VERSION, FEATURES, frame_features, windows
from src.gesture_catalog import CLASSES, BY_KEY

_SESSION_CACHE_VERSION = f"v13-5finger-occ-rules-{FEATURE_VERSION}-{SPATIAL_FEATURE_VERSION}"
_EXTRACT_MEM_CACHE: dict[tuple[str, int, int], dict] = {}


def is_pinch_captured_on_screen(frame: dict, target: str | None) -> bool:
    """Return True if the scheduled pinch gesture is visually captured on screen in 2D/3D."""
    if target not in ("thumb_index", "thumb_middle", "thumb_ring", "thumb_pinky", "thumb_index_middle"):
        return True
    lm = frame.get("lm")
    if lm is None or len(lm) < 21:
        return False
    try:
        pts = [(float(p[0]), float(p[1])) for p in lm[:21]]
    except (TypeError, ValueError, IndexError):
        return False

    def d2(i: int, j: int) -> float:
        dx = pts[i][0] - pts[j][0]
        dy = pts[i][1] - pts[j][1]
        return float((dx * dx + dy * dy) ** 0.5)

    hs = max(d2(0, 5), d2(0, 9), d2(0, 17), 1.4 * d2(5, 17))
    if target == "thumb_index":
        return min(d2(4, 8), d2(4, 7), d2(3, 8)) <= max(0.065, 0.36 * hs)
    if target == "thumb_middle":
        return min(d2(4, 12), d2(4, 11), d2(3, 12)) <= max(0.065, 0.36 * hs)
    if target == "thumb_ring":
        return min(d2(4, 16), d2(4, 15), d2(3, 16)) <= max(0.065, 0.36 * hs)
    if target == "thumb_pinky":
        return min(d2(4, 20), d2(4, 19), d2(3, 20)) <= max(0.068, 0.37 * hs)
    if target == "thumb_index_middle":
        di = min(d2(4, 8), d2(4, 7), d2(3, 8))
        dm = min(d2(4, 12), d2(4, 11), d2(3, 12))
        thr = max(0.070, 0.38 * hs)
        return di <= thr and dm <= thr
    return True


def resolve_cleaned_path(path: Path | str, *, use_cleaned: bool = True) -> Path:
    """Return the cleaned recording path in ``cleaned/`` if it exists and is complete, else the original path."""
    p = Path(path)
    if not use_cleaned:
        return p
    cleaned_dir = p.parent / "cleaned"
    candidate = cleaned_dir / p.name
    if candidate.exists():
        usable_files, _ = finished_recordings(cleaned_dir)
        if candidate in usable_files or candidate.resolve() in {u.resolve() for u in usable_files}:
            return candidate
    return p


def discover_augmented_paths(
    paths,
    *,
    augmented_dir: Path | None = None,
    max_per_recording: int | None = None,
) -> list[Path]:
    """Find finished offline-augmented recordings in ``augmented/`` matching the given base recordings."""
    if max_per_recording is not None and max_per_recording <= 0:
        return []
    found: list[Path] = []
    seen: set[Path] = set()
    for raw_p in paths:
        p = Path(raw_p)
        base_parent = p.parent.parent if p.parent.name == "cleaned" else p.parent
        aug_dir = Path(augmented_dir) if augmented_dir is not None else (base_parent / "augmented")
        if not aug_dir.exists():
            continue
        usable_aug, _ = finished_recordings(aug_dir)
        usable_set = {u.resolve() for u in usable_aug}
        stem = p.name[: -len(".jsonl.gz")] if p.name.endswith(".jsonl.gz") else p.stem
        per_rec = 0
        for cand in sorted(aug_dir.glob(f"{stem}-aug*.jsonl.gz")):
            if cand.resolve() in usable_set and cand.resolve() not in seen:
                seen.add(cand.resolve())
                found.append(cand)
                per_rec += 1
                if max_per_recording is not None and per_rec >= max_per_recording:
                    break
    return found



def usable(frame):
    lm = frame.get("lm")
    world = frame.get("world")
    if isinstance(lm, np.ndarray) and isinstance(world, np.ndarray):
        return lm.shape == (21, 3) and world.shape == (21, 3) and bool(np.isfinite(lm).all() and np.isfinite(world).all())
    if isinstance(lm, list) and isinstance(world, list):
        if len(lm) == 21 and len(world) == 21:
            try:
                for p in lm:
                    if len(p) != 3 or not (-1e9 < float(p[0]) < 1e9 and -1e9 < float(p[1]) < 1e9 and -1e9 < float(p[2]) < 1e9):
                        return False
                for p in world:
                    if len(p) != 3 or not (-1e9 < float(p[0]) < 1e9 and -1e9 < float(p[1]) < 1e9 and -1e9 < float(p[2]) < 1e9):
                        return False
                return True
            except (TypeError, ValueError):
                return False
        return False
    try:
        for field in ("lm", "world"):
            points = np.asarray(frame.get(field), dtype=float)
            if points.shape != (21, 3) or not np.isfinite(points).all():
                return False
        return True
    except (TypeError, ValueError):
        return False


def frame_durations(frames):
    """Observed time, never invented 30fps minutes or time spent between disconnected frames."""
    out = np.zeros(len(frames), dtype=float)
    for i in range(len(frames) - 1):
        dt = float(frames[i + 1].get("t", 0)) - float(frames[i].get("t", 0))
        if 0 < dt <= 0.25:
            out[i] = dt
    return out


def _extract_record(path: Path, meta: dict, frames: list[dict], *, slim_frames: bool = False) -> dict:
    if not meta.get("complete"):
        raise ValueError(f"Unfinished recording: {path.name}")
    if not meta.get("occlusion_calibrated") and len(frames) >= 3:
        frames, num_cal = reconstruct_hand_sequence(frames, in_place=False)
        meta = dict(meta)
        meta["occlusion_calibrated"] = True
        meta["occlusion_calibrated_frames"] = int(num_cal)
    n = len(frames)
    if n >= 600 and meta.get("mode") == "guided":
        from types import SimpleNamespace
        from src.capture_rules import CaptureRules
        from src.gesture_engine import GestureEngine

        frames = list(frames)
        eng = GestureEngine()
        eng.frame_aspect = float(meta.get("frame_aspect", 0.5625))
        cap_rules = CaptureRules(eng.config)
        prev_rep_tok = None
        for idx_f, f in enumerate(frames):
            t_f = float(f.get("t", 0.0))
            lab_f = f.get("label") or {}
            rep_tok = (lab_f.get("task"), lab_f.get("set"), lab_f.get("rep"), lab_f.get("phase") == "do")
            if rep_tok != prev_rep_tok:
                prev_rep_tok = rep_tok
                eng._desktop_armed = True
                eng._desktop_since = None
                eng._last_trigger_times.clear()
                eng._last_curled_at = -1e9
                eng._last_halffist_at = -1e9
                eng._index_released_at = -1e9
                eng._scroll_released_at = -1e9
                eng._pinky_fired_at = -1e9
                eng._desktop_fired_at = -1e9
                eng._side_released_at = -1e9
                eng._side_armed = {"index": True, "ring": True, "pinky": True}
                eng._click_fresh = {"middle": True, "ring": True, "pinky": True}
                eng._secondary_since.clear()
                eng._secondary_off.clear()
                eng._index_pinched = False
                eng._middle_hold_pinched = False
            lm_f = f.get("lm") if usable(f) else None
            if isinstance(lm_f, np.ndarray):
                lm_f = lm_f.tolist()
            res_f = eng.process(lm_f, t_f)
            hand_ns = SimpleNamespace(landmarks=lm_f) if lm_f is not None else None
            obs_targets = cap_rules.observe(t_f, hand_ns, res_f, lab_f)
            old_rule = f.get("rule")
            if isinstance(old_rule, dict) or lm_f is not None:
                merged_rule = dict(old_rule) if isinstance(old_rule, dict) else {"evaluated": True}
                old_targets = list(merged_rule.get("targets") or [])
                merged_rule["targets"] = list(dict.fromkeys(old_targets + obs_targets))
                if merged_rule.get("action") in (None, "none", "move_cursor") and res_f.action not in (None, "none"):
                    merged_rule["action"] = res_f.action
                    merged_rule["gesture"] = res_f.active_gesture
                merged_rule["evaluated"] = True
                frames[idx_f] = {**f, "rule": merged_rule}
    features = np.zeros((n, FEATURES), np.float32)
    spatial_features = np.zeros((n, SPATIAL_FEATURES), np.float32)
    segments = np.full(n, -1, np.int64)
    cond_keys = [label_condition_key(f.get("label") or {}) for f in frames]
    valid_targets: list[str | None] = [None] * n
    seg_ranges: list[tuple[int, int]] = []
    start, previous = None, None
    aspect = float(meta.get("frame_aspect", 0.5625))

    def flush(end: int) -> None:
        if start is not None:
            part = frame_features(frames[start:end], aspect)
            features[start:end] = part
            segments[start:end] = start
            seg_ranges.append((start, end))

    for i, f in enumerate(frames):
        lab = f.get("label") or {}
        target = lab.get("target")
        valid = usable(f) and target not in ("idle", None)
        if valid:
            lm_pts = f.get("lm")
            if lm_pts is None:
                lm_pts = f.get("world")
            s_vec = extract_spatial_features(lm_pts)
            if s_vec is not None:
                spatial_features[i] = s_vec
        boundary = (cond_keys[i], lab.get("set"))
        gap = i > 0 and not 0 < float(f.get("t", 0)) - float(frames[i - 1].get("t", 0)) <= 0.25
        if not valid or boundary != previous or gap:
            flush(i)
            start = None
        if valid and start is None:
            start = i
        if valid and isinstance(target, str):
            valid_targets[i] = target
        previous = boundary if valid else None
    flush(n)

    for i in range(n):
        if features[i, -1] == 0:
            valid_targets[i] = None
    for i, f in enumerate(frames):
        if valid_targets[i] is None:
            continue
        lab = f.get("label") or {}
        task = BY_KEY.get(lab.get("task"))
        if task and task.direction and lab.get("phase") == "do":
            vx, vy = features[i, 130:132]
            motion = {"left": -vx, "right": vx, "down": vy}[task.direction]
            if motion < 0.03:
                valid_targets[i] = None

    # For real-length human recordings, trim reaction latency at phase transitions
    # and filter 'rest' frames where the user was still holding or releasing the gesture.
    if n >= 300:
        idx = 0
        while idx < n:
            ph = (frames[idx].get("label") or {}).get("phase")
            j = idx
            while j + 1 < n and (frames[j + 1].get("label") or {}).get("phase") == ph:
                j += 1
            t_start = float(frames[idx].get("t", 0.0))
            t_end = float(frames[j].get("t", 0.0))
            dur = t_end - t_start
            prev_ph = (frames[idx - 1].get("label") or {}).get("phase") if idx > 0 else "waiting"
            if ph == "do" and dur >= 1.2 and (j - idx + 1) >= 25:
                lab0 = frames[idx].get("label") or {}
                task0 = BY_KEY.get(lab0.get("task"))
                if not (task0 and task0.direction):
                    if prev_ph in ("prep", "rest") or (prev_ph in ("waiting", "paused") and dur >= 3.0):
                        max_trim = idx + max(1, (j - idx + 1) // 4)
                        for k in range(idx, min(j + 1, max_trim)):
                            if float(frames[k].get("t", 0.0)) - t_start < 0.30:
                                valid_targets[k] = None
                            else:
                                break
            elif ph == "rest" and prev_ph == "do" and dur >= 0.8:
                for k in range(idx, j + 1):
                    if float(frames[k].get("t", 0.0)) - t_start < 0.45:
                        valid_targets[k] = None
                    else:
                        break
            idx = j + 1

        # Filter guided pinch 'do' frames by whether the scheduled pinch is actually captured on screen
        if n >= 600:
            for i in range(n):
                tgt_i = valid_targets[i]
                if tgt_i in ("thumb_index", "thumb_middle", "thumb_ring", "thumb_pinky", "thumb_index_middle"):
                    lab_i = frames[i].get("label") or {}
                    if lab_i.get("phase") == "do" and not is_pinch_captured_on_screen(frames[i], tgt_i):
                        valid_targets[i] = None

        do_vecs = [
            spatial_features[i]
            for i in range(n)
            if valid_targets[i] not in (None, "none")
            and (frames[i].get("label") or {}).get("phase") == "do"
            and np.any(spatial_features[i] != 0.0)
        ]
        if len(do_vecs) >= 20:
            do_arr = np.asarray(do_vecs, dtype=np.float32)
            do_mean = do_arr.mean(axis=0)
            do_med = float(np.median(np.linalg.norm(do_arr - do_mean, axis=1)))
            cutoff = max(do_med * 1.35, 4.5)
            for i in range(n):
                if valid_targets[i] == "none" and (frames[i].get("label") or {}).get("phase") == "rest":
                    if np.any(spatial_features[i] != 0.0):
                        dist = float(np.linalg.norm(spatial_features[i] - do_mean))
                        if dist <= cutoff:
                            valid_targets[i] = None

    stored_frames = (
        [{"t": f.get("t", 0.0), "label": f.get("label"), "rule": f.get("rule")} for f in frames]
        if slim_frames
        else frames
    )
    return {
        "path": str(path),
        "meta": meta,
        "frames": stored_frames,
        "features": features,
        "spatial_features": spatial_features,
        "segments": segments,
        "seg_ranges": seg_ranges,
        "cond_keys": cond_keys,
        "valid_targets": valid_targets,
    }


def _load_or_extract_path(path: Path) -> dict:
    p = Path(path)
    try:
        st = p.stat()
        resolved = str(p.resolve())
        mem_key = (resolved, st.st_mtime_ns, st.st_size)
    except OSError:
        meta, frames, _ = read_session(p)
        return _extract_record(p, meta, frames, slim_frames=False)

    if mem_key in _EXTRACT_MEM_CACHE:
        return _EXTRACT_MEM_CACHE[mem_key]

    use_disk_cache = st.st_size >= 32 * 1024
    cache_file = None
    if use_disk_cache:
        base_dir = p.parent.parent if p.parent.name in ("cleaned", "augmented") else p.parent
        cache_dir = base_dir / ".cache"
        digest = hashlib.sha1(
            f"{_SESSION_CACHE_VERSION}|{resolved}|{st.st_mtime_ns}|{st.st_size}".encode("utf-8")
        ).hexdigest()[:16]
        cache_file = cache_dir / f"{p.name}.{digest}.pkl"
        if cache_file.exists():
            try:
                rec = pickle.loads(cache_file.read_bytes())
                rec["path"] = str(p)
                _EXTRACT_MEM_CACHE[mem_key] = rec
                return rec
            except Exception:
                pass

    meta, frames, _ = read_session(p)
    rec = _extract_record(p, meta, frames, slim_frames=use_disk_cache)
    _EXTRACT_MEM_CACHE[mem_key] = rec
    if cache_file is not None:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_file = cache_file.with_suffix(f".{os.getpid()}.tmp")
            tmp_file.write_bytes(pickle.dumps(rec, protocol=pickle.HIGHEST_PROTOCOL))
            os.replace(tmp_file, cache_file)
        except OSError:
            pass
    return rec


def load_sessions(paths, window=15, *, include_windows=True, classes=None, use_cleaned=False, extra_records=None):
    classes = list(CLASSES if classes is None else classes)
    class_to_idx = {name: idx for idx, name in enumerate(classes)}
    resolved_paths = [resolve_cleaned_path(p, use_cleaned=use_cleaned) for p in paths]
    extracted = [_load_or_extract_path(Path(p)) for p in resolved_paths]
    if extra_records:
        for p, meta, frames in extra_records:
            cached = meta.get("_cached_extract") if isinstance(meta, dict) else None
            if cached is not None:
                extracted.append(cached)
            else:
                extracted.append(_extract_record(Path(p), meta, frames, slim_frames=False))
    keys = sorted({k for r in extracted for k in r["cond_keys"]} - {"unassigned"})
    groups = {key: i for i, key in enumerate(keys)}
    free_none_count = sum(
        1
        for r in extracted
        for f, t in zip(r["frames"], r["valid_targets"])
        if t == "none" and (f.get("label") or {}).get("phase") != "rest"
    )
    drop_all_rest = free_none_count >= 100
    sessions = []
    for r in extracted:
        features = r["features"]
        n = len(features)
        x = np.zeros((n, window, FEATURES), np.float32) if include_windows else None
        if include_windows:
            for seg_start, seg_end in r["seg_ranges"]:
                x[seg_start:seg_end] = windows(features[seg_start:seg_end], window)
        y = np.array(
            [
                -1
                if (
                    t is None
                    or (
                        drop_all_rest
                        and t == "none"
                        and (f.get("label") or {}).get("phase") == "rest"
                    )
                )
                else class_to_idx.get(t, -1)
                for f, t in zip(r["frames"], r["valid_targets"])
            ],
            dtype=np.int64,
        )
        cond = np.array([groups.get(k, -1) for k in r["cond_keys"]], dtype=np.int64)
        sessions.append({
            "path": r["path"],
            "meta": r["meta"],
            "frames": r["frames"],
            "features": features,
            "spatial_features": r.get("spatial_features"),
            "x": x,
            "y": y,
            "cond": cond,
            "condition_groups": keys,
            "classes": classes,
            "segments": r["segments"].copy(),
        })
    return sessions
