"""Local snapshot checks follow the files each model module actually needs."""

import json

import pytest

from app.core.model_assets import inspect_directory


@pytest.mark.parametrize(
    "module,folder,valid",
    [
        ("sentence_transformers.models.Normalize", "2_Normalize", True),
        ("sentence_transformers.models.Pooling", "1_Pooling", False),
        ("sentence_transformers.models.Normalize", "../outside", False),
    ],
)
def test_stateless_normalization_does_not_require_a_weight_directory(
    tmp_path, module, folder, valid
):
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "pytorch_model.bin").write_bytes(b"test-layout-only")
    (tmp_path / "tokenizer.json").write_text("{}", encoding="utf-8")
    (tmp_path / "modules.json").write_text(
        json.dumps(
            [
                {"path": "", "type": "sentence_transformers.models.Transformer"},
                {"path": folder, "type": module},
            ]
        ),
        encoding="utf-8",
    )
    result = inspect_directory("test/model", tmp_path)
    assert result.loadable_candidate is valid


def test_docling_setup_detects_an_old_ocr_bundle_before_offline_use(
    tmp_path, monkeypatch
):
    from scripts import init_models
    from types import SimpleNamespace

    monkeypatch.setattr(init_models, "DOCLING_MODELS_DIR", tmp_path)
    monkeypatch.setattr(
        init_models,
        "inspect_directory",
        lambda *_: SimpleNamespace(loadable_candidate=True),
    )
    monkeypatch.setattr(init_models.settings, "RAG_OCR_ENABLED", True)
    # A structurally valid historical bundle does not contain the current OCR set.
    assert not init_models.is_docling_downloaded()
    (tmp_path / "RapidOcr").mkdir()
    for name in (
        "PP-OCRv6_det_small.onnx",
        "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
        "PP-OCRv6_rec_small.onnx",
    ):
        (tmp_path / "RapidOcr" / name).write_bytes(b"fixture-layout")
    assert init_models.is_docling_downloaded()
