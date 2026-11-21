"""Real Linux flock/process regressions; no Docker, GPU or host process signals."""
import copy
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'tools'))
import candidate as C


def await_file(path, timeout=5):
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() >= deadline:
            raise AssertionError('Timed out waiting for CPU fixture: ' + str(path))
        time.sleep(.01)


class LockProcessTests(unittest.TestCase):
    def run_fixture(self, old):
        source = HERE / ('evidence/lock-before/host.sh' if old else 'host.sh')
        script = source.read_text()
        cleanup = 'cleanup() {' + script.split('cleanup() {', 1)[1].split('\ntrap ', 1)[0]
        launch = next(line for line in script.splitlines()
                      if line.startswith('python3 "$ROOT/lifemate-host-validation/monitor_resources.py"'))
        # Redirect fixture output so a lingering child cannot hold communicate() open.
        launch = launch.removesuffix(' &') + ' >/dev/null 2>&1 &'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'lifemate-host-validation').mkdir()
            monitor = root / 'lifemate-host-validation/monitor_resources.py'
            monitor.write_text('''import json,os,signal,sys,time
from pathlib import Path
out=Path(sys.argv[3])
def stop(*args):
    deadline=time.monotonic()+5
    while not out.with_suffix('.allow_exit').exists() and time.monotonic()<deadline: time.sleep(.01)
    out.with_suffix('.stopped').write_text('stopped')
    raise SystemExit(0)
signal.signal(signal.SIGTERM,stop)
fds=[]
for fd in (8,9):
    try: os.fstat(fd);fds.append(fd)
    except OSError: pass
out.with_suffix('.ready').write_text(json.dumps(fds))
while True: signal.pause()
''')
            program = '''set -euo pipefail
ROOT=$1; RUN=$1; CID=''; GPU=0; GPU_UUID=fixture; CLEANED=0; MONITOR=''
nvidia-smi() { :; }
exec 8> "$ROOT/stage.lock"
exec 9> "$ROOT/gpu.lock"
flock -n 8
flock -n 9
''' + cleanup + '\n' + launch + '''
MONITOR=$!
python3 - "$RUN/resources.ready" "$RUN/start_cleanup" <<'PY'
import sys,time
from pathlib import Path
deadline=time.monotonic()+5
while not all(Path(p).exists() for p in sys.argv[1:]):
 if time.monotonic()>deadline: raise SystemExit(2)
 time.sleep(.01)
PY
cleanup
'''
            process = subprocess.Popen(['/bin/bash', '-c', program, 'fixture', str(root)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                await_file(root / 'resources.ready')
                fds = json.loads((root / 'resources.ready').read_text())
                self.assertEqual(fds, [8, 9] if old else [])
                for name in ('stage.lock', 'gpu.lock'):
                    with (root / name).open('a') as lock:
                        with self.assertRaises(BlockingIOError):
                            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if not old:
                    (root / 'resources.allow_exit').touch()
                (root / 'start_cleanup').touch()
                out, error = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, (out, error))
                if old:
                    # Parent exited but its exact monitor still owns both inherited locks.
                    for name in ('stage.lock', 'gpu.lock'):
                        with (root / name).open('a') as lock:
                            with self.assertRaises(BlockingIOError):
                                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    (root / 'resources.allow_exit').touch()
                    await_file(root / 'resources.stopped')
                else:
                    self.assertTrue((root / 'resources.stopped').exists(), 'cleanup did not reap monitor')
                    for name in ('stage.lock', 'gpu.lock'):
                        with (root / name).open('a') as lock:
                            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                (root / 'resources.allow_exit').touch()
                (root / 'start_cleanup').touch()
                process.communicate(timeout=6)

    def test_original_cleanup_reproduces_inherited_lock_after_parent_exit(self):
        self.run_fixture(old=True)

    def test_corrected_cleanup_reaps_monitor_and_releases_both_locks(self):
        self.run_fixture(old=False)

    def test_active_owner_is_not_bypassed_or_unlinked(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lock'
            with path.open('a') as owner:
                inode = path.stat().st_ino
                fcntl.flock(owner, fcntl.LOCK_EX)
                result = subprocess.run(['flock', '-w', '.1', str(path), 'true'], timeout=2)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(path.stat().st_ino, inode)
                fcntl.flock(owner, fcntl.LOCK_UN)
            self.assertEqual(subprocess.run(['flock', '-n', str(path), 'true']).returncode, 0)


class EvidenceReuseTests(unittest.TestCase):
    def test_preserved_gpu_receipt_and_build_validate_under_host_only_correction(self):
        self.assertTrue(C.completed('gpu'))
        with tempfile.TemporaryDirectory() as directory, patch.object(C, 'HERE', Path(directory)):
            self.assertFalse(C.completed('smoke'))
        correction = C.read(HERE / 'evidence/lock-correction.json')
        self.assertEqual(C.V.sha(HERE / 'BUILD.json'), correction['preserved_build_sha256'])

    def test_changes_outside_lock_fix_allowlist_fail(self):
        original_sha = C.V.sha
        for relative in ('overlay/predict.py', 'container/preflight.py', 'tools/package.py',
                         'BUILD.json', 'runs/20261116T142101Z-gpu-qtxYSa/report.json'):
            def changed(path):
                return '0' * 64 if Path(path) == HERE / relative else original_sha(path)
            with self.subTest(file=relative), patch.object(C, 'check_context', return_value='corrected-fixture'), \
                    patch.object(C.V, 'sha', side_effect=changed), self.assertRaises(ValueError):
                C.check_build_context(C.read(HERE / 'BUILD.json'))

    def test_invalid_stage_or_receipt_cannot_be_reused(self):
        original_read = C.read
        for change in ('report_hash', 'build_hash', 'stage', 'pass'):
            def altered(path):
                value = copy.deepcopy(original_read(path))
                if Path(path) == HERE / 'evidence/gpu-pass.json':
                    if change == 'report_hash': value['report_sha256'] = '0' * 64
                    if change == 'build_hash': value['build_sha256'] = '0' * 64
                if Path(path) == HERE / 'runs/20261116T142101Z-gpu-qtxYSa/report.json':
                    if change == 'stage': value['stage'] = 'smoke'
                    if change == 'pass': value['selected_stage_pass'] = False
                return value
            with self.subTest(change=change), patch.object(C, 'read', side_effect=altered), \
                    self.assertRaises(ValueError):
                C.completed('gpu')

    def test_resume_skips_valid_gpu_and_stops_on_corrupt_receipt(self):
        script = (HERE / 'host.sh').read_text()
        block = script.split('if [[ "$MODE" == resume ]]; then', 1)[1].split('\nfi', 1)[0]
        for return_code in (0, 2):
            program = ('set -euo pipefail\nHERE=/fixture; GPU=0\n'
                       'bash() { echo "stage:$2"; }\n'
                       'python3() { if [[ "$3" == gpu ]]; then return ' + str(return_code) + '; fi; return 1; }\n' + block)
            result = subprocess.run(['/bin/bash', '-c', program], text=True, capture_output=True)
            stages = [line for line in result.stdout.splitlines() if line.startswith('stage:')]
            self.assertEqual(stages, ['stage:verify'] if return_code == 2 else
                             ['stage:verify', 'stage:smoke', 'stage:pilot', 'stage:notebook', 'stage:package'])
            self.assertEqual(result.returncode, return_code)


if __name__ == '__main__':
    unittest.main()
