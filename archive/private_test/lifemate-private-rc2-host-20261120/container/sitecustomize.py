"""RC2 host-test observer, with only the SDK root changed to Private Test."""
import hashlib
import json
import os
from pathlib import Path
import sys
import sysconfig

SDK = Path('/data/private_test/zaic_tools')
STDLIB = Path(sysconfig.get_path('stdlib'))
SEEN = set()


def record(row):
    row['pid'] = os.getpid()
    with open(f'/result/sdk-imports.{os.getpid()}.jsonl', 'a') as stream:
        stream.write(json.dumps(row) + '\n')


def environment_reader(frame, sdk=SDK):
    """The first non-stdlib caller of an environment open must be the SDK."""
    while frame:
        filename = frame.f_code.co_filename
        if not filename.startswith('<'):
            origin = Path(filename).resolve()
            if origin.is_relative_to(sdk):
                return True, str(origin)
            if not origin.is_relative_to(STDLIB):
                return False, str(origin)
        frame = frame.f_back
    return False, None


def audit(event, args):
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
        path = Path(os.fsdecode(args[0]))
        if any(part.endswith('_environment') for part in path.parts):
            allowed, origin = environment_reader(sys._getframe(1))
            record({'event': 'environment_open', 'allowed': allowed, 'caller': origin,
                    'path': str(path)})  # Path only; never state contents.
            if not allowed:
                raise RuntimeError('Environment file access outside mounted SDK: ' + str(origin))
    if event != 'exec':
        return
    filename = getattr(args[0], 'co_filename', '')
    if 'zaic_tools' not in Path(filename).parts or filename in SEEN:
        return
    SEEN.add(filename)
    path = Path(filename).resolve()
    allowed = path.is_relative_to(SDK)
    record({'event': 'sdk_exec', 'path': str(path), 'allowed': allowed,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None})
    if not allowed:
        raise RuntimeError('SDK code outside mounted split: ' + str(path))


sys.addaudithook(audit)
record({'event': 'audit_installed'})
