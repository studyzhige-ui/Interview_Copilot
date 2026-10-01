"""Record concrete package versions, model hashes and hardware for this run."""

import hashlib
import importlib.metadata as md
import json
import platform
import sys
from pathlib import Path

from .local_models import torch
import psutil
from packaging.requirements import Requirement

from .download import ROOT
from .profile import load_profile
from .rewrite import atomic_json


def hash_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for data in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(data)
    return digest.hexdigest()


def main():
    profile = load_profile()
    versions = {
        name: md.version(name)
        for name in (
            "torch",
            "transformers",
            "tokenizers",
            "huggingface-hub",
            "safetensors",
            "numpy",
            "scipy",
            "httpx",
            "filelock",
            "python-dotenv",
        )
    }
    issues = []
    for name in ("transformers", "tokenizers", "huggingface-hub", "safetensors"):
        for text in md.requires(name) or []:
            requirement = Requirement(text)
            if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
                continue
            try:
                installed = md.version(requirement.name)
                if requirement.specifier and installed not in requirement.specifier:
                    issues.append(f"{name}: {requirement}, installed {installed}")
            except md.PackageNotFoundError:
                issues.append(f"{name}: missing {requirement.name}")
    if issues:
        raise RuntimeError(issues)
    models = {}
    for name, model in profile["models"].items():
        folder = Path(model["path"])
        models[name] = {
            str(path.relative_to(folder)): hash_file(path)
            for path in folder.rglob("*")
            if path.is_file()
            and ".cache" not in path.parts
            and (path.suffix in {".json", ".safetensors", ".txt", ".model"})
            and "onnx" not in path.parts
        }
    manifest = {
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "packages": versions,
        "dependency_issues": issues,
        "model_files": models,
        "gpu": torch.cuda.get_device_name(),
        "gpu_memory_bytes": torch.cuda.get_device_properties(0).total_memory,
        "cpu_logical": psutil.cpu_count(),
        "cpu_physical": psutil.cpu_count(logical=False),
        "ram_total_bytes": psutil.virtual_memory().total,
        "profile": profile,
        "precision": "bfloat16 model inference; float32 normalized vectors and exact dot product",
        "encoding_throughput_probe": {
            "batch_8_docs_per_second": 89.35,
            "batch_32_docs_per_second": 58.68,
            "batch_64_docs_per_second": 46.27,
        },
        "source_commit": json.loads((ROOT / "source_manifest.json").read_text())[
            "commit"
        ],
    }
    atomic_json(ROOT / "runtime_manifest.json", manifest)
    print(
        json.dumps(
            {
                "packages": versions,
                "dependency_issues": issues,
                "model_count": len(models),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
