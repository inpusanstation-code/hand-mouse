"""The uses the app collects by itself (src/use_log.py), shown in the training center's simulator (2026-11-11).

The simulator plays recordings (training_center.simulate_model_on_recording). Here one taught gesture's logged uses are put end
to end and given the same shape of result, so the same player, timeline and per-repetition list show them:
- each use is one "repetition": 3 s before the command, the command, 2 s after;
- the stretch a learning round takes as the gesture's example (src/online/use_import.py) is the "judgment" zone, the rest is context;
- a use the person marked as not meant (F) says so, and so does one that went through on its third try;
- when the gesture has its checking model (src/online/verifier.py), its probability is the model line.
Nothing is written: the log stays as it is, and these are not recordings (they never enter the recordings folder or a training).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.online.use_import import AFTER, BEFORE_MARKED, BEFORE_TAUGHT, learnable
from src.use_log import INDEX_SUFFIX

PREFIX = "use:"            # a simulator "file" name that means: the logged uses of this gesture
MAX_USES = 60              # newest uses shown (60 x 5 s is already 5 minutes of playback)
GAP_SECONDS = .4           # pause drawn between two uses
BINS = 80


def is_use_file(name: str) -> bool:
    return str(name or "").startswith(PREFIX)


def list_gestures(folder: Path | str, root: Path | str, name_of: Callable[[str], str] = str,
                  exists: Callable[[str], bool] = lambda key: True) -> List[Dict[str, Any]]:
    """One row per taught gesture with logged uses: key, name, uses, marked, state of its checking model, the combo's text.
    Reads the small index files only. A gesture that was deleted since (`exists` says no) is left out: its old uses stay in the
    log until the log's size limit drops them, but nothing lists, counts or learns from them."""
    folder = Path(folder)
    counts: Dict[str, List[int]] = {}
    for path in sorted(folder.glob("*.jsonl")):
        index = path.with_suffix(INDEX_SUFFIX)
        if not index.is_file():
            continue
        keys: Dict[int, str] = {}
        marked: set = set()
        for line in index.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("type") == "event" and learnable(str(rec.get("source", "")), str(rec.get("key", ""))):
                keys[rec["id"]] = str(rec["key"])
            elif rec.get("type") == "mark":
                marked.add(rec.get("id"))
        for eid, key in keys.items():
            row = counts.setdefault(key, [0, 0])
            row[0] += 1
            row[1] += eid in marked
    try:
        from src.online.verifier import load_verifiers, read_status
        have, status = load_verifiers(root), read_status(root)
    except Exception:
        have, status = {}, {}
    rows = []
    for key, (uses, marks) in sorted(counts.items(), key=lambda kv: -kv[1][0]):
        if not exists(key):
            continue
        dirs = [k for k in have if k.split("@", 1)[0] == key and "@" in k]    # one checking model per hand direction
        state = (f"확인 모델 있음 (방향 {len(dirs)}개)" if dirs else "확인 모델 있음" if key in have else "다른 날 사용을 기다리는 중" if (status.get(key) or {}).get("status") == "waiting"
                 else "검사에서 떨어짐" if (status.get(key) or {}).get("status") == "rejected" else "모으는 중")
        name = name_of(key)
        rows.append({"key": key, "file": PREFIX + key, "name": name, "uses": uses, "marked": marks, "state": state,
                     "combo_label": f"{name} · 사용 {uses}번" + (f" (원하지 않음 {marks}번)" if marks else "") + f" · {state}"})
    return rows


def read_uses(folder: Path | str, key: str, limit: int = MAX_USES) -> List[Dict[str, Any]]:
    """The newest `limit` logged uses of `key`, oldest first, with their frames and "marked". Only that gesture's lines are parsed."""
    needle = json.dumps(key, ensure_ascii=False)
    out: List[Dict[str, Any]] = []
    for path in sorted(Path(folder).glob("*.jsonl")):
        events: Dict[int, Dict[str, Any]] = {}
        marks: Dict[int, str] = {}
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                is_mark = '"type": "mark"' in line
                if not is_mark and needle not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("type") == "mark":
                    marks[rec["id"]] = str(rec.get("reason") or "f_key")
                elif rec.get("type") == "event" and rec.get("key") == key and learnable(str(rec.get("source", "")), key):
                    events[rec["id"]] = rec
        for eid in sorted(events):
            events[eid]["marked"] = marks.get(eid, "")
            events[eid]["file"] = path.name
            out.append(events[eid])
    return out[-limit:]


