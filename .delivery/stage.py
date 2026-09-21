"""Apply one fixed, hashed document-runtime batch; never move product refs."""
import hashlib
import json
import lzma
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

REPO = "studyzhige-ui/Interview_Copilot"
BASE = "9e056e4059390f0b6ebff3031d5b5e30db2dc549"
BRANCH = "refactor/product-runtime-convergence"
DIGEST = "8d7fbd8f8b730ff3a98b5efd063de780645366d8bbff84d5bf35d1a514910140"
TREE = "7802629d2309eca9ab016c3190b21ad582b11ce3"
HOME = Path(__file__).resolve().parent
PATHS = {".env.local-first.example", "backend/app/core/config.py", "backend/app/rag/chunking.py", "backend/app/rag/cleaning.py", "backend/app/rag/documents.py", "backend/app/rag/index/identity.py", "backend/app/rag/parsing/docling_worker.py", "backend/app/rag/parsing/local_document.py", "backend/app/rag/parsing/parsers.py", "backend/app/rag/parsing/registry.py", "backend/tests/test_rag/test_chunking.py", "backend/tests/test_rag/test_local_document.py", "backend/tests/test_rag/test_parsing.py", "docs/reviews/2026-09-22-document-runtime.md", "pyproject.toml", "requirements/local-document.txt", "scripts/doctor_local.py"}

def git(*args):
    return subprocess.check_output(["git", *args]).decode().strip()

def api(method, path, data=None):
    body = None if data is None else json.dumps(data, ensure_ascii=False).encode()
    request = urllib.request.Request("https://api.github.com/repos/" + REPO + "/" + path,
        data=body, method=method, headers={"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
        "Accept": "application/vnd.github+json", "Content-Type": "application/json", "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)

def current_base():
    assert api("GET", "git/ref/heads/" + BRANCH)["object"]["sha"] == BASE, "product_branch_changed"

def prepare():
    current_base()
    compressed = b"".join((HOME / ("batch.part." + str(i))).read_bytes() for i in range(3))
    assert len(compressed) == 15800, "patch_transfer_size"
    decoder = lzma.LZMADecompressor(memlimit=256 * 1024**2)
    patch = decoder.decompress(compressed, max_length=1000001)
    assert decoder.eof and not decoder.unused_data and len(patch) == 57960, "patch_expansion_size"
    assert hashlib.sha256(patch).hexdigest() == DIGEST, "patch_transfer_hash"
    (HOME / "batch.patch").write_bytes(patch)
    git("checkout", "--detach", BASE)
    git("config", "user.name", "OpenAI")
    git("config", "user.email", "noreply@openai.com")
    git("am", "--committer-date-is-author-date", str(HOME / "batch.patch"))
    commits = git("rev-list", BASE + "..HEAD").splitlines()
    assert len(commits) == 1
    assert git("rev-parse", "HEAD^{tree}") == TREE, "source_tree_mismatch"
    assert set(git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()) == PATHS
    print("Fixed document/OCR isolation and installed grammar batch applied")

def publish():
    current_base()
    assert git("status", "--porcelain") == "", "validation_changed_source"
    assert git("rev-parse", "HEAD^{tree}") == TREE
    base_tree = api("GET", "git/commits/" + BASE)["tree"]["sha"]
    entries = []
    for path in sorted(PATHS):
        mode = git("ls-tree", "HEAD", "--", path).split()[0]
        content = subprocess.check_output(["git", "show", "HEAD:" + path]).decode("utf-8")
        entries.append({"path": path, "mode": mode, "type": "blob", "content": content})
    tree = api("POST", "git/trees", {"base_tree": base_tree, "tree": entries})
    assert tree["sha"] == TREE, "published_tree_mismatch"
    message = git("log", "-1", "--format=%B")
    saved = api("POST", "git/commits", {"message": message, "tree": TREE, "parents": [BASE]})
    result = {"base": BASE, "head": saved["sha"], "tree": TREE, "message": message, "changed_files": sorted(PATHS), "refs_updated": False}
    (HOME / "result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result))

if __name__ == "__main__":
    {"prepare": prepare, "publish": publish}[sys.argv[1]]()
