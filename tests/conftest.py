"""Tests always run against the built-in defaults, never the user's tuned config file."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import src.gesture_engine as gesture_engine


@pytest.fixture(autouse=True)
def _default_config_only(tmp_path, monkeypatch, request):
    monkeypatch.setattr(gesture_engine, "DEFAULT_CONFIG_PATH", tmp_path / "no_user_config.json")
    # Record & Fling ships OFF; most gesture tests exercise it, so they switch it on.
    # Tests marked `record_off` keep the real default.
    if request.node.get_closest_marker("record_off") is None:
        monkeypatch.setitem(gesture_engine.DEFAULT_CONFIG, "record_fling_enabled", True)


@pytest.fixture(autouse=True)
def _own_fold_cache(tmp_path, monkeypatch):
    """A test that starts a (fake) training must not leave an 'unfinished training' in the real logs/fold_cache."""
    import src.fold_cache as fold_cache
    monkeypatch.setattr(fold_cache, "CACHE_ROOT", tmp_path / "fold_cache")


@pytest.fixture(autouse=True)
def _no_hand_label_left_over():
    """Which hand is being judged (src/pose_probe.set_hand_label, set by a runtime's loop on this thread) must not stay
    for the next test: an open hand would then read as showing its back there."""
    import src.pose_probe as pose_probe
    pose_probe.set_hand_label("")
    yield
    pose_probe.set_hand_label("")


def pytest_configure(config):
    config.addinivalue_line("markers", "record_off: run with Record & Fling at its shipped default (off)")


@pytest.fixture(autouse=True)
def _own_binding_files(tmp_path, monkeypatch):
    """Never the user's gesture bindings, motions, drawings, sequences or AI history (2026-11-10: a motion the user
    registered changed the task list two dataset tests count; tests could also have written to config/)."""
    import src.action_bindings as ab
    import src.draw_mode as dm
    import src.gesture_catalog as gc
    import src.llm_binding as lb
    import src.path_gesture as pg
    import src.sequence as sq
    monkeypatch.setattr(ab, "DEFAULT_BINDINGS_PATH", tmp_path / "gesture_bindings.json")
    monkeypatch.setattr(ab, "_GLOBAL_REGISTRY", None)
    monkeypatch.setattr(ab, "_BINDING_PROFILE", None)
    monkeypatch.setattr(dm, "DEFAULT_PATH", tmp_path / "draw_shapes.json")
    monkeypatch.setattr(sq, "DEFAULT_PATH", tmp_path / "sequences.json")
    monkeypatch.setattr(pg, "DEFAULT_PATH", tmp_path / "path_gestures.json")
    monkeypatch.setattr(lb, "HISTORY_PATH", tmp_path / "ai_connections.json")
    gc.sync_custom_motions({})
    yield
    gc.sync_custom_motions({})


@pytest.fixture(autouse=True)
def _no_taught_shapes(tmp_path, monkeypatch):
    """Shapes the user taught (models/posture_teach.json) must not change what the rule tests see."""
    import src.posture_teach as posture_teach
    monkeypatch.setattr(posture_teach, "MODEL_PATH", tmp_path / "no_posture_teach.json")
    monkeypatch.setattr(posture_teach, "CANDIDATE_PATH", tmp_path / "posture_teach.candidate.json")
    monkeypatch.setattr(posture_teach, "EXAMPLES_DIR", tmp_path / "posture_examples")
    posture_teach.reset_cache()
    # ... and the shapes the user named (config/custom_postures.json) stay out of the posture lists
    import src.custom_postures as custom_postures
    monkeypatch.setattr(custom_postures, "PATH", tmp_path / "custom_postures.json")
    custom_postures.register()


@pytest.fixture(autouse=True)
def _own_center_prefs(tmp_path, monkeypatch):
    """The training center's per-profile options (tab left open, training options) go to a file of the test, never to
    the settings of the person's app."""
    monkeypatch.setenv("HAND_MOUSE_CENTER_PREFS", str(tmp_path / "center.ini"))


_DASHBOARDS = []      # every dashboard a test made, kept to the end of the run


@pytest.fixture(autouse=True)
def _keep_dashboards_alive():
    """A QtDashboard that is garbage-collected while a later test's QML is running crashes Qt on Windows (access
    violation). Its signals are connected to its own methods, so it is freed by the collector at some later moment,
    not when its test ends. Every dashboard made in a test is therefore kept until the run is over."""
    import sys
    qd = sys.modules.get("src.qt_dashboard")
    if qd is not None and not getattr(qd.QtDashboard, "_kept_by_tests", False):
        original = qd.QtDashboard.__init__

        def init(self, *args, **kwargs):
            _DASHBOARDS.append(self)
            original(self, *args, **kwargs)

        qd.QtDashboard.__init__ = init
        qd.QtDashboard._kept_by_tests = True
    yield
    qd = sys.modules.get("src.qt_dashboard")      # imported during this test: its dashboards are in use until it ends
    if qd is not None and not getattr(qd.QtDashboard, "_kept_by_tests", False):
        import gc
        _DASHBOARDS.extend(o for o in gc.get_objects() if type(o).__name__ == "QtDashboard")
