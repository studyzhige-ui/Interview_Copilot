import io
import math
from dataclasses import replace

import pytest

from app.local_inference.protocol import (
    frame,
    loads,
    read_sync,
    request,
    validate_values,
)
from app.local_inference.config import BrokerConfig
from .conftest import task


def test_roundtrip_and_partial_payload(specs):
    value = task(specs[0])
    assert request(read_sync(io.BytesIO(frame(value)))) == value
    with pytest.raises(ValueError):
        read_sync(io.BytesIO(frame(value)[:-1]))


@pytest.mark.parametrize(
    "raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b"\xff", b"[]" * 100]
)
def test_invalid_json(raw):
    with pytest.raises(ValueError):
        loads(raw)


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", True),
        ("version", 2),
        ("id", "bad"),
        ("binding", "bad"),
        ("timeout", True),
        ("timeout", float("nan")),
        ("texts", []),
        ("texts", [" "]),
        ("texts", ["x"] * 33),
        ("query", True),
        ("operation", "shell"),
        ("priority", "arbitrary"),
    ],
)
def test_strict_request(specs, field, value):
    with pytest.raises((ValueError, TypeError)):
        request({**task(specs[0]), field: value})


@pytest.mark.parametrize(
    "values",
    [[[0, 0, 0]], [[1, 2]], [[1, True, 2]], [[1, math.inf, 2]], [[1, "2", 3]], []],
)
def test_bad_model_outputs(values):
    with pytest.raises(ValueError):
        validate_values(values, role="embedding", count=1, dimension=3)


def test_negative_reranker_score_is_not_a_ten_point_rating():
    assert validate_values([-5.2, 3.6], role="reranking", count=2, dimension=1) == [
        -5.2,
        3.6,
    ]


def test_semantic_binding_includes_prefix_and_not_device(specs):
    a = specs[0]
    assert replace(a, device="cuda").binding == a.binding
    assert replace(a, query_prefix="instruction").binding != a.binding
    assert replace(a, revision="a" * 40).binding != a.binding
    assert replace(a, dimension=4).binding != a.binding


def test_config_rejects_duplicate_models_and_insufficient_reservation(config, specs):
    with pytest.raises(ValueError):
        replace(config, models=(specs[0], specs[0]))
    with pytest.raises(ValueError):
        replace(config, capacity_mib=1)
    with pytest.raises(ValueError):
        replace(config, cache_root=specs[0].model_path + "/cache")
    with pytest.raises(ValueError):
        replace(specs[1], dimension=3)


def test_config_roundtrip(config, tmp_path):
    import json

    file = tmp_path / "config.json"
    file.write_text(json.dumps(config.as_dict()))
    assert BrokerConfig.load(file) == config


def test_unknown_rejection_code_is_not_refundable(specs):
    from app.local_inference.client import checked_response, LocalInferenceUnknown

    req = task(specs[0])
    with pytest.raises(LocalInferenceUnknown):
        checked_response(
            req,
            {
                "id": req["id"],
                "binding": req["binding"],
                "status": "rejected",
                "code": "really_already_ran",
            },
            3,
        )


def test_oversized_config_is_rejected_even_with_valid_prefix(config, tmp_path):
    import json

    file = tmp_path / "large.json"
    file.write_text(json.dumps(config.as_dict()) + " " * 65537)
    with pytest.raises(ValueError):
        BrokerConfig.load(file)