def _verifier_probs(root: Path, key: str, uses: List[Dict[str, Any]]):
    """(threshold, per use: the checking model's probability per frame), or (None, None) when the gesture has none (or no torch)."""
    try:
        import numpy as np
        import torch

        from src.online.models import make_model
        from src.online.verifier import encoder_fingerprint, load_verifiers
        from src.online.versions import ModelManager
        from src.tcn_features import frame_features, windows
        manager = ModelManager(root)
        if not manager.has("production"):
            return None, None
        saved = manager.load()
        from src.hand_direction import split
        from src.online.use_import import event_direction
        have = load_verifiers(root, encoder_fingerprint(saved["state"]))
        # each use is checked by the model of the way its hand pointed (2026-11-11); a gesture from before: its one model
        chosen = [have.get(split(key, event_direction(use))) or have.get(key) for use in uses]
        found = [v for v in chosen if v is not None]
        if not found:
            return None, None
        verifier = found[0]
        info = saved["info"]
        model = make_model(info["kind"], len(info["classes"]), int(info["window"]), info["embedding"])
        model.load_state_dict(saved["state"])
        model.eval()
        probs = []
        with torch.no_grad():
            for use, verifier_n in zip(uses, chosen):
                frames = [{"t": f["t"], "lm": f.get("lm"), "world": f.get("world")} for f in use.get("frames") or []]
                if not frames or verifier_n is None:
                    probs.append([])
                    continue
                x = windows(frame_features(frames, 720 / 1280), int(info["window"]))
                emb = model.embed(torch.from_numpy(np.ascontiguousarray(x, dtype=np.float32))).numpy()
                probs.append([float(v) for v in verifier_n.prob(emb)])
        return float(verifier.threshold), probs
    except Exception:
        return None, None


def _runs(values: List[bool], frames: int = 3) -> bool:
    run = 0
    for v in values:
        run = run + 1 if v else 0
        if run >= frames:
            return True
    return False


