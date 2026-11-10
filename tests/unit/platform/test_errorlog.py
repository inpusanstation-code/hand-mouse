"""errors.log (2026-11-10 request): errors are written to their own file, with the home folder masked."""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def run_child(tmp_path, body):
    code = textwrap.dedent(f"""
        import sys, threading
        sys.path.insert(0, {str(ROOT / 'src')!r})
        from pathlib import Path
        from manux.platform.errorlog import install, logger
        path = install(Path({str(tmp_path)!r}), qt=False)
        assert install(Path({str(tmp_path)!r}) / "other", qt=False) == path      # once per process
    """) + textwrap.dedent(body)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}                      # same bytes whatever the console code page
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)


def test_errors_threads_and_crashes_go_to_errors_log_with_home_masked(tmp_path):
    result = run_child(tmp_path, """
        logger("runtime").error("could not open %s", str(Path.home() / "secret" / "file.txt"))
        logger("runtime").info("not an error: left out")
        t = threading.Thread(target=lambda: 1 / 0, name="worker-x"); t.start(); t.join()
        raise RuntimeError("boom at " + str(Path.home()))
    """)
    assert result.returncode != 0 and "오류 기록" in result.stderr
    text = (tmp_path / "errors.log").read_text(encoding="utf-8")
    assert "could not open ~" in text and str(Path.home()) not in text
    assert "not an error" not in text
    assert "worker-x" in text and "ZeroDivisionError" in text
    assert "uncaught exception" in text and "RuntimeError: boom at ~" in text


def test_the_runtime_loop_logs_a_new_error_once_and_then_counts(tmp_path, monkeypatch):
    import logging
    from types import SimpleNamespace
    from manux.app import schema
    from manux.desktop import build
    from manux.settings.store import Settings
    runtime = build(Settings(schema()), SimpleNamespace(close=lambda: None), windows=False)
    records = []
    handler = logging.Handler()
    handler.emit = records.append
    log = logging.getLogger("manux")
    log.addHandler(handler)
    old_level = log.level
    log.setLevel(logging.WARNING)
    calls = {"n": 0}

    def failing_step():
        calls["n"] += 1
        if calls["n"] >= 4:
            runtime._stop.set()
        raise ValueError("camera gone")
    monkeypatch.setattr(runtime, "step", failing_step)
    monkeypatch.setattr("manux.desktop.time.sleep", lambda s: None)
    try:
        runtime._loop()
    finally:
        log.removeHandler(handler)
        log.setLevel(old_level)
        runtime._stop.clear()
        runtime.stop()
    failures = [r for r in records if r.getMessage() == "runtime step failed"]
    assert len(failures) == 1 and failures[0].exc_info and calls["n"] == 4
