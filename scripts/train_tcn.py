"""
Train the gesture TCN on the guided recordings (recordings/*-guided.jsonl.gz) and compare it with the rules.

Run from hand-mouse/:  uv run --locked --extra qt --extra train python scripts/train_tcn.py [--folds] [--epochs 25]

- Every recorded frame becomes a 0.5 s window (15 frames) of src/tcn_features.py features, labelled with what the
  user was asked to do at its last frame: none / thumb_index / thumb_ring ("get ready" and "waiting" frames are left out).
- Honest test: one posture is held out entirely (default: the last one, the phone moved). `--folds` repeats that
  for each posture. The final model is then trained on all postures and exported to models/gesture_tcn.onnx with
  models/gesture_tcn.json (classes, window, feature version, decision threshold, where the data came from).
- Compared per repetition ("did it recognise the gesture asked for") and over the half-fist stretches ("how many
  times did it fire although nothing was asked") - the same two numbers measured for the rules, from the rule
  decisions stored in the recording.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# scripts/profile.py would shadow the standard `profile` module that torch imports: drop scripts/ from the path.
sys.path = [p for p in sys.path if Path(p or ".").resolve() != Path(__file__).resolve().parent]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import torch  # noqa: E402
import torch.nn as nn  # noqa: E402

from src.recorder import read_session  # noqa: E402
from src.tcn_features import FEATURE_VERSION, FEATURES, windows, frame_features  # noqa: E402

CLASSES = ["none", "thumb_index", "thumb_ring"]
RULE_ACTION = {"thumb_index": "scroll_grab", "thumb_ring": "right_click"}
CLICKY = {"right_click", "left_click", "task_switcher"}
STARTY = {"scroll_grab", "drag_hold"}
WINDOW = 15
PROGRESS = False          # --progress: one JSON object per line on stdout (the app's training center reads them)


def emit(event: str, **info) -> None:
    """Progress for the app (JSON lines with --progress) or for a person reading the console."""
    if PROGRESS:
        print(json.dumps({"event": event, **info}, ensure_ascii=False), flush=True)
    elif event == "epoch" and (info["epoch"] % 5 == 0 or info["epoch"] == info["epochs"]):
        print(f"    epoch {info['epoch']:2d}  loss {info['loss']:.3f}", flush=True)
    elif event in ("note",):
        print(info.get("text", ""), flush=True)


# ---------------------------------------------------------------- data
def load(paths):
    sessions = []
    for p in paths:
        meta, frames, _ = read_session(Path(p))
        feats = frame_features(frames, float(meta.get("frame_aspect", 0.5625)))
        y = np.full(len(frames), -1, dtype=np.int64)
        cond = np.full(len(frames), -1, dtype=np.int64)
        for i, f in enumerate(frames):
            lab = f.get("label") or {}
            t = lab.get("target")
            if t in CLASSES and "world" in f:
                y[i] = CLASSES.index(t)
            if lab.get("condition_index") is not None:
                cond[i] = int(lab["condition_index"])
        sessions.append({"path": str(p), "meta": meta, "frames": frames, "x": windows(feats, WINDOW), "y": y, "cond": cond})
    return sessions


def pick(sessions, conds):
    xs, ys = [], []
    for s in sessions:
        m = (s["y"] >= 0) & np.isin(s["cond"], conds)
        xs.append(s["x"][m])
        ys.append(s["y"][m])
    return np.concatenate(xs), np.concatenate(ys)


# ---------------------------------------------------------------- model
class TCN(nn.Module):
    """Causal dilated 1-D convolutions over 15 frames (receptive field 15); the last step is classified."""

    def __init__(self, n_in: int = FEATURES, ch: int = 64, n_out: int = len(CLASSES), drop: float = 0.2):
        super().__init__()
        layers, c = [], n_in
        for d in (1, 2, 4):
            layers += [nn.ConstantPad1d((2 * d, 0), 0.0), nn.Conv1d(c, ch, 3, dilation=d), nn.ReLU(), nn.Dropout(drop)]
            c = ch
        self.body = nn.Sequential(*layers)
        self.head = nn.Linear(ch, n_out)

    def forward(self, x):                      # x: (batch, time, features)
        h = self.body(x.transpose(1, 2))
        return self.head(h[:, :, -1])


def augment(x: torch.Tensor) -> torch.Tensor:
    """Different seats / camera angles: small 3D rotation of the hand-frame joints, size and jitter."""
    b = x.shape[0]
    ang = (torch.rand(b, 3) - 0.5) * math.radians(30)
    cx, cy, cz = torch.cos(ang).unbind(1)
    sx, sy, sz = torch.sin(ang).unbind(1)
    one, zero = torch.ones(b), torch.zeros(b)
    rx = torch.stack([one, zero, zero, zero, cx, -sx, zero, sx, cx], 1).view(b, 3, 3)
    ry = torch.stack([cy, zero, sy, zero, one, zero, -sy, zero, cy], 1).view(b, 3, 3)
    rz = torch.stack([cz, -sz, zero, sz, cz, zero, zero, zero, one], 1).view(b, 3, 3)
    r = rz @ ry @ rx
    x = x.clone()
    for lo in (0, 63):
        pts = x[:, :, lo:lo + 63].reshape(b, x.shape[1], 21, 3)
        x[:, :, lo:lo + 63] = torch.einsum("btjk,blk->btjl", pts, r).reshape(b, x.shape[1], 63)
    scale = 1.0 + (torch.rand(b, 1, 1) - 0.5) * 0.2
    x[:, :, :130] = x[:, :, :130] * scale
    x[:, :, :130] += torch.randn_like(x[:, :, :130]) * 0.01
    return x


def train(x, y, epochs: int, seed: int = 0, stage: str = "", losses=None):
    torch.manual_seed(seed)
    np.random.seed(seed)
    model = TCN()
    counts = np.bincount(y, minlength=len(CLASSES)).astype(np.float64)
    weight = torch.tensor((counts.sum() / np.maximum(counts, 1)) ** 0.5, dtype=torch.float32)
    lossf = nn.CrossEntropyLoss(weight=weight / weight.mean())
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)
    xt, yt = torch.from_numpy(x), torch.from_numpy(y)
    for ep in range(epochs):
        model.train()
        perm = torch.randperm(len(xt))
        total = 0.0
        for i in range(0, len(perm), 256):
            idx = perm[i:i + 256]
            opt.zero_grad()
            loss = lossf(model(augment(xt[idx])), yt[idx])
            loss.backward()
            opt.step()
            total += float(loss.detach()) * len(idx)
        avg = total / len(perm)
        if losses is not None:
            losses.append(round(avg, 4))
        emit("epoch", stage=stage, epoch=ep + 1, epochs=epochs, loss=round(avg, 4))
    return model


def predict(model, x) -> np.ndarray:
    model.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(x), 2048):
            out.append(torch.softmax(model(torch.from_numpy(x[i:i + 2048])), dim=1).numpy())
    return np.concatenate(out)


# ---------------------------------------------------------------- event-level evaluation
def runs(mask: np.ndarray, k: int):
    """Start indices of runs of at least k True frames."""
    starts, n = [], 0
    for i, v in enumerate(mask):
        n = n + 1 if v else 0
        if n == k:
            starts.append(i)
    return starts


def evaluate(session, conds, prob=None, thr=0.7, k=3):
    """{"reps": {task: (recognised, total)}, "misfires": {kind: n}, "confused": n} for the model (prob given) or rules."""
    frames = session["frames"]
    rep_frames = defaultdict(list)
    free = []
    for i, f in enumerate(frames):
        lab = f.get("label") or {}
        if lab.get("condition_index") not in conds:
            continue
        if lab.get("task") in RULE_ACTION and lab.get("phase") in ("do", "rest"):
            rep_frames[(lab["condition_index"], lab["task"], lab["rep"])].append(i)
        elif lab.get("task") == "none" and lab.get("phase") == "free":
            free.append(i)
    recog, total, confused = Counter(), Counter(), 0
    misfires = Counter()
    if prob is not None:
        fired = {c: np.zeros(len(frames), dtype=bool) for c in (1, 2)}
        for c in (1, 2):
            for s in runs(prob[:, c] >= thr, k):
                fired[c][s] = True
        for (cond, task, rep), idx in rep_frames.items():
            total[task] += 1
            want = CLASSES.index(task)
            other = 3 - want
            if fired[want][idx].any():
                recog[task] += 1
            if fired[other][idx].any():
                confused += 1
        free_set = np.zeros(len(frames), dtype=bool)
        free_set[free] = True
        for c in (1, 2):
            misfires[CLASSES[c]] = int((fired[c] & free_set).sum())
    else:
        acts = [(f.get("rule") or {}).get("action") for f in frames]
        for (cond, task, rep), idx in rep_frames.items():
            total[task] += 1
            a = {acts[i] for i in idx}
            if RULE_ACTION[task] in a:
                recog[task] += 1
            if a & ({"right_click", "scroll_grab"} - {RULE_ACTION[task]}):
                confused += 1
        prev = None
        for i in free:
            a = acts[i]
            if a in CLICKY:
                misfires[a] += 1
            elif a in STARTY and prev != a:
                misfires[a] += 1
            prev = a
    return {"reps": {t: (recog[t], total[t]) for t in total}, "misfires": dict(misfires), "confused": confused}


def free_minutes(session, conds) -> float:
    n = sum(1 for f in session["frames"] if (f.get("label") or {}).get("phase") == "free"
            and (f.get("label") or {}).get("condition_index") in conds)
    return n / 30.0 / 60.0


def per_gesture(summary, windows_per_class, train_acc):
    """Scores per gesture for the training center: held-out recognition, misfires per minute, data, fit."""
    out = {}
    for c, name in enumerate(CLASSES):
        g = {"windows": int(windows_per_class.get(name, 0)), "train_accuracy": train_acc.get(name)}
        if name in RULE_ACTION:
            a = sum(m["tcn"]["reps"].get(name, (0, 0))[0] for m in summary)
            b = sum(m["tcn"]["reps"].get(name, (0, 0))[1] for m in summary)
            ra = sum(m["rules"]["reps"].get(name, (0, 0))[0] for m in summary)
            g.update(recognised=a, total=b, rate=round(a / b, 3) if b else None,
                     rules_rate=round(ra / b, 3) if b else None)
        else:
            mins = sum(m.get("free_minutes", 0.0) for m in summary)
            tcn = sum(sum(m["tcn"]["misfires"].values()) for m in summary)
            rules = sum(sum(m["rules"]["misfires"].values()) for m in summary)
            g.update(free_minutes=round(mins, 2), misfires=tcn, rules_misfires=rules,
                     misfires_per_min=round(tcn / mins, 2) if mins else None,
                     rules_misfires_per_min=round(rules / mins, 2) if mins else None)
        out[name] = g
    return out


def show(name, r):
    reps = "  ".join(f"{t} {a}/{b}" for t, (a, b) in sorted(r["reps"].items()))
    mis = sum(r["misfires"].values())
    print(f"  {name:6s} recognised: {reps}  | wrong gesture in reps: {r['confused']}  | fired during half-fist moving: {mis} {r['misfires']}")


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recordings", default=str(ROOT / "recordings" / "*-guided.jsonl.gz"))
    ap.add_argument("--test-condition", type=int, default=2)
    ap.add_argument("--folds", action="store_true", help="hold out each posture in turn")
    ap.add_argument("--epochs", type=int, default=25)
    ap.add_argument("--thr", type=float, default=0.7)
    ap.add_argument("--k", type=int, default=3, help="frames in a row above the threshold that count as the gesture")
    ap.add_argument("--no-export", action="store_true")
    ap.add_argument("--progress", action="store_true", help="JSON progress lines for the app")
    a = ap.parse_args()
    global PROGRESS
    PROGRESS = a.progress

    paths = sorted(glob.glob(a.recordings))
    if not paths:
        emit("error", text=f"녹화가 없어요: {a.recordings}")
        print("no recordings found:", a.recordings)
        return 1
    t0 = time.perf_counter()
    sessions = load(paths)
    conds = sorted({int(c) for s in sessions for c in s["cond"] if c >= 0})
    xa, ya = pick(sessions, conds)
    per_class = dict(Counter(CLASSES[i] for i in ya))
    if not PROGRESS:
        print(f"{len(paths)} recording(s), postures {conds}, {len(ya)} labelled windows {per_class}"
              f"  ({time.perf_counter() - t0:.1f} s to load)")
    emit("loaded", recordings=len(paths), postures=conds, windows=int(len(ya)), per_class=per_class,
         folds=len(conds) if a.folds else (0 if a.test_condition < 0 else 1))

    held = conds if a.folds else ([] if a.test_condition < 0 else [a.test_condition])
    summary = []
    for test in held:
        train_conds = [c for c in conds if c != test]
        x, y = pick(sessions, train_conds)
        if not PROGRESS:
            print(f"\n== held-out posture {test} (train on {train_conds}, {len(y)} windows)")
        emit("fold_start", posture=test, fold=held.index(test) + 1, folds=len(held))
        t1 = time.perf_counter()
        model = train(x, y, a.epochs, stage=f"fold{test}")
        if not PROGRESS:
            print(f"    trained in {time.perf_counter() - t1:.0f} s")
        for s in sessions:
            prob = predict(model, s["x"])
            rule = evaluate(s, [test])
            tcn = evaluate(s, [test], prob, a.thr, a.k)
            if not PROGRESS:
                show("rules", rule)
                show("TCN", tcn)
            summary.append((test, rule, tcn, free_minutes(s, [test])))
            emit("fold_result", posture=test, rules=rule, tcn=tcn)

    if a.no_export:
        return 0
    old = ROOT / "models" / "gesture_tcn.onnx.data"
    if old.exists():
        old.unlink()                         # an earlier export kept the weights apart
    if not PROGRESS:
        print(f"\n== final model on all postures {conds}")
    emit("final_start")
    losses: list = []
    model = train(xa, ya, a.epochs, stage="final", losses=losses)
    pred = predict(model, xa).argmax(1)
    train_acc = {name: round(float((pred[ya == c] == c).mean()), 3) for c, name in enumerate(CLASSES) if (ya == c).any()}
    out = ROOT / "models" / "gesture_tcn.onnx"
    model.eval()
    torch.onnx.export(model, torch.zeros(1, WINDOW, FEATURES), str(out), input_names=["x"], output_names=["logits"],
                      dynamic_axes={"x": {0: "batch"}, "logits": {0: "batch"}}, opset_version=18,
                      external_data=False)
    if not summary and (ROOT / "models" / "gesture_tcn.json").exists():
        # (--test-condition -1: only the final model; keep the held-out results of the last full run)
        summary = [(r["posture"], r["rules"], r["tcn"], r.get("free_minutes", 0.0)) for r in
                   json.loads((ROOT / "models" / "gesture_tcn.json").read_text(encoding="utf-8")).get("held_out_results", [])]
    results = [{"posture": t, "rules": r, "tcn": m, "free_minutes": round(fm, 2)} for t, r, m, fm in summary]
    info = {
        "classes": CLASSES, "window": WINDOW, "features": FEATURES, "feature_version": FEATURE_VERSION,
        "threshold": a.thr, "frames_in_a_row": a.k, "epochs": a.epochs,
        "trained": time.strftime("%Y-%m-%d %H:%M:%S"),
        "data": [{"file": Path(s["path"]).name, "pc": s["meta"].get("pc"), "camera": s["meta"].get("camera"),
                  "frames": len(s["frames"])} for s in sessions],
        "held_out_results": results,
        "loss_curve": losses, "train_accuracy": train_acc,
        "per_gesture": per_gesture(results, per_class, train_acc),
    }
    (ROOT / "models" / "gesture_tcn.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    if not PROGRESS:
        print(f"saved {out.name} ({out.stat().st_size // 1024} KB) and gesture_tcn.json")
    emit("done", model=out.name, kb=out.stat().st_size // 1024, per_gesture=info["per_gesture"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
