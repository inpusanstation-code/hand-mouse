"""The personal pinch-shape model: trains on synthetic rows, saves and loads, refuses a wrong file."""
import json

import numpy as np
import pytest

from manux.perception.pinch_shape import FILE, PinchShapeModel, load_optional, train


def test_trains_saves_and_loads_the_same_scores(tmp_path):
    rng = np.random.default_rng(0)
    x = rng.normal(0, 1, (400, 33)); y = (x[:, 3] + x[:, 4] > 0).astype(float)   # "ring and little finger out"
    model = train(x, y, info={"note": "synthetic"})
    assert ((model.score_features(x) >= .5) == (y > .5)).mean() > .9
    model.save(tmp_path / FILE)
    again = load_optional(tmp_path)
    assert again is not None and np.allclose(again.score_features(x[:5]), model.score_features(x[:5]))
    assert again.info["note"] == "synthetic"


def test_missing_or_wrong_files_mean_no_model(tmp_path):
    assert load_optional(tmp_path) is None
    (tmp_path / FILE).parent.mkdir(parents=True)
    (tmp_path / FILE).write_text(json.dumps({"version": "other"}), encoding="utf-8")
    assert load_optional(tmp_path) is None
    with pytest.raises(ValueError):
        train(np.zeros((3, 33)), np.zeros(3))


def test_unusable_joints_give_no_score():
    model = train(np.random.default_rng(1).normal(0, 1, (50, 33)), np.arange(50) % 2)
    assert model.score(None) is None and model.score([[0, 0, 0]] * 21) is None
