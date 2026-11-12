"""Does a taught gesture's checking model (src/online/verifier.py) get better when it sees more than the last half second?

The use log keeps 3 s before each command, but the checking model looks at one embedding: the production encoder's view of the
last 15 frames (.5 s). Here the same small head is trained on that embedding alone, and on it together with the embeddings .5 s,
1 s and 1.5 s earlier (1 s and 2 s of history), and tested on recordings it did not see.

There is no everyday use log yet, so the guided recordings stand in: for one gesture at a time, its "do" frames are the yes
examples (as if the person had taught it) and every other frame with a hand (other gestures, getting ready, resting, the
"almost touching" tasks) is a no example. Recordings of the encoder's validation sessions are the test; a gesture that was only
recorded on one side is split by time inside its recordings (first 60 % train, rest test).

Per gesture and history length (mean of SEEDS runs):
  recall@1%  : repetitions recognised (FRAMES windows in a row) at the threshold where 1 % of the test no-windows are over it
  false@90%  : share of test no-windows over the threshold at which 90 % of the repetitions are recognised
Both thresholds are picked on the test recordings, the same way for every length: fine for comparing lengths, too kind as
absolute numbers. Results: logs/verifier_window_compare.json.

프로젝트 폴더에서:  ..\\hand-mouse-gpuenv\\Scripts\\python.exe scripts/verifier_window_compare.py   (또는 .venv 의 python)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[0] = str(ROOT)

import numpy as np  # noqa: E402
import torch  # noqa: E402

from src.gesture_catalog import BY_KEY  # noqa: E402
from src.online.models import make_model  # noqa: E402
from src.online.samples import DEFAULT_ROOT  # noqa: E402
from src.online.verifier import FRAMES, NEG_CAP, _fit  # noqa: E402
from src.online.versions import ModelManager  # noqa: E402
from src.pinch_report import read_recording  # noqa: E402
from src.tcn_features import frame_features, windows  # noqa: E402

LAGS = {"0.5s": (0,), "1s": (0, 15), "2s": (0, 15, 30, 45)}      # frames back from now whose embeddings the head sees
SEEDS = (0, 1, 2, 3, 4)
SKIP_DO = 10          # the fingers arrive a moment after the schedule says "do"
NEAR = .7             # seconds around a gesture's "do" frames that count as neither yes nor no for it
MIN_REPS = 6          # test repetitions a gesture needs to be reported
THRESHOLDS = np.concatenate([np.linspace(.02, .98, 49), [.99, .995, .999]])


def load(model, window):
    """Per recording: embeddings per frame, hand flag, the gesture label of its "do" frames ("" elsewhere), repetition id."""
    out = {}
    for path in sorted((ROOT / "recordings").glob("*.jsonl.gz")):
        meta, frames = read_recording(path)
        frames = [f for f in frames if "t" in f]
        if len(frames) < 100:
            continue
        feats = frame_features(frames, float(meta.get("frame_aspect") or .5625))
        x = windows(feats, window)
        parts = []
        with torch.no_grad():
            for i in range(0, len(x), 4096):
                parts.append(model.embed(torch.from_numpy(np.ascontiguousarray(x[i:i + 4096], dtype=np.float32))).numpy())
        emb = np.concatenate(parts)
        label = np.array([""] * len(frames), dtype=object)
        rep = np.full(len(frames), -1)
        seen, run, last = {}, 0, None
        for i, f in enumerate(frames):
            lab = f.get("label") or {}
            task = BY_KEY.get(lab.get("task"))
            token = (lab.get("task"), lab.get("set"), lab.get("rep")) if lab.get("phase") == "do" and task and not task.free else None
            if token != last:
                run, last = 0, token
            if token is not None and task.label != "none":
                run += 1
                if run > SKIP_DO:
                    label[i] = task.label
                    rep[i] = seen.setdefault(token, len(seen))
        # frames of a "do" phase, by gesture: the frames within NEAR seconds of them are neither yes nor no for that gesture
        # (the hand is still getting there or has not let go yet; scripts/online_gate_replay.py leaves out the same margin)
        t = np.array([float(f["t"]) for f in frames])
        do_of = np.array([(BY_KEY[(f.get("label") or {}).get("task")].label
                           if (f.get("label") or {}).get("phase") == "do" and (f.get("label") or {}).get("task") in BY_KEY else "")
                          for f in frames], dtype=object)
        out[path.name.split(".")[0]] = {"emb": emb, "hand": feats[:, 132] > 0, "label": label, "rep": rep, "t": t, "do_of": do_of}
    return out


def lagged(emb, lags):
    """(n, E * len(lags)): the embedding now and `lags` frames earlier (zeros before the recording starts)."""
    cols = []
    for lag in lags:
        shifted = np.zeros_like(emb)
        if lag < len(emb):
            shifted[lag:] = emb[:len(emb) - lag]
        cols.append(shifted)
    return np.concatenate(cols, axis=1)


def runs_hit(over, frames=FRAMES):
    run = 0
    for v in over:
        run = run + 1 if v else 0
        if run >= frames:
            return True
    return False


def evaluate(p, y, reps):
    """recall@1% and false@90% (see the top of the file)."""
    neg = p[~y]
    rep_ids = sorted(set(reps[y]))
    table = []
    for th in THRESHOLDS:
        false = float((neg >= th).mean())
        hit = sum(runs_hit(p[y & (reps == r)] >= th) for r in rep_ids)
        table.append((th, false, hit / len(rep_ids)))
    at_one = max((r for _, f, r in table if f <= .01), default=0.0)
    at_ninety = min((f for _, f, r in table if r >= .9), default=1.0)
    return at_one, at_ninety


def main() -> int:
    manager = ModelManager(DEFAULT_ROOT)
    if not manager.has("production"):
        print("no production model: run the three 'first time' commands of docs/online-learning-guide.md")
        return 1
    saved = manager.load()
    info = saved["info"]
    model = make_model(info["kind"], len(info["classes"]), int(info["window"]), info["embedding"])
    model.load_state_dict(saved["state"])
    model.eval()
    validation = set(info.get("validation_sessions") or [])
    data = load(model, int(info["window"]))
    print(f"recordings {len(data)} (validation {sum(s in validation for s in data)}), frames {sum(len(d['emb']) for d in data.values())}")
    gestures = sorted({g for d in data.values() for g in set(d["label"]) if g})
    results = {}
    for gesture in gestures:
        has = {s: bool((d["label"] == gesture).any()) for s, d in data.items()}
        cross = any(has[s] and s in validation for s in data) and any(has[s] and s not in validation for s in data)
        row = {"split": "other recordings" if cross else "by time inside its recordings", "known_to_encoder": gesture in info["classes"]}
        for name, lags in LAGS.items():
            xs_tr, ys_tr, xs_te, ys_te, reps_te = [], [], [], [], []
            offset = 0
            for session, d in data.items():
                x = lagged(d["emb"], lags)
                y = d["label"] == gesture
                do_t = d["t"][d["do_of"] == gesture]
                if len(do_t):
                    pos = np.searchsorted(do_t, d["t"])
                    gap = np.minimum(np.abs(d["t"] - do_t[np.clip(pos - 1, 0, len(do_t) - 1)]),
                                     np.abs(d["t"] - do_t[np.clip(pos, 0, len(do_t) - 1)]))
                    near = (gap <= NEAR) & ~y
                else:
                    near = np.zeros(len(y), bool)
                keep = d["hand"] & ~near
                test = np.zeros(len(y), bool)
                if cross:
                    test[:] = session in validation
                elif has[session]:
                    test[int(len(y) * .6):] = True
                else:
                    test[:] = session in validation
                xs_tr.append(x[keep & ~test]); ys_tr.append(y[keep & ~test])
                xs_te.append(x[keep & test]); ys_te.append(y[keep & test])
                reps_te.append(np.where(d["rep"][keep & test] >= 0, d["rep"][keep & test] + offset, -1))
                offset += int(d["rep"].max()) + 1 if len(d["rep"]) else 0
            x_tr, y_tr = np.concatenate(xs_tr), np.concatenate(ys_tr)
            x_te, y_te, r_te = np.concatenate(xs_te), np.concatenate(ys_te), np.concatenate(reps_te)
            n_reps = len(set(r_te[y_te]))
            if y_tr.sum() < 50 or n_reps < MIN_REPS:
                row = None
                break
            scores = []
            for seed in SEEDS:
                rng = np.random.default_rng(seed)
                neg = np.flatnonzero(~y_tr)
                if len(neg) > NEG_CAP:
                    neg = rng.choice(neg, NEG_CAP, replace=False)
                idx = np.concatenate([np.flatnonzero(y_tr), neg])
                mean, scale, w1, b1, w2, b2 = _fit(x_tr[idx], y_tr[idx].astype(float), seed)
                hidden = np.maximum(((x_te - mean) / scale) @ w1 + b1, 0.0)
                p = 1.0 / (1.0 + np.exp(-np.clip(hidden @ w2 + b2, -50, 50)))
                scores.append(evaluate(p, y_te, r_te))
            row[name] = {"recall_at_1pct": round(float(np.mean([s[0] for s in scores])), 3),
                         "recall_spread": round(float(np.max([s[0] for s in scores]) - np.min([s[0] for s in scores])), 3),
                         "false_at_90pct": round(float(np.mean([s[1] for s in scores])), 4)}
            row["test_reps"], row["train_yes_windows"], row["test_no_windows"] = n_reps, int(y_tr.sum()), int((~y_te).sum())
        if row is None:
            continue
        results[gesture] = row
        print(f"{gesture:16s} {'(encoder knows it)' if row['known_to_encoder'] else '(new to encoder) ':18s} reps {row['test_reps']:3d}  "
              + "   ".join(f"{n}: recall@1% {row[n]['recall_at_1pct']:.2f}±{row[n]['recall_spread'] / 2:.2f} false@90% {row[n]['false_at_90pct']:.3f}" for n in LAGS), flush=True)
    (ROOT / "logs").mkdir(exist_ok=True)
    (ROOT / "logs" / "verifier_window_compare.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    if results:
        print("mean             " + " " * 28 + "   ".join(
            f"{n}: recall@1% {np.mean([r[n]['recall_at_1pct'] for r in results.values()]):.2f} "
            f"false@90% {np.mean([r[n]['false_at_90pct'] for r in results.values()]):.3f}" for n in LAGS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
