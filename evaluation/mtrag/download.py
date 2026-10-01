"""Download a pinned IBM release; preserve file hashes and original files."""

import concurrent.futures
import hashlib
import json
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2] / "data/evaluation/mtrag"
PINNED_COMMIT = "2c618bb98db3c8526433e22d8a2f7320f10a7470"


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    tree_path = ROOT / "upstream_tree.json"
    if not tree_path.exists():
        response = httpx.get(
            f"https://api.github.com/repos/IBM/mt-rag-benchmark/git/trees/{PINNED_COMMIT}?recursive=1",
            timeout=60,
        )
        response.raise_for_status()
        tree_path.write_text(
            json.dumps({"commit": PINNED_COMMIT, "tree": response.json()}),
            encoding="utf-8",
        )
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    commit = tree["commit"]
    if commit != PINNED_COMMIT or tree["tree"].get("truncated"):
        raise ValueError("Expected a complete tree at the pinned upstream revision")
    selected = []
    for item in tree["tree"]["tree"]:
        path = item["path"]
        if item["type"] != "blob":
            continue
        if (
            path.startswith("corpora/passage_level/")
            or path
            in {
                "LICENSE",
                "README.md",
                "corpora/README.md",
                "mtrag-human/README.md",
                "mtragun-human/README.md",
            }
            or (
                path.startswith(("mtrag-human/", "mtragun-human/"))
                and (
                    path.endswith("generation_tasks/reference.jsonl")
                    or ("retrieval_tasks/" in path and path.endswith(".tsv"))
                    or path.endswith("_lastturn.jsonl")
                )
            )
        ):
            selected.append(item)

    def download(item):
        path = ROOT / "upstream" / item["path"]
        url = f"https://raw.githubusercontent.com/IBM/mt-rag-benchmark/{commit}/{item['path']}"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.stat().st_size != item["size"]:
            temporary = path.with_suffix(path.suffix + ".part")
            with httpx.stream(
                "GET", url, timeout=120, follow_redirects=True
            ) as response:
                response.raise_for_status()
                with temporary.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
            if temporary.stat().st_size != item["size"]:
                raise ValueError(f"Download size mismatch: {item['path']}")
            temporary.replace(path)
        data = path.read_bytes()
        git_hash = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        if git_hash != item["sha"]:
            raise ValueError(f"Git blob mismatch: {item['path']}")
        print("verified", item["path"], len(data), flush=True)
        return {
            "path": item["path"],
            "url": url,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": git_hash,
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        files = list(pool.map(download, selected))
    (ROOT / "source_manifest.json").write_text(
        json.dumps({"commit": commit, "files": files}, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
