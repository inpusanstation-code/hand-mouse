"""The candidate of models/gesture_tcn.onnx that the app trained from the collected uses (scripts/onnx_auto_update.py),
for the person to look at and apply (2026-11-12, the person's choice: "내가 확인 후 교체").

`view` turns models/candidate/summary.json into rows of plain words: what the model in use and the candidate do on the
uses kept out of training, the candidate's own held-out posture, and what else differs (the gestures each knows).
`apply` copies the candidate over the model in use after putting that one into models/backup-auto-<time>/;
`rollback` puts the newest such backup back; `discard` removes the candidate. Only gesture_tcn.onnx and
gesture_tcn.json are ever replaced (the other files a training writes stay with the candidate).
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

SUMMARY = "summary.json"
FILES = ("gesture_tcn.onnx", "gesture_tcn.json")
BACKUP_PREFIX = "backup-auto-"
KEEP_BACKUPS = 5


def read(candidate_dir: Path | str) -> Optional[Dict[str, Any]]:
    d = Path(candidate_dir)
    if not all((d / f).is_file() for f in FILES):
        return None
    try:
        doc = json.loads((d / SUMMARY).read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, ValueError):
        return None


def backups(models_dir: Path | str) -> List[Path]:
    """The backups made by `apply`, newest first."""
    return sorted((p for p in Path(models_dir).glob(BACKUP_PREFIX + "*") if all((p / f).is_file() for f in FILES)),
                  reverse=True)


def _names(classes) -> str:
    try:
        from src.gesture_catalog import BY_KEY
        return ", ".join(BY_KEY[c].name.split(" (")[0] if c in BY_KEY else c for c in classes) or "없음"
    except Exception:
        return ", ".join(classes) or "없음"


def _share(a: int, b: int) -> str:
    return f"{a} / {b}" if b else "자료 없음"


def view(candidate_dir: Path | str, models_dir: Path | str) -> Dict[str, Any]:
    doc = read(candidate_dir)
    out: Dict[str, Any] = {"ready": doc is not None, "rows": [], "notes": [], "can_rollback": bool(backups(models_dir))}
    if doc is None:
        return out
    new, old = doc.get("candidate") or {}, doc.get("current") or {}
    rows: List[Dict[str, Any]] = []

    def row(what: str, current: str, candidate: str, better: Optional[bool] = None) -> None:
        rows.append({"what": what, "current": current, "candidate": candidate,
                     "better": "" if better is None else ("yes" if better else "no")})

    nu, ou = new.get("uses") or {}, old.get("uses") or {}
    # the uses kept out of training: the only numbers both models are measured on alike
    if nu.get("rejected") or ou.get("rejected"):
        a, b = int(ou.get("rejected_fired", 0)), int(nu.get("rejected_fired", 0))
        row("따로 둔 오탐지 사례에서 손짓으로 본 것 (적을수록 좋음)", _share(a, int(ou.get("rejected", 0))),
            _share(b, int(nu.get("rejected", 0))), None if a == b else b < a)
    if nu.get("clicks") or ou.get("clicks"):
        a, b = int(ou.get("clicks_seen", 0)), int(nu.get("clicks_seen", 0))
        row("따로 둔 통과 클릭에서 알아본 것 (많을수록 좋음)", _share(a, int(ou.get("clicks", 0))),
            _share(b, int(nu.get("clicks", 0))), None if a == b else b > a)
    for name, g in (new.get("held_out_posture") or {}).items():
        rate = g.get("rate")
        if rate is None:
            continue
        rules = g.get("rules_rate")
        mine = (old.get("held_out_posture") or {}).get(name) or {}
        row(f"{_names([name])}: 학습에 안 쓴 자세에서 인식",
            f"{float(mine['rate']) * 100:.0f}% ({mine.get('total', 0)}회)" if mine.get("rate") is not None else "자료 없음",
            f"{float(rate) * 100:.0f}% ({g.get('total', 0)}회)")
    if new.get("misfires_per_min") is not None:
        rules = new.get("rules_misfires_per_min")
        row("손을 그냥 움직일 때 오작동",
            f"분당 {float(old['misfires_per_min']):.1f}회" if old.get("misfires_per_min") is not None else "자료 없음",
            f"분당 {float(new['misfires_per_min']):.1f}회")
    out["rows"] = rows
    notes: List[str] = []
    added = [c for c in new.get("classes") or [] if c not in (old.get("classes") or [])]
    gone = [c for c in old.get("classes") or [] if c not in (new.get("classes") or [])]
    if added:
        notes.append(f"새 후보가 추가로 아는 동작: {_names(added)}")
    if gone:
        notes.append(f"새 후보가 모르게 되는 동작: {_names(gone)}")
    held = int(doc.get("held_out", 0))
    if held < 10:
        notes.append(f"따로 둔 사례가 {held}개뿐이라 위 비교는 참고 정도예요. 더 모이면 다시 학습해요.")
    if not (nu.get("clicks") or ou.get("clicks")):
        notes.append("통과시킨 클릭 사례가 아직 없어 이번 후보는 오탐지 사례만 배웠어요 (좌클릭 카드의 [검토하기]로 통과시키면 다음부터 들어가요).")
    if (old.get("training_mode") or "") != (new.get("training_mode") or ""):
        notes.append("'학습에 안 쓴 자세'와 '오작동' 줄은 두 모델이 서로 다른 방식으로 검사된 수치예요 (지금 모델: 자세를 하나씩 "
                     "번갈아 빼는 꼼꼼 검사, 새 후보: 자세 하나만 빼는 빠른 검사). 참고로만 보고, 위의 '따로 둔 사례' 줄을 기준으로 삼으세요.")
    out.update(created=str(doc.get("created", "")), minutes=round(float(doc.get("seconds", 0.0)) / 60.0, 1),
               trained_on=int(doc.get("trained_on", 0)), held_out=held, notes=notes,
               current_trained=str(old.get("trained", "")))
    return out


def apply(candidate_dir: Path | str, models_dir: Path | str) -> Path:
    """Put the candidate in place of the model in use; that one goes to a backup folder first. Returns the backup."""
    candidate_dir, models_dir = Path(candidate_dir), Path(models_dir)
    if read(candidate_dir) is None:
        raise ValueError("적용할 후보가 없어요.")
    backup = models_dir / (BACKUP_PREFIX + time.strftime("%Y%m%d-%H%M%S"))
    backup.mkdir(parents=True, exist_ok=False)
    for name in FILES:
        if (models_dir / name).is_file():
            shutil.copy2(models_dir / name, backup / name)
    for name in FILES:                                   # the .json last: the app reads the pair
        tmp = models_dir / (name + ".new")
        shutil.copy2(candidate_dir / name, tmp)
        tmp.replace(models_dir / name)
    discard(candidate_dir)
    for old in backups(models_dir)[KEEP_BACKUPS:]:
        shutil.rmtree(old, ignore_errors=True)
    return backup


def discard(candidate_dir: Path | str) -> None:
    shutil.rmtree(Path(candidate_dir), ignore_errors=True)


def rollback(models_dir: Path | str) -> str:
    """The newest backup back in place (and that backup removed, so the next rollback goes one further). Its name."""
    models_dir = Path(models_dir)
    found = backups(models_dir)
    if not found:
        raise ValueError("되돌릴 이전 모델이 없어요.")
    newest = found[0]
    for name in FILES:
        tmp = models_dir / (name + ".new")
        shutil.copy2(newest / name, tmp)
        tmp.replace(models_dir / name)
    shutil.rmtree(newest, ignore_errors=True)
    return newest.name
