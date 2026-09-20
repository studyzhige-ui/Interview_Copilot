import math
import pytest
from pydantic import TypeAdapter
from app.core.scoring import (
    Score,
    mean_score,
    read_historical_score,
    score_scale,
    validate_score,
)


@pytest.mark.parametrize("value", [n / 10 for n in range(101)])
def test_every_tenth_is_valid_without_clipping(value):
    assert TypeAdapter(Score).validate_python(value) == value


@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        "8",
        "10",
        None,
        [],
        {},
        math.nan,
        math.inf,
        -math.inf,
        -0.1,
        10.1,
        4.05,
        10**1000,
    ],
)
def test_invalid_is_not_cast_rounded_or_clamped(value):
    with pytest.raises(ValueError):
        validate_score(value)


def test_missing_is_not_zero_and_history_requires_identified_units():
    assert mean_score([None, None]) is None
    assert mean_score([0, None, 10]) == 5
    assert read_historical_score(85, "score100-legacy-v2") == 8.5
    assert read_historical_score(8.5, "score10-v1") == 8.5
    assert read_historical_score(8.5, None) is None
    assert read_historical_score(8.5, "unrecognized") is None
    assert read_historical_score(99, "score10-v1") is None
    assert score_scale()["range"] == [0, 10]


def test_product_evaluator_uses_same_scale():
    from evaluation.mock_contracts import JUDGE_DIMENSIONS, JudgeResult

    value = {
        **dict.fromkeys(JUDGE_DIMENSIONS, 8.5),
        "reason": "依据候选人的上一问与回答。",
    }
    assert JudgeResult.model_validate(value).grounding == 8.5
