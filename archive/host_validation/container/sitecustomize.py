"""Observe mounted and known legacy SDK imports; reject unknown SDK origins.

Known packaged imports remain visible as compliance failures without changing K.
"""
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path('/data/public_test/zaic_tools')
LEGACY = Path('/code/runtime/lifemate/train/zaic_tools')
_seen = set()

def audit(event, args):
    if event != 'exec':
        return
    filename = getattr(args[0], 'co_filename', '')
    if 'zaic_tools' not in Path(filename).parts or filename in _seen:
        return
    _seen.add(filename)
    path = Path(filename).resolve()
    allowed = path.is_relative_to(ROOT)
    record = {'event': 'sdk_exec', 'pid': os.getpid(), 'path': str(path), 'allowed': allowed,
              'legacy_packaged_sdk': path.is_relative_to(LEGACY),
              'sha256': hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None}
    with open(f'/result/sdk-imports.{os.getpid()}.jsonl', 'a') as f:
        f.write(json.dumps(record) + '\n')
        f.flush()
    if not allowed and not path.is_relative_to(LEGACY):
        raise RuntimeError('SDK code originates outside mounted split: ' + str(path))

sys.addaudithook(audit)
# Receipt confirms sitecustomize was discovered; SDK exec events are required separately.
with open(f'/result/sdk-imports.{os.getpid()}.jsonl', 'a') as f:
    f.write(json.dumps({'event': 'audit_installed', 'pid': os.getpid()}) + '\n')
