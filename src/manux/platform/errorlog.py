"""The error log: one file the person (or a teammate) can open when something went wrong (2026-11-10 request).

`<data>/logs/errors.log` (rotated: 1 MB x 5 files). What goes in:
- uncaught exceptions on any thread, with the traceback;
- errors and warnings the app logs on the `manux` logger (the runtime loop, startup failures);
- Qt warnings, criticals and fatals (QML binding errors and the like). Qt debug/info chatter is left out.

The Windows home folder in any message is written as `~`, because `logs/` goes into "로그 묶어 내보내기".
No camera images, window titles or key strokes are ever logged here.
"""
from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

LOGGER = "manux"
FILE = "errors.log"
_installed: Optional[Path] = None


class _HideHome(logging.Filter):
    def __init__(self) -> None:
        super().__init__()
        home = str(Path.home())
        self.forms = sorted({home, home.replace("\\", "/"), home.replace("\\", "\\\\")}, key=len, reverse=True)

    def _clean(self, text: str) -> str:
        for form in self.forms:
            text = text.replace(form, "~")
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._clean(record.getMessage())
        record.args = None
        if record.exc_info:
            record.exc_text = self._clean(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


def logger(name: str = "") -> logging.Logger:
    return logging.getLogger(LOGGER + ("." + name if name else ""))


def install(log_dir: Path, *, qt: bool = True) -> Path:
    """Start writing errors.log in `log_dir` (once per process; later calls return the same path)."""
    global _installed
    if _installed is not None:
        return _installed
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / FILE
    handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=5, encoding="utf-8", delay=True)
    handler.setLevel(logging.WARNING)
    handler.addFilter(_HideHome())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s"))
    root = logging.getLogger(LOGGER)
    root.addHandler(handler)
    root.setLevel(logging.WARNING)
    root.propagate = False

    previous_hook = sys.excepthook

    def excepthook(kind, value, tb):
        if not issubclass(kind, KeyboardInterrupt):
            root.critical("uncaught exception", exc_info=(kind, value, tb))
            print(f"[MANUX] 오류 기록: {path}", file=sys.stderr)
        previous_hook(kind, value, tb)

    previous_thread_hook = threading.excepthook

    def thread_hook(args):
        if args.exc_type is not SystemExit:
            root.critical("uncaught exception in thread %s", getattr(args.thread, "name", "?"),
                          exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        previous_thread_hook(args)

    sys.excepthook = excepthook
    threading.excepthook = thread_hook
    if qt:
        _install_qt(root.getChild("qt"))
    _installed = path
    return path


def _install_qt(log: logging.Logger) -> None:
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except ImportError:
        return
    levels = {QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
              QtMsgType.QtFatalMsg: logging.CRITICAL}
    previous = None

    def handler(kind, context, message):
        level = levels.get(kind)
        if level is not None:
            where = f"{context.file}:{context.line}: " if getattr(context, "file", None) else ""
            log.log(level, "%s%s", where, message)
        if previous is not None:
            previous(kind, context, message)
        elif level is not None:
            print(message, file=sys.stderr)       # keep Qt's own console output

    previous = qInstallMessageHandler(handler)