def simulate(key: str, folder: Path | str, root: Path | str, name: str = "", limit: int = MAX_USES) -> Dict[str, Any]:
    """The simulator's result for the logged uses of `key` (the keys the training center reads: file, summary, gestures,
    timeline, reps, playback_frames)."""
    from src.training_center import _build_playback_frames

    name = name or key
    root = Path(root)
    uses = read_uses(folder, key, limit)
    file_name = PREFIX + key
    if not uses:
        return {"file": file_name, "using_cleaned": False, "frames": 0, "duration_s": 0.0, "has_model": False, "use_view": True,
                "summary": f"'{name}'의 사용 사례가 아직 기록되지 않았어요.", "gestures": [], "timeline": [], "reps": [],
                "playback_frames": []}
    threshold, probs = _verifier_probs(root, key, uses)
    raw: List[Dict[str, Any]] = []
    spans = []                                         # per use: (first frame, last frame, time of the command on the new clock)
    clock = 0.0
    for use in uses:
        frames = use.get("frames") or []
        if not frames:
            spans.append((len(raw), len(raw) - 1, clock))
            continue
        t0 = float(frames[0]["t"])
        start = len(raw)
        for f in frames:
            rec: Dict[str, Any] = {"t": round(clock + float(f["t"]) - t0, 3), "label": {"target": "none", "phase": "use"}}
            if f.get("lm"):
                rec["lm"], rec["world"] = f["lm"], f.get("world")
            raw.append(rec)
        spans.append((start, len(raw) - 1, clock + float(use["t"]) - t0))
        clock = raw[-1]["t"] + GAP_SECONDS
    playback = _build_playback_frames(raw, None, None, {}, threshold or .7, [])

    reps: List[Dict[str, Any]] = []
    in_stretch = [False] * len(playback)
    model_line = [0.0] * len(playback)
    for n, (use, (first, last, at)) in enumerate(zip(uses, spans), start=1):
        marked, forced = bool(use.get("marked")), bool(use.get("forced"))
        before = BEFORE_MARKED if marked else BEFORE_TAUGHT
        p = probs[n - 1] if probs is not None else None
        stretch = [i for i in range(first, last + 1) if -before <= playback[i]["t"] - at <= AFTER]
        tag = (" · 원하지 않음 표시" if marked else "") + (" · 세 번째 시도로 통과" if forced else "")
        for i in range(first, last + 1):
            frame = playback[i]
            rel = frame["t"] - at
            inside = -before <= rel <= AFTER
            in_stretch[i] = inside
            frame.update(
                task=key, task_name=name, target=key, target_name=f"사용 #{n} · {str(use.get('wall', ''))[5:16]}{tag}", rep=n,
                zone="judgment" if inside else "transition",
                zone_ko=(("학습 구간 · '아무 동작 아님'으로 학습" if marked else "학습 구간 · 이 자세의 정답") if inside else "앞뒤 맥락"),
                phase="use", phase_ko=f"명령 실행 {abs(rel):.1f}초 {'전' if rel < 0 else '후'}",
                event_kind="none",
                event_text=(f"명령 실행 · {name}" if inside else ("손 감지됨 · 앞뒤 맥락" if frame["hand_present"] else "손 감지 안 됨")),
                issue_text=("사용자가 '원하지 않음'으로 표시한 실행 (F)" if marked else "확인 모델이 막았지만 세 번째 시도로 통과한 실행" if forced else ""),
                rule_action="taught", rule_targets=[key] if inside else [], rule_names=[name] if inside else [])
            if p is not None and i - first < len(p):
                value = p[i - first]
                model_line[i] = value
                frame.update(model_cls=key, model_name=name, model_prob=round(value, 3), model_hit=value >= threshold)
            else:
                frame.update(model_cls="none", model_name="확인 모델 없음", model_prob=0.0, model_hit=False)
        values = [model_line[i] for i in stretch]
        passed = p is not None and _runs([v >= threshold for v in values])
        reps.append({"rep": n, "label": key, "name": name + tag, "time_s": round(at, 1),
                     "start_frame": stretch[0] if stretch else first, "end_frame": stretch[-1] if stretch else last,
                     "peak_prob": round(max(values), 3) if values and p is not None else 0.0,
                     "mean_prob": round(sum(values) / len(values), 3) if values and p is not None else 0.0,
                     "model_ok": bool(passed), "rule_ok": not marked, "marked": marked, "forced": forced,
                     "use": True, "no_model": p is None})

    total = len(playback)
    timeline = []
    for b in range(min(BINS, max(1, total))):
        s = int(b * total / min(BINS, max(1, total)))
        e = max(s + 1, int((b + 1) * total / min(BINS, max(1, total))))
        inside = any(in_stretch[s:e])
        peak = max(model_line[s:e]) if probs is not None else (.65 if inside else .15)
        timeline.append({"bin": b, "prob": round(peak, 3), "predicted": key if probs is not None and peak >= threshold else "none",
                         "predicted_name": name if probs is not None and peak >= threshold else "중립",
                         "target": key if inside else "none", "target_name": f"학습 구간 · {name}" if inside else "앞뒤 맥락",
                         "zone": "judgment" if inside else "transition", "zone_name": "학습 구간" if inside else "앞뒤 맥락",
                         "confirmed": probs is not None and peak >= threshold})

    meant = [r for r in reps if not r["marked"]]
    unmeant = [r for r in reps if r["marked"]]
    hits = sum(r["model_ok"] for r in meant)
    gestures = [{"key": key, "label": key, "name": name, "trained": probs is not None, "reps": len(meant), "model_hits": hits,
                 "rule_hits": len(meant), "model_rate": round(hits / len(meant), 3) if meant else None,
                 "rule_rate": 1.0 if meant else None, "max_prob": round(max(model_line), 3) if probs is not None and model_line else 0.0,
                 "mean_prob": round(sum(model_line) / len(model_line), 3) if probs is not None and model_line else 0.0,
                 "false_fires": sum(r["model_ok"] for r in unmeant)}]
    duration = round(raw[-1]["t"], 1) if raw else 0.0
    summary = (f"'{name}' 자동 수집 사용 사례 {len(uses)}번" + (f" (원하지 않음 표시 {len(unmeant)}번)" if unmeant else "")
               + (f" · 최근 {limit}번만 표시" if len(uses) >= limit else "") + f" · {duration:.0f}초 · 한 번에 앞 3초·뒤 2초 · ")
    summary += (f"확인 모델(기준 {threshold:.2f})이 뜻한 사용 {hits}/{len(meant)}번 인식"
                + (f", 원하지 않은 실행 {len(unmeant) - gestures[0]['false_fires']}/{len(unmeant)}번 막음" if unmeant else "")
                if probs is not None else "확인 모델은 아직 없어요 (관절과 학습 구간만 표시)")
    return {"file": file_name, "using_cleaned": False, "frames": total, "duration_s": duration, "has_model": probs is not None,
            "use_view": True, "summary": summary, "gestures": gestures, "timeline": timeline, "reps": reps,
            "playback_frames": playback}
