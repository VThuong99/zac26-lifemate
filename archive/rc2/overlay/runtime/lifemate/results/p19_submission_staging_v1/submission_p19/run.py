"""Fail-closed launcher for the frozen P19 runtime bundle."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

BUNDLE = Path(__file__).resolve().parents[1]
PINNED = {
    'models/p19.gguf': 'fc596f336207a81766df77f66a7d445d2d7371798746173176a1483a52487b46',
    'models/asr/encoder.onnx': '96b3c83c9c39afc4421f8fd2914d26b53ae837e56788a7bd5aece61580937c36',
    'models/asr/decoder.onnx': 'ea584ee86d6f74191f934f8b950013adcb2c33483785aa8b1b44fff3a7b30069',
    'models/asr/joiner.onnx': 'd146a1cff4a0060d7031e5eb91295773661bc52c356c952dd1e2759e60ffa94d',
    'models/asr/tokens.txt': 'f536d03c2e95ebd2930cf0abec88e823bd17d3c1933da7ae6a82db3b80605e15',
    'prompts/explicit_stopping.txt': '4001ff33e5d1cf5372d5eea4aafd5cfa4c2a06acc21808dd80f1314bedf7195d',
    'backend/bin/llama-server': 'aea1eaf1d40c318d99725898656268a7c382a8089289a1467e4df82ccc136f4d',
}

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def verify_bundle(bundle=BUNDLE):
    inventory = json.loads((bundle / 'SHA256.json').read_text())
    files, links = inventory['files'], inventory['symlinks']
    for name, expected in PINNED.items():
        if files.get(name) != expected:
            raise ValueError(f'frozen P19 identity mismatch in manifest: {name}')
    for name, expected in files.items():
        p = bundle / name
        if p.is_symlink() or not p.is_file() or digest(p) != expected:
            raise ValueError(f'missing or altered bundle file: {name}')
    for name, target in links.items():
        p = bundle / name
        if not p.is_symlink() or os.readlink(p) != target or not p.resolve().is_relative_to(bundle.resolve()) or not p.resolve().is_file():
            raise ValueError(f'missing or unsafe bundle symlink: {name}')
    backend = bundle / 'backend/bin'
    actual = {str(p.relative_to(bundle)) for p in backend.iterdir()}
    expected = {n for n in list(files) + list(links) if Path(n).parent.as_posix() == 'backend/bin'}
    if actual != expected:
        raise ValueError('unexpected or missing backend file')
    if {p.name for p in (bundle/'models').iterdir()} != {'p19.gguf', 'asr'}:
        raise ValueError('unexpected model or fallback in bundle')
    return len(files), len(links)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True, help='root containing the organizer split')
    p.add_argument('--split', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--server-log', type=Path, required=True)
    p.add_argument('--port', type=int, default=18108)
    p.add_argument('--limit', type=int, default=0, help='smoke only; omit for the full split')
    p.add_argument('--verify-only', action='store_true')
    a = p.parse_args()
    if a.limit < 0:
        p.error('limit must be nonnegative')
    count, links = verify_bundle()
    if a.verify_only:
        print(json.dumps({'status': 'verified', 'files': count, 'symlinks': links, 'p19_sha256': PINNED['models/p19.gguf']}))
        return
    env = os.environ.copy()
    # P19 server has a build-host RUNPATH. Force the verified bundled libraries
    # to resolve first, independent of the original build-host location.
    env.update({'LD_LIBRARY_PATH': str(BUNDLE / 'backend/bin'), 'PYTHONPATH': str(BUNDLE),
                'PYTHONHASHSEED': '20261030', 'HF_HUB_OFFLINE': '1',
                'TRANSFORMERS_OFFLINE': '1', 'TOKENIZERS_PARALLELISM': 'false',
                'PYTHONDONTWRITEBYTECODE': '1'})
    cmd = [sys.executable, '-m', 'submission_p28.run', '--root', str(a.root.resolve()),
           '--split', a.split, '--output', str(a.output.resolve()),
           '--model-dir', str(BUNDLE/'models/asr'), '--gguf', str(BUNDLE/'models/p19.gguf'),
           '--server-binary', str(BUNDLE/'backend/bin/llama-server'),
           '--prompt', str(BUNDLE/'prompts/explicit_stopping.txt'),
           '--server-log', str(a.server_log.resolve()), '--port', str(a.port), '--limit', str(a.limit)]
    os.chdir(BUNDLE)
    os.execve(sys.executable, cmd, env)

if __name__ == '__main__':
    main()
