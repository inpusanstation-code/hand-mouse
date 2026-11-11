"""Uses of a taught gesture are kept per hand direction (src/hand_direction.py, 2026-11-11): "the open-hand uses were collected
whatever way the hand pointed; collect and learn each direction (diagonals too) apart"."""
import json
import math
from types import SimpleNamespace

from src import hand_direction as hd

ASPECT = 720 / 1280


def hand(angle_deg, at=(.5, .5), length=.12):
    """21 landmarks: wrist at `at`, middle knuckle `length` away (screen units) at `angle_deg` clockwise from up."""
    a = math.radians(angle_deg)
    pts = [[at[0], at[1], 0.0] for _ in range(21)]
    pts[9] = [at[0] + math.sin(a) * length, at[1] - math.cos(a) * length / ASPECT, 0.0]
    return pts


def test_eight_directions_and_their_names():
    for i, d in enumerate(hd.DIRS):
        assert hd.direction([SimpleNamespace(x=p[0], y=p[1]) for p in hand(i * 45)], ASPECT) == d
        assert hd.direction(hand(i * 45 + 20), ASPECT) == d          # within the sector
    assert hd.direction(hand(0)[:20]) == "" and hd.direction(None) == ""
    assert hd.name("up_left") == "↖ 왼쪽 위"
    key = hd.split("comp_open_hand_hold", "left")
    assert key == "comp_open_hand_hold@left" and hd.base(key) == "comp_open_hand_hold" and hd.of_key(key) == "left"
    assert hd.split(key, "up") == key and hd.split("comp_a", "") == "comp_a" and hd.of_key("left_click:thumb_index") == ""


def test_the_direction_of_a_use_is_the_half_second_before_it():
    frames = [{"t": 9.0 + k / 30, "lm": hand(90)} for k in range(30)]          # pointing right until 10.0
    frames += [{"t": 10.0 + k / 30, "lm": hand(270)} for k in range(1, 30)]     # then left (after the command)
    frames[25]["lm"] = hand(180)                                                # one odd frame does not flip it
    assert hd.of_frames(frames, 10.0) == "right"
    assert hd.of_frames([{"t": 1.0, "lm": None}], 1.0) == ""


def _write(folder, events, with_dir):
    folder.mkdir(parents=True, exist_ok=True)
    full, index = [], []
    for i, angle in enumerate(events, 1):
        t = 10.0 * i
        frames = [{"t": round(t - 2 + k / 30, 4), "lm": hand(angle)} for k in range(75)]
        rec = {"type": "event", "id": i, "source": "binding", "key": "comp_open_hand_hold", "label": "", "t": t,
               "wall": f"2026-11-11 12:00:{i:02d}"}
        if with_dir:
            rec["dir"] = hd.of_frames(frames, t)
        full.append({**rec, "frames": frames})
        index.append(rec)
    (folder / "20261111-120000-pc.jsonl").write_text("\n".join(json.dumps(x) for x in full) + "\n", encoding="utf-8")
    (folder / "20261111-120000-pc.idx").write_text("\n".join(json.dumps(x) for x in index) + "\n", encoding="utf-8")


def test_uses_are_counted_per_direction_also_the_ones_logged_without_one(tmp_path):
    from src.online.use_import import DIRS_FILE, pending_counts
    from src.use_log import INDEX_SUFFIX
    assert INDEX_SUFFIX == ".idx"
    for with_dir in (True, False):                                   # logged by the app now / before the direction was logged
        folder, root = tmp_path / f"use{with_dir}", tmp_path / f"online{with_dir}"
        _write(folder, [0, 0, 270, 270, 270, 45], with_dir)
        assert pending_counts(folder, root) == {"comp_open_hand_hold@up": 2, "comp_open_hand_hold@left": 3,
                                                "comp_open_hand_hold@up_right": 1}
        assert (root / DIRS_FILE).is_file() != with_dir             # worked out once from the full file, then remembered


def test_the_viewer_shows_only_the_uses_of_that_direction(tmp_path):
    from src.use_view import cases
    _write(tmp_path / "use", [0, 270, 0, 270, 270], True)
    left = cases(tmp_path / "use", "comp_open_hand_hold@left")
    assert len(left) == 3 and all(c["direction"] == "← 왼쪽" for c in left)
    assert len(cases(tmp_path / "use", "comp_open_hand_hold")) == 5          # the whole gesture: all of them


def test_uses_stored_before_get_their_direction_label(tmp_path):
    from src.online.samples import PSEUDO_CANDIDATE, SampleStore
    from src.online.use_import import split_taught_labels
    store = SampleStore(tmp_path / "online")
    for i, angle in enumerate((0, 270)):
        frames = [{"t": k / 30, "lm": hand(angle), "world": [[0.0, 0.0, 0.0]] * 21} for k in range(45)]
        store.add_frames(frames, label="comp_open_hand_hold", label_source=PSEUDO_CANDIDATE, session="use-x",
                         sample_id=f"use-x-{i}", extra={"taught": True, "context_frames": 30})
    assert split_taught_labels(store) == 2
    assert sorted(s.label for s in store.samples()) == ["comp_open_hand_hold@left", "comp_open_hand_hold@up"]
    assert split_taught_labels(store) == 0                                   # once
