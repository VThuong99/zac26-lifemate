"""Materialize only small source files and the existing dual backend; no Docker/GPU."""
import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parent
RELEASE = ROOT / 'lifemate-release-k-20261115'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024**2), b''):
            h.update(block)
    return h.hexdigest()


def replace_once(path, old, new):
    source = path.read_text()
    if source.count(old) != 1:
        raise ValueError('Unexpected source: ' + str(path))
    path.write_text(source.replace(old, new))


def main():
    source, out = RELEASE / 'source', HERE / 'overlay'
    if (out / 'predict.py').exists():
        raise SystemExit('Candidate already prepared; refusing to overwrite')
    manifest = json.loads((source / 'manifests/source-release.json').read_text())
    for entry in manifest:
        if sha(source / entry['path']) != entry['sha256']:
            raise ValueError('Original source hash mismatch: ' + entry['path'])
    shutil.copytree(source, out, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('zaic_tools', '__pycache__', '*.pyc'))
    shutil.copy2(HERE / 'tools/schema_helpers.py', out / 'runtime/lifemate/k_schema_helpers.py')
    policies = ['schema_feedback_review_v1/policy.py', 'scoped_adapter_read_review_v1/policy.py']
    for name in policies:
        replace_once(out / 'runtime/lifemate/experiments/continuous_improvement' / name,
                     'from train.zaic_tools.validate import ', 'from k_schema_helpers import ')
    replace_once(out / 'predict.py',
                 "    if capability == (8, 0):\n        raise RuntimeError('A30 backend is unqualified: the sm_80 build changed a consequential K decision in regression; see release report')\n    target = {(12, 0): 'sm120'}.get(capability)",
                 "    # rc2 uses the existing native dual-target build on Ampere; actual A30 remains unverified.\n    # Blackwell retains the original qualified binary and CUDA library, byte for byte.\n    target = {(8, 0): 'sm80', (12, 0): 'sm120'}.get(capability)")
    replace_once(out / 'runtime/third_party/icefall-p12-3f848bb6/icefall/env.py',
                 '"IP address": socket.gethostbyname(socket.gethostname()),',
                 '"IP address": None,  # Diagnostic metadata: no DNS in offline inference.')
    dual = RELEASE / 'candidates/dual-gpu-20261116'
    binary = json.loads((dual / 'binary-manifest.json').read_text())
    for entry in binary['files']:
        if sha(dual / entry['path']) != entry['sha256']:
            raise ValueError('Dual backend hash mismatch: ' + entry['path'])
    shutil.copytree(dual / 'bin', out / 'native/sm80/bin', symlinks=True)
    native = json.loads((out / 'manifests/native.json').read_text())
    native += [{'path': 'native/sm80/' + x['path'], 'bytes': x['bytes'], 'sha256': x['sha256'],
                'in_image': True, 'transfer_permission': 'UNRESOLVED'} for x in binary['files']]
    (out / 'manifests/native.json').write_text(json.dumps(native, indent=2) + '\n')
    handoff = RELEASE / 'handoff-dual-gpu-20261116'
    # Preserve the previous training sources and include the already recovered supplement.
    subprocess.run([sys.executable, str(handoff / 'restore_training_code.py'), '--source', str(source),
                    '--output', str(out / 'training_code/restored/lifemate')], check=True)
    for name in ('TRAINING_ASSET_STATUS.json', 'TRAINING_RESTORATION.md', 'training-supplement-manifest.json'):
        shutil.copy2(handoff / name, out / 'training_code' / name)
    (out / 'FINAL_CANDIDATE.md').write_text('''# Final candidate rc2 — not yet host qualified

Original K48.46, weights, tokenizer, ASR, controller decisions, 30s watchdog and
state integrity checks are preserved. Two policy imports now use local pure
schema helpers, tested against the frozen helpers. No organizer SDK is packaged.
Mounted split ToolEnv selection and one-instance guard are unchanged.
The hostname DNS lookup is removed only from Icefall diagnostic metadata.
Capability 12.0 retains the original sm120 backend. Capability 8.0 selects the
existing dual-target native CUDA build; actual A30 execution is NOT VERIFIED.
Unsupported capabilities fail. The original notebook cells are unchanged.

training_code contains recovered source plus the 65-file restoration supplement.
Complete authorized training data/base restoration, immutable download URLs and
clean-machine reproduction remain missing. Company and organizer redistribution
permissions remain unresolved. This image must not be advertised as fully compliant.
Historical README/reports describe rc1; this addendum describes rc2 changes.
''')
    # Native/model/dependency manifests remain separately checked by verify_release.py.
    rows = []
    for path in sorted(out.rglob('*')):
        if not path.is_file() or path.is_relative_to(out / 'native') or path == out / 'manifests/source-release.json':
            continue
        rows.append({'path': str(path.relative_to(out)), 'bytes': path.stat().st_size, 'sha256': sha(path)})
        if path.suffix == '.py':
            ast.parse(path.read_bytes(), filename=str(path))
    (out / 'manifests/source-release.json').write_text(json.dumps(rows, indent=2) + '\n')
    removed = [x for x in manifest if 'zaic_tools' in Path(x['path']).parts]
    changes = []
    for x in manifest:
        p = out / x['path']
        if p.is_file() and sha(p) != x['sha256']:
            changes.append({'path': x['path'], 'before': x['sha256'], 'after': sha(p)})
    receipt = {'parent_tag': 'lifemate-k:k48.46-20261115-rc1',
               'candidate_tag': 'lifemate-k:k48.46-20261116-rc2',
               'removed_sdk_files': removed, 'changed_original_source_files': changes,
               'dual_backend_cuda_sha256': sha(out / 'native/sm80/bin/libggml-cuda.so'),
               'model_manifest_unchanged': sha(out / 'manifests/models.json') == sha(source / 'manifests/models.json'),
               'python_manifest_unchanged': sha(out / 'manifests/python-files.json') == sha(source / 'manifests/python-files.json'),
               'frozen_k_sha256': sha(ROOT / 'lifemate/submissions/submission_K.jsonl'),
               'a30_runtime_verified': False, 'docker_built': False, 'redistribution_authorized': False}
    (HERE / 'evidence/preparation.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({k: v for k, v in receipt.items() if k != 'removed_sdk_files'}, indent=2))


if __name__ == '__main__':
    main()
