"""The single 0–10 evaluation scale used by product and evaluation code.

Physical metrics (latency, WER, probability, retrieval similarity) are not scores.
A rubric identifies *what* was measured; this module identifies the numeric unit.
Missing evidence is None, never zero. Model values are validated, never clamped.
"""

from __future__ import annotations

import math
from statistics import mean
from typing import Annotated

from pydantic import BeforeValidator, Field

SCORE_SCALE_VERSION = "score10-v1"
SCORE_MIN = 0.0
SCORE_MAX = 10.0
QUALITY_PASS_SCORE = 8.0


def validate_score(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("score must be a JSON number, not a boolean or string")
    try:
        score = float(value)
    except OverflowError:
        raise ValueError("score must be finite and between 0 and 10") from None
    if not math.isfinite(score) or not SCORE_MIN <= score <= SCORE_MAX:
        raise ValueError("score must be finite and between 0 and 10")
    # Do not silently round a model's apparent precision into a valid score.
    if not math.isclose(score * 10, round(score * 10), abs_tol=1e-8, rel_tol=0):
        raise ValueError("score must have at most one decimal place")
    return score


Score = Annotated[
    float,
    BeforeValidator(validate_score),
    Field(
        strict=True,
        ge=SCORE_MIN,
        le=SCORE_MAX,
        allow_inf_nan=False,
        json_schema_extra={"multipleOf": 0.1},
    ),
]


def mean_score(values: list[float | None]) -> float | None:
    measured = [validate_score(v) for v in values if v is not None]
    return round(mean(measured), 1) if measured else None


def score_scale() -> dict[str, object]:
    return {
        "version": SCORE_SCALE_VERSION,
        "range": [0, 10],
        "precision": 1,
        "missing": "unknown_not_zero",
    }


def read_historical_score(value: object, scale_version: str | None) -> float | None:
    """Normalize only identified stored units; unknown history stays unassessed.

    The database retains the original value. This is a unit conversion, not a
    claim that different historical rubrics measure equivalent competence.
    """
    if value is None or type(value) not in (int, float):
        return None
    if scale_version == "score100-legacy-v2":
        if not 0 <= value <= 100 or not math.isfinite(value):
            return None
        return round(value / 10, 1)
    if scale_version == SCORE_SCALE_VERSION:
        try:
            return validate_score(value)
        except ValueError:
            return None
    return None
