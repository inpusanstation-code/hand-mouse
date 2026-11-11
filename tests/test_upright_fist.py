"""A fist turned on its side (thumb on top) also holds the page (2026-11-11, "세로 주먹도 스크롤브라우징 가능하게 해줘").

The fixture is the user's own upright fist from a live capture (camera 0, 1280x720): before, not one of its frames was a fist."""
import json
from pathlib import Path
from types import SimpleNamespace

from src.gesture_engine import GestureEngine
from src.virtual_hand import Grip

FIX = Path(__file__).parent / "fixtures"


def _lm(frame):
    return [SimpleNamespace(x=a[0], y=a[1], z=a[2]) for a in frame]


def _run(name, upright=True):
    d = json.loads((FIX / name).read_text(encoding="utf-8"))
    if "t" in d:
        frames = list(zip(d["t"], d["frames"]))
    else:
        frames = [(f[0], f[1]) if isinstance(f[0], (int, float)) else (i / 30, f) for i, f in enumerate(d["frames"])]
    e = GestureEngine()
    e.config["fist_upright"] = upright
    e.frame_aspect = 720 / 1280
    return [(t, e.process(_lm(lm), timestamp=t).active_gesture) for t, lm in frames]


def test_the_upright_fist_is_a_fist():
    out = _run("upright_fist_20261111.json")
    fists = sum(g == "fist" for _, g in out)
    assert fists >= .7 * len(out), (fists, len(out))
    assert not any(g == "fist" for _, g in _run("upright_fist_20261111.json", upright=False))


def test_the_upright_fist_holds_the_page_without_letting_go():
    grip, held = Grip(), []
    for t, g in _run("upright_fist_20261111.json"):
        held.append(grip.step("fist" if g == "fist" else None, t))
    first = held.index("scroll")
    assert first < 20
    assert all(m == "scroll" for m in held[first:]), "".join("S" if m else "." for m in held)


def test_other_hands_do_not_become_upright_fists():
    for name in ("index_point_20261111.json", "half_fist_moving.json", "v_sign_down_20261110.json"):
        before = sum(g == "fist" for _, g in _run(name, upright=False))
        after = sum(g == "fist" for _, g in _run(name))
        assert after == before, (name, before, after)
