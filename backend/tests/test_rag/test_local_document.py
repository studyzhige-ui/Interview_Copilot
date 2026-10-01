"""Owned document snapshots, CPU child boundary and exact page provenance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.rag.parsing import docling_worker as worker
from app.rag.parsing import local_document as local
from app.rag.parsing import registry, parsers


def result(digest="0" * 64):
    return {
        "contract": local.CONTRACT,
        "sha256": digest,
        "package_version": "2.118.1",
        "pages": [{"text": "# Skills\nPython", "number": 1}],
        "ocr_used": False,
        "ocr_enabled": True,
    }


@pytest.fixture
def document(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "APP_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(settings, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(settings, "PARSER_LOCAL_PYTHON", sys.executable)
    path = tmp_path / "owned.PDF"
    path.write_bytes(b"%PDF-owned-test-fixture")
    return path


def test_snapshot_keeps_format_exact_bytes_private_mode_and_bounded_lifetime(document):
    content = document.read_bytes()
    with local.snapshot(str(document), maximum=100) as (path, digest):
        assert path.suffix == ".pdf" and path.read_bytes() == content
        assert path.stat().st_mode & 0o777 == 0o400
        assert path.parent.stat().st_mode & 0o777 == 0o700
        assert digest == hashlib.sha256(content).hexdigest()
    assert not path.exists() and not path.parent.exists()


def test_replaced_source_cannot_publish_or_fall_back(document, monkeypatch):
    with pytest.raises(local.DocumentSourceChanged):
        with local.snapshot(str(document), maximum=100) as (path, _):
            original = path.read_bytes()
            document.unlink()
            document.write_bytes(b"new version")
            assert path.read_bytes() == original
    assert not path.exists()
    failed = SimpleNamespace(
        id="docling",
        tier="first_class",
        parse=lambda _: (_ for _ in ()).throw(local.DocumentSourceChanged("changed")),
    )
    fallback = SimpleNamespace(
        parse=lambda _: pytest.fail("read changed source via fallback")
    )
    with pytest.raises(local.DocumentSourceChanged):
        registry._run_candidates(str(document), [failed, fallback])


def test_snapshot_cleans_on_error_and_rejects_symlinks_and_excessive_input(document):
    with pytest.raises(RuntimeError):
        with local.snapshot(str(document), maximum=100) as (path, _):
            raise RuntimeError("failure")
    assert not path.parent.exists()
    with pytest.raises(ValueError, match="capacity"):
        with local.snapshot(str(document), maximum=1):
            pytest.fail("size bypass")
    link = document.with_name("link.pdf")
    link.symlink_to(document)
    with pytest.raises(OSError):
        with local.snapshot(str(link), maximum=100):
            pytest.fail("symlink bypass")


def test_output_preserves_page_provenance_and_runtime_without_claiming_pdf_ocr():
    parsed = local.validate_result(result(), digest="0" * 64, max_pages=5, max_text=100)
    assert [(p.number, p.text) for p in parsed.pages] == [(1, "# Skills\nPython")]
    assert not parsed.ocr_used
    assert parsed.runtime_profile == {
        "contract": local.CONTRACT,
        "device": "cpu",
        "package_version": "2.118.1",
        "ocr_enabled": True,
    }
    from app.rag.cleaning import canonicalize_document

    canonical = canonicalize_document(parsed, parser_profile={})
    assert canonical.page_spans[0].page == 1
    assert canonical.parser_profile["runtime"]["device"] == "cpu"


def test_output_identity_shape_and_finite_capacity_are_mandatory():
    mutations = [
        lambda v: v.update(sha256="1" * 64),
        lambda v: v.update(package_version="unverified"),
        lambda v: v.update(ocr_used=1),
        lambda v: v.update(pages=[]),
        lambda v: v["pages"].append({"text": "duplicate", "number": 1}),
        lambda v: v["pages"][0].update(number=True),
        lambda v: v["pages"][0].update(text="x" * 101),
        lambda v: v.update(extra="not permitted"),
    ]
    for mutate in mutations:
        value = result()
        mutate(value)
        with pytest.raises(ValueError):
            local.validate_result(value, digest="0" * 64, max_pages=5, max_text=100)


def test_docling_routes_to_owned_runner_without_sdk_import(document, monkeypatch):
    calls = []
    monkeypatch.setattr(
        local, "parse_local_document", lambda path: calls.append(path) or "parsed"
    )
    assert parsers.DoclingParser().parse(str(document)) == "parsed"
    assert calls == [str(document)]


def test_explicit_interpreter_is_not_probed_by_importing_docling(monkeypatch):
    import importlib.util

    monkeypatch.setattr(settings, "PARSER_LOCAL_PYTHON", "/prepared/python")
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda _: pytest.fail("import/probe in caller")
    )
    assert registry._docling_available()


def test_real_runner_contract_omits_credentials_and_disables_gpu(document, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-never-in-child")
    monkeypatch.setenv("DATABASE_URL", "postgresql://private")
    calls = []

    async def run(argv, **kw):
        payload = json.loads(kw["input_data"])
        assert Path(payload["source"]).read_bytes() == document.read_bytes()
        assert kw["cwd"] == Path(payload["source"]).parent
        assert argv[1:3] == ["-I", "-B"]
        assert kw["env"]["CUDA_VISIBLE_DEVICES"] == ""
        assert kw["env"]["HF_HUB_OFFLINE"] == "1"
        assert "DEEPSEEK_API_KEY" not in kw["env"] and "DATABASE_URL" not in kw["env"]
        assert "PYTHONPATH" not in kw["env"] and "HTTP_PROXY" not in kw["env"]
        calls.append(payload)
        return SimpleNamespace(
            returncode=0, stdout=json.dumps(result(payload["sha256"])).encode()
        )

    monkeypatch.setattr(local, "run_isolated", run)
    assert local.parse_local_document(str(document)).pages[0].number == 1
    assert len(calls) == 1 and not Path(calls[0]["source"]).exists()


def test_failed_child_is_reaped_before_registry_fallback_and_does_not_leak_logs(
    document, monkeypatch
):
    async def fail(*args, **kwargs):
        return SimpleNamespace(
            returncode=2, stdout=b"", stderr=b"sensitive source and model logs"
        )

    monkeypatch.setattr(local, "run_isolated", fail)
    with pytest.raises(RuntimeError, match="failed_or_assets_unavailable") as error:
        local.parse_local_document(str(document))
    assert "sensitive" not in str(error.value)
    assert not list((Path(settings.APP_DATA_DIR) / "tmp").glob("document-*"))
    # The same slot is reusable only after the prior invocation has returned.
    assert local.SLOTS.acquire(blocking=False)
    local.SLOTS.release()


def test_worker_rejects_unsupported_or_mutable_sources_before_loading_models(
    document, monkeypatch
):
    with local.snapshot(str(document), maximum=100) as (source, digest):
        monkeypatch.chdir(source.parent)
        request = {
            "contract": local.CONTRACT,
            "source": str(source),
            "sha256": digest,
            "artifacts": "/unused/models",
            "ocr": True,
            "max_input_bytes": 100,
            "max_pages": 5,
            "max_text_bytes": 100,
            "timeout": 10.0,
        }
        assert worker.validate_input(request) is request
        for change in (
            {"sha256": "1" * 64},
            {"source": "https://remote/doc.pdf"},
            {"ocr": 1},
            {"timeout": float("nan")},
            {"max_pages": True},
        ):
            with pytest.raises(ValueError):
                worker.validate_input({**request, **change})
        source.chmod(0o600)
        with pytest.raises(ValueError, match="snapshot"):
            worker.validate_input(request)


def test_worker_page_export_rejects_partial_and_overflow_without_silent_truncation(
    monkeypatch,
):
    status = SimpleNamespace(SUCCESS=object(), PARTIAL_SUCCESS=object())
    monkeypatch.setitem(
        sys.modules,
        "docling.datamodel.base_models",
        SimpleNamespace(ConversionStatus=status),
    )
    monkeypatch.setitem(
        sys.modules,
        "docling_core.types.doc",
        SimpleNamespace(ContentLayer=SimpleNamespace(BODY="body")),
    )
    document = SimpleNamespace(
        pages={1: object(), 2: object()},
        export_to_markdown=lambda **kw: "page" + str(kw["page_no"]),
    )
    data = SimpleNamespace(status=status.SUCCESS, document=document)
    policy = {"max_pages": 2, "max_text_bytes": 100}
    assert worker.export_document(data, policy) == [
        {"text": "page1", "number": 1},
        {"text": "page2", "number": 2},
    ]
    for policy in (
        {"max_pages": 1, "max_text_bytes": 100},
        {"max_pages": 2, "max_text_bytes": 1},
    ):
        with pytest.raises(ValueError, match="capacity"):
            worker.export_document(data, policy)
    data.status = status.PARTIAL_SUCCESS
    with pytest.raises(RuntimeError, match="incomplete"):
        worker.export_document(data, {"max_pages": 2, "max_text_bytes": 100})


def test_actual_fresh_worker_fails_with_content_free_error_before_model_import(
    tmp_path,
):
    complete = subprocess.run(
        [sys.executable, "-I", "-B", str(Path(worker.__file__).absolute())],
        input=b'{"invalid":"PRIVATE_DOCUMENT_TEXT"}',
        capture_output=True,
        cwd=tmp_path,
        timeout=10,
    )
    assert complete.returncode == 2
    assert complete.stdout == b""
    assert complete.stderr == b"local_document_failed\n"


def test_configured_ocr_and_cpu_limits_reach_real_adapter_contract(monkeypatch):
    status = SimpleNamespace(SUCCESS=object())
    formats = SimpleNamespace(PDF="pdf", IMAGE="image")
    monkeypatch.setitem(
        sys.modules,
        "docling.datamodel.base_models",
        SimpleNamespace(ConversionStatus=status, InputFormat=formats),
    )
    monkeypatch.setitem(
        sys.modules,
        "docling_core.types.doc",
        SimpleNamespace(ContentLayer=SimpleNamespace(BODY="body")),
    )
    monkeypatch.setitem(
        sys.modules,
        "docling.datamodel.accelerator_options",
        SimpleNamespace(AcceleratorOptions=lambda **kw: kw),
    )
    monkeypatch.setitem(
        sys.modules,
        "docling.datamodel.pipeline_options",
        SimpleNamespace(
            PdfPipelineOptions=lambda **kw: kw, RapidOcrOptions=lambda **kw: kw
        ),
    )
    calls = []

    class Converter:
        def __init__(self, **kw):
            calls.append(kw)

        def convert(self, path, **kw):
            calls.append(kw)
            return SimpleNamespace(
                status=status.SUCCESS,
                document=SimpleNamespace(
                    pages={1: object()}, export_to_markdown=lambda **kw: "source text"
                ),
            )

    monkeypatch.setitem(
        sys.modules,
        "docling.document_converter",
        SimpleNamespace(
            DocumentConverter=Converter,
            ImageFormatOption=lambda **kw: kw,
            PdfFormatOption=lambda **kw: kw,
        ),
    )
    monkeypatch.setattr(worker.importlib.metadata, "version", lambda _: "2.118.1")
    monkeypatch.setattr(worker.importlib.util, "find_spec", lambda _: object())
    monkeypatch.setattr(Path, "is_dir", lambda _: True)
    payload = {
        "source": "/private/source.png",
        "artifacts": "/read-only/models",
        "sha256": "0" * 64,
        "ocr": True,
        "max_pages": 3,
        "max_text_bytes": 100,
        "max_input_bytes": 100,
        "timeout": 15.0,
    }
    converted = worker.convert(payload)
    options = calls[0]["format_options"]["pdf"]["pipeline_options"]
    assert options["accelerator_options"] == {"device": "cpu", "num_threads": 2}
    assert (
        options["enable_remote_services"] is False
        and options["allow_external_plugins"] is False
    )
    assert options["do_ocr"] and options["ocr_options"]["backend"] == "onnxruntime"
    assert options["document_timeout"] == 15.0
    assert calls[1] == {"max_num_pages": 3, "max_file_size": 100}
    assert converted["ocr_enabled"] and converted["ocr_used"]
    calls.clear()
    converted = worker.convert({**payload, "ocr": False})
    assert not calls[0]["format_options"]["image"]["pipeline_options"]["do_ocr"]
    assert not converted["ocr_enabled"] and not converted["ocr_used"]


def test_actual_process_pipeline_uses_snapshot_and_leaves_no_temp_source(
    document, monkeypatch, tmp_path
):
    from app.core.isolated_process import run_isolated

    stub = tmp_path / "fake_document_sdk.py"
    stub.write_text(
        "import json,sys; from pathlib import Path; v=json.load(sys.stdin); "
        'assert Path(v["source"]).read_bytes().startswith(b"%PDF"); '
        'json.dump({"contract":v["contract"],"sha256":v["sha256"],"package_version":"2.118.1",'
        '"pages":[{"text":"source text","number":1}],"ocr_used":False,"ocr_enabled":False},sys.stdout)'
    )

    async def child(argv, **kw):
        return await run_isolated([*argv[:3], str(stub)], **kw)

    monkeypatch.setattr(local, "run_isolated", child)
    assert local.parse_local_document(str(document)).pages[0].text == "source text"
    assert not list((Path(settings.APP_DATA_DIR) / "tmp").glob("document-*"))


def test_source_mutation_during_failed_child_still_blocks_fallback(
    document, monkeypatch
):
    async def child(*argv, **kw):
        document.write_bytes(b"new revision during failure")
        return SimpleNamespace(returncode=2, stdout=b"")

    monkeypatch.setattr(local, "run_isolated", child)
    with pytest.raises(local.DocumentSourceChanged):
        local.parse_local_document(str(document))
