from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_cloud_runtime_does_not_import_community_ml_stack() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    env = {
        **os.environ,
        "APP_EDITION": "cloud",
        "EMBEDDING_PROVIDER": "siliconflow",
        "EMBEDDING_MODEL": "BAAI/bge-m3",
        "RERANKER_PROVIDER": "siliconflow",
        "RERANKER_MODEL": "BAAI/bge-reranker-v2-m3",
        "TRANSCRIPTION_PROVIDER": "siliconflow",
        "SILICONFLOW_API_KEY": "boundary-test",
        "SECRET_KEY": "boundary-test-secret",
        "LANGSMITH_TRACING": "false",
    }
    code = """
import importlib.abc
import importlib.util
import sys

blocked = {
    "torch", "torchvision", "torchaudio", "whisperx",
    "sentence_transformers", "docling", "rapidocr_onnxruntime",
    "llama_index.embeddings.huggingface",
    "llama_index.postprocessor.sbert_rerank",
}
def is_blocked(name):
    return any(name == root or name.startswith(root + ".") for root in blocked)

real_find_spec = importlib.util.find_spec
def dependency_probe(name, package=None):
    return None if is_blocked(name) else real_find_spec(name, package)
importlib.util.find_spec = dependency_probe

class BlockCommunityImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if is_blocked(fullname):
            raise ModuleNotFoundError(fullname)
        return None
sys.meta_path.insert(0, BlockCommunityImports())

import app.main
from app.rag.embedding_registry import build_embedding
from app.rag.reranker_registry import build_reranker
from app.services.voice.transcription_registry import resolve_transcription

build_embedding()
build_reranker(top_n=5)
assert resolve_transcription().provider_id == "siliconflow"
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
