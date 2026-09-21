"""One-use, fixed-payload integration. Creates objects, never updates refs."""
import base64
import hashlib
import json
import lzma
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

ROOT = Path.cwd()
OUT = Path('/tmp/copilot-stage')
BASE = 'abca9f0bf8f524ee78905819a30daac4f2dd0432'
DIGEST = 'd8f863ec97314f6af6d838ca7b73eee74f02c007a710bc4da3cabfca1db88be4'
BRANCH = 'refactor/product-runtime-convergence'

def git(*args, binary=False):
    return subprocess.check_output(['git', *args], text=not binary).strip() if not binary else subprocess.check_output(['git', *args])

def apply():
    if os.environ['GITHUB_REPOSITORY'] != 'studyzhige-ui/Interview_Copilot' or os.environ['GITHUB_REF_NAME'] != BRANCH:
        raise SystemExit('unexpected_repository_or_branch')
    if git('rev-parse', 'HEAD^') != BASE or git('rev-parse', 'HEAD') != os.environ['GITHUB_SHA']:
        raise SystemExit('staging_base_changed')
    encoded = ''.join((ROOT / f'.github/_stage/payload{i}.txt').read_text() for i in range(7))
    decoder = lzma.LZMADecompressor(memlimit=64 * 1024 * 1024)
    raw = decoder.decompress(base64.b64decode(encoded, validate=True), max_length=126350)
    if len(raw) != 126349 or not decoder.eof or decoder.unused_data or hashlib.sha256(raw).hexdigest() != DIGEST:
        raise SystemExit('payload_integrity')
    value = json.loads(raw)
    if value['base'] != BASE or len(value['patches']) != 2:
        raise SystemExit('payload_base')
    OUT.mkdir(exist_ok=True)
    trees = [git('rev-parse', 'HEAD^{tree}')]
    for number, text in enumerate(value['patches']):
        path = OUT / f'{number+1}.patch'
        path.write_text(text)
        subprocess.run(['git', 'apply', '--check', str(path)], check=True)
        subprocess.run(['git', 'apply', '--index', str(path)], check=True)
        trees.append(git('write-tree'))
    (OUT / 'plan.json').write_text(json.dumps({'base_commit': os.environ['GITHUB_SHA'], 'trees': trees}))
    (OUT / 'stage.py').write_text(Path(__file__).read_text())
    subprocess.run(['git', 'rm', '-r', '.github/_stage', '.github/workflows/repo-patch-staging.yml'], check=True)

def capture():
    subprocess.run(['git', 'add', 'frontend/src/types/generated/shared-protocols.ts', 'frontend/contracts/shared-protocols.openapi.json'], check=True)
    data = json.loads((OUT / 'plan.json').read_text())
    data['trees'][2] = git('write-tree')
    (OUT / 'plan.json').write_text(json.dumps(data))
    subprocess.run(['git', 'diff', '--exit-code'], check=True)

def publish():
    data = json.loads((OUT / 'plan.json').read_text())
    subprocess.run(['git', 'diff', '--exit-code'], check=True)
    if git('write-tree') != data['trees'][2]:
        raise SystemExit('tree_changed_after_validation')
    prefix = 'https://api.github.com/repos/studyzhige-ui/Interview_Copilot'
    def api(path, body=None):
        req = urllib.request.Request(prefix + path, data=None if body is None else json.dumps(body).encode(), headers={
            'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
            'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28',
        }, method='GET' if body is None else 'POST')
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    ref = api('/git/ref/heads/' + BRANCH)
    if ref['object']['sha'] != data['base_commit']:
        raise SystemExit('remote_branch_changed_no_ref_updated')
    parent = data['base_commit']
    commits = []
    messages = [
        'test: handle procfs exit races without weakening cleanup gates',
        'feat(review): integrate versioned transcript corrections and verified source playback',
    ]
    for index in (1, 2):
        before, after = data['trees'][index-1:index+1]
        paths = git('diff-tree', '--no-commit-id', '--name-only', '-r', '-z', before, after, binary=True).split(b'\0')
        entries = []
        for raw_path in filter(None, paths):
            path = raw_path.decode()
            found = subprocess.run(['git', 'cat-file', '-e', f'{after}:{path}'], capture_output=True).returncode == 0
            if not found:
                entries.append({'path': path, 'mode': '100644', 'type': 'blob', 'sha': None})
                continue
            content = git('show', f'{after}:{path}', binary=True)
            if len(content) > 2_000_000:
                raise SystemExit('unexpected_file_capacity')
            expected = git('rev-parse', f'{after}:{path}')
            blob = api('/git/blobs', {'content': base64.b64encode(content).decode(), 'encoding': 'base64'})
            if blob['sha'] != expected:
                raise SystemExit('blob_identity_mismatch')
            entries.append({'path': path, 'mode': '100644', 'type': 'blob', 'sha': expected})
        tree = api('/git/trees', {'base_tree': before, 'tree': entries})
        if tree['sha'] != after:
            raise SystemExit('published_tree_identity_mismatch')
        commit = api('/git/commits', {'message': messages[index-1] + '\n\nValidated together on the exact current repository tree with the locked contract\ngenerator, backend, frontend and static gates. Model/device acceptance separate.', 'tree': after, 'parents': [parent]})
        parent = commit['sha']; commits.append(parent)
    data['commits'] = commits
    (OUT / 'result.json').write_text(json.dumps(data, indent=2))
    subprocess.run(['git', 'archive', '--format=tar.gz', '--output=/tmp/copilot-stage/source-final.tar.gz', data['trees'][2]], check=True)
    subprocess.run(['tar', '-czf', '/tmp/copilot-stage/contract-codegen-dependencies.tar.gz', '-C', 'scripts/contract_codegen', 'node_modules'], check=True)
    print(json.dumps(data))

{'apply': apply, 'capture': capture, 'publish': publish}[sys.argv[1]]()
