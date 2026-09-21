"""Apply a fixed, hashed three-commit batch; publish objects, never branch refs."""
import hashlib
import json
import lzma
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

REPO = "studyzhige-ui/Interview_Copilot"
BASE = "69c2393685142378fa3f4776b677e002f2ceec63"
BRANCH = "refactor/product-runtime-convergence"
DIGEST = "6b74fd19c759d0df04fe15ae1f211906cb2b3f07ad4e4b080653bb840af84480"
TREES = ["221ff38a3b2fd1c6b5fbd20bad0e6e60b8b210d7", "fc62d61fb6238f236ffd8a461ec5136572c3cda4", "df3b42e151af4f6f93571d66bb423a61f969427c"]
HOME = Path(__file__).resolve().parent

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
    assert len(compressed) == 23304, "patch_transfer_size"
    decoder = lzma.LZMADecompressor(memlimit=256 * 1024**2)
    patch = decoder.decompress(compressed, max_length=1000001)
    assert decoder.eof and not decoder.unused_data and len(patch) == 100572, "patch_expansion_size"
    assert hashlib.sha256(patch).hexdigest() == DIGEST, "patch_transfer_hash"
    (HOME / "batch.patch").write_bytes(patch)
    git("checkout", "--detach", BASE)
    git("config", "user.name", "OpenAI")
    git("config", "user.email", "noreply@openai.com")
    git("am", "--committer-date-is-author-date", str(HOME / "batch.patch"))
    commits = git("rev-list", "--reverse", BASE + "..HEAD").splitlines()
    assert len(commits) == 3
    assert [git("rev-parse", c + "^{tree}") for c in commits] == TREES, "source_tree_mismatch"
    (HOME / "local-commits.json").write_text(json.dumps(commits))
    print("Fixed preparation, mutation and preflight batch applied to exact product baseline")

def publish():
    current_base()
    assert git("status", "--porcelain") == "", "validation_changed_tracked_or_untracked_source"
    commits = json.loads((HOME / "local-commits.json").read_text())
    parent, previous = BASE, BASE
    result = []
    for commit, expected_tree in zip(commits, TREES, strict=True):
        base_tree = api("GET", "git/commits/" + parent)["tree"]["sha"]
        paths = git("diff-tree", "--no-commit-id", "--name-only", "--no-renames", "-r", previous, commit).splitlines()
        entries = []
        for path in paths:
            assert path.startswith(("backend/", "frontend/", "scripts/", "docs/")), "unexpected_product_path"
            mode = git("ls-tree", commit, "--", path)
            if not mode:
                entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
                continue
            content = subprocess.check_output(["git", "show", commit + ":" + path]).decode("utf-8")
            entries.append({"path": path, "mode": mode.split()[0], "type": "blob", "content": content})
        tree = api("POST", "git/trees", {"base_tree": base_tree, "tree": entries})
        assert tree["sha"] == expected_tree, "published_tree_mismatch"
        message = git("log", "-1", "--format=%B", commit)
        saved = api("POST", "git/commits", {"message": message, "tree": tree["sha"], "parents": [parent]})
        result.append({"sha": saved["sha"], "tree": tree["sha"], "parent": parent, "message": message, "changed_files": paths})
        previous, parent = commit, saved["sha"]
    (HOME / "result.json").write_text(json.dumps({"base": BASE, "head": parent, "commits": result, "refs_updated": False}, indent=2))
    print(json.dumps({"head_object": parent, "refs_updated": False}))

if __name__ == "__main__":
    {"prepare": prepare, "publish": publish}[sys.argv[1]]()
