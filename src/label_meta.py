"""Which rules gave a logged label, and where a label came from (2026-11-13, user: data stays meaningful when custom gestures
come and go or the app's rules change).

The joints of a logged moment are true forever. Its label is not always: "the rules carried out a left click" is what the rules of
that day said, and a later rule change (a moving pinch is no longer a click, a stricter V sign) can make it wrong. A label the
person gave (F / F8, a review verdict, a guided recording's prompt) stays true. So every new record keeps:

- `rules`: {"code": hash of the files that judge the hand, "config": hash of the engine settings} at the time,
- `label_source`: "rule" (the rules carried it out), "user" (the person said), "auto" (picked by the app, e.g. a quiet
  stretch with no command around it), "model" (the TCN alone).

Learning can then keep what the person said as it is and judge rule labels again with the rules of its own day (the joints are
there), instead of trusting an old rule's word.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
# the files whose rules turn joints into commands (rule engine, the virtual hand's shapes, pointing mode, composite gestures,
# and the runtime that ties them together)
RULE_FILES = ("src/gesture_engine.py", "src/virtual_hand.py", "src/point_mode.py", "src/action_bindings.py",
              "src/pose_probe.py", "src/qt_runtime.py")
SOURCES = ("rule", "user", "auto", "model")

_code: Optional[str] = None


def code_hash() -> str:
    """Hash of the rule files as they are on disk (read once per process: they do not change under a running app)."""
    global _code
    if _code is None:
        h = hashlib.sha1()
        for name in RULE_FILES:
            try:
                h.update((ROOT / name).read_bytes())
            except OSError:
                h.update(name.encode())
        _code = h.hexdigest()[:12]
    return _code


def config_hash(config: Optional[Dict[str, Any]]) -> str:
    try:
        text = json.dumps(config or {}, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = repr(sorted((config or {}).items()))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def rules_version(config: Optional[Dict[str, Any]]) -> Dict[str, str]:
    return {"code": code_hash(), "config": config_hash(config)}
