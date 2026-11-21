"""CPU-only path regression tests; Docker/GPU processes are forbidden."""
from contextlib import ExitStack, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import check_results as checks
import run_private_test as host


class OutputDirectory(unittest.TestCase):
    def test_default_uses_invoking_host_home(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(host.Path, 'home', return_value=Path(temp)):
            result = host.prepare_output_dir()
            self.assertEqual(result, Path(temp) / 'lifemate-private-rc2-results')
            self.assertTrue(result.is_dir())

    def test_explicit_tilde_path_is_resolved(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(host.os.environ, {'HOME': temp}):
            result = host.prepare_output_dir('~/custom results')
            self.assertEqual(result, Path(temp) / 'custom results')
            self.assertTrue(result.is_dir())

    def test_unsafe_mount_path_rejected_before_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            for name in ('bad,path', 'bad\npath'):
                with self.subTest(name=name):
                    path = Path(temp) / name
                    with self.assertRaisesRegex(RuntimeError, 'Unsupported comma/newline'):
                        host.prepare_output_dir(path)
                    self.assertFalse(path.exists())

    def test_unwritable_output_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(host.os, 'access', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'Host user cannot write --output-dir'):
                host.prepare_output_dir(temp)

    def test_smoke_then_full_outside_unwritable_workspace(self):
        self.check_smoke_then_full()

    def test_cuda_compat_reaches_preflight_smoke_full_and_reports(self):
        self.check_smoke_then_full(cuda_compat=True)

    def test_cuda_compat_cannot_bypass_failed_preflight(self):
        for success, ok in ((False, True), (True, False)):
            with self.subTest(preflight_success=success, container_ok=ok):
                self.check_smoke_then_full(cuda_compat=True, preflight_success=success, preflight_ok=ok)

    def check_smoke_then_full(self, *, cuda_compat=False, preflight_success=True, preflight_ok=True):
        # Exercise real orchestration, mounts, evidence sealing, smoke approval
        # checks and publication. Replace only external execution and inference
        # evidence with explicitly synthetic fixtures in a temporary directory.
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            workspace = Path(temp) / 'workspace'
            (workspace / 'lifemate-final-20261116-rc2').mkdir(parents=True)
            dataset_zip = workspace / 'lifemate/docs/organizer/private_test.zip'
            dataset_zip.parent.mkdir(parents=True)
            dataset_zip.write_bytes(b'CPU TEST FIXTURE, NOT A DATASET')
            output = Path(temp) / 'host home/lifemate-private-rc2-results'
            original_open, original_access = Path.open, host.os.access
            original_lock, original_run_container = host.lock, host.run_container
            before = sorted(str(p.relative_to(workspace)) for p in workspace.rglob('*'))
            captured = []

            def read_only_workspace(path, mode='r', *args, **kwargs):
                if Path(path).is_relative_to(workspace) and any(x in mode for x in 'wax+'):
                    raise AssertionError('Attempted workspace write: ' + str(path))
                return original_open(path, mode, *args, **kwargs)

            def writable(path, mode):
                return False if Path(path).is_relative_to(workspace) else original_access(path, mode)

            def output_lock(path):
                self.assertTrue(path.is_relative_to(output))
                return original_lock(path)

            def disk_usage(path):
                self.assertEqual(path, output)
                return SimpleNamespace(free=100 * 1024**3)

            def metadata_command(argv, **kwargs):
                if argv == ['docker', 'info', '--format', '{{json .}}']:
                    return SimpleNamespace(stdout=json.dumps({'OSType': 'linux', 'NCPU': 16,
                        'MemTotal': 64 * 1024**3, 'DockerRootDir': '/unused-fixture'}))
                self.assertIn(argv, (['docker', 'version'], ['nvidia-smi']))
                return SimpleNamespace(stdout='CPU TEST FIXTURE\n')

            def extracted_fixture(zip_path, run):
                self.assertEqual(zip_path, dataset_zip)
                self.assertTrue(run.is_relative_to(output))
                split = run / 'dataset/private_test'
                split.mkdir(parents=True)
                return split, [{'id': f'fixture_{i:04d}'} for i in range(625)], {}

            class CapturedCreate(Exception):
                pass

            def container_fixture(run, name, cmd, deadline, identity, split, harness, gpu, **options):
                # Real argument generation runs until the first command boundary.
                # It cannot create or start an actual Docker container.
                with patch.object(host, 'command', side_effect=CapturedCreate) as create:
                    with self.assertRaises(CapturedCreate):
                        original_run_container(run, name, cmd, deadline, identity, split, harness, gpu, **options)
                argv = create.call_args.args[0]
                stage = run / name
                self.assertEqual(argv[:3], ['docker', 'create', '--pull=never'])
                self.assertNotIn('--entrypoint', argv)
                self.assertEqual(argv[argv.index(host.MANIFEST) + 1:], cmd)
                self.assertEqual(argv[argv.index('--user') + 1], '1003:1003')
                self.assertEqual(argv[argv.index('--gpus') + 1], 'device=GPU-cpu-test')
                env = [argv[i + 1] for i, v in enumerate(argv) if v == '--env']
                overrides = [v for v in env if v.startswith('NVIDIA_DISABLE_REQUIRE')]
                self.assertEqual(overrides, ['NVIDIA_DISABLE_REQUIRE=true'] if cuda_compat else [])
                self.assertEqual([argv[i + 1] for i, v in enumerate(argv) if v == '--mount'], [
                    f'type=bind,src={split},dst=/data/private_test,readonly',
                    f'type=bind,src={stage},dst=/result',
                    f'type=bind,src={harness},dst=/validation,readonly'])
                self.assertTrue(all(p.is_relative_to(output) for p in (split, stage, harness)))
                captured.append((name, cmd))
                if name == 'preflight':
                    self.assertEqual(cmd, ['python3', '/validation/preflight.py'])
                    checks.write(stage / 'preflight.json', {'success': preflight_success})
                else:
                    (stage / 'submission.jsonl').write_text('CPU TEST FIXTURE, NOT PREDICTIONS\n')
                return stage, preflight_ok if name == 'preflight' else True, {'wall_seconds': 1}

            def analyzed_fixture(stage, cases, split, manifest):
                return {'issues': [], 'warnings': [], 'tool_calls': len(cases),
                        'expected': len(cases), 'processed': len(cases), 'finished': len(cases),
                        'step_limit_requests': 0, 'timeouts': 0, 'failed_receipts': 0, 'timing': {},
                        'jsonl_sha256': checks.sha(stage / 'submission.jsonl')}

            stack.enter_context(patch.object(Path, 'open', read_only_workspace))
            # A host environment variable alone must not enable compatibility.
            stack.enter_context(patch.dict(host.os.environ, {'NVIDIA_DISABLE_REQUIRE': 'true'}))
            for obj, name, value in (
                (host, 'ensure_host', lambda: None),
                (host, 'local_docker_endpoint', lambda: 'unix:///cpu-test-fixture'),
                (host, 'command', metadata_command),
                (host, 'lock', output_lock),
                (host.os, 'access', writable),
                (host.os, 'getuid', lambda: 1003),
                (host.os, 'getgid', lambda: 1003),
                (host.shutil, 'disk_usage', disk_usage),
                (host, 'load_verifier', lambda w: (None, {}, {'archive': 'fixture.tar.gz'}, {})),
                (host, 'verify_archive', lambda *a: {}),
                (host, 'get_loaded', lambda *a: {'image_id': host.MANIFEST,
                    'entrypoint': ['/opt/nvidia/nvidia_entrypoint.sh']}),
                (host, 'check_gpu', lambda g: {'uuid': 'GPU-cpu-test', 'driver': 'fixture'}),
                (host, 'extract_dataset', extracted_fixture),
                (host, 'run_container', container_fixture),
                (host, 'analyze', analyzed_fixture),
            ):
                stack.enter_context(patch.object(obj, name, value))
            stack.enter_context(patch.object(host.subprocess, 'run', side_effect=AssertionError('No processes allowed')))
            stack.enter_context(patch.object(host.subprocess, 'Popen', side_effect=AssertionError('No processes allowed')))
            terminal = stack.enter_context(redirect_stdout(io.StringIO()))
            args = ['--workspace', str(workspace), '--output-dir', str(output), '--gpu', '0']
            if cuda_compat:
                args += ['--cuda-compat']
            if not preflight_success or not preflight_ok:
                self.assertEqual(host.main(['smoke', *args]), 2)
                report_path, = output.glob('*/REPORT.json')
                report = checks.read(report_path)
                self.assertFalse(report['smoke_pass'])
                self.assertFalse(report['output_created'])
                self.assertTrue(report['cuda_compat'])
                self.assertIn('preflight failed', report['error'])
                self.assertEqual([name for name, cmd in captured], ['preflight'])
                self.assertFalse((output / 'private_test_k48_46_rc2.jsonl').exists())
                return
            self.assertEqual(host.main(['smoke', *args]), 0)
            smoke_report_path, = output.glob('*/REPORT.json')
            smoke = checks.read(smoke_report_path)
            self.assertTrue(smoke['smoke_pass'])
            self.assertEqual(smoke['validation']['processed'], 3)
            final = output / 'private_test_k48_46_rc2.jsonl'
            self.assertFalse(final.exists())
            opposite_args = [a for a in args if a != '--cuda-compat'] if cuda_compat else args + ['--cuda-compat']
            with self.assertRaisesRegex(RuntimeError, 'CUDA compatibility mode changed since smoke'):
                host.main(['full', *opposite_args, '--smoke-run', str(smoke_report_path.parent)])
            self.assertEqual([name for name, cmd in captured], ['preflight', 'inference'])
            self.assertEqual(host.main(['full', *args, '--smoke-run', str(smoke_report_path.parent)]), 0)
            reports = [checks.read(p) for p in output.glob('*/REPORT.json')]
            full, = [r for r in reports if r['mode'] == 'full']
            self.assertTrue(full['output_created'])
            self.assertEqual(full['validation']['processed'], 625)
            self.assertEqual(full['requested_output'], str(final))
            self.assertEqual(checks.sha(final), full['output_sha256'])
            self.assertEqual(final.stat().st_ino, (Path(full['run']) / 'inference/submission.jsonl').stat().st_ino)
            for report in reports:
                self.assertEqual(report['output_dir'], str(output))
                plan = checks.read(Path(report['run']) / 'plan.json')
                self.assertEqual(plan['host_output_dir'], str(output))
                self.assertEqual(plan['container_output'], '/result')
                for metadata in (report, plan):
                    self.assertIs(metadata['cuda_compat'], cuda_compat)
                    self.assertEqual(metadata['docker_env_overrides'], {'NVIDIA_DISABLE_REQUIRE': 'true'} if cuda_compat else {})
                    self.assertFalse(metadata['organizer_exact_execution'])
                if cuda_compat:
                    self.assertEqual(report['execution_environment'], 'local_cuda_compatibility_override')
                    self.assertTrue(any('not organizer-exact' in n for n in report['environment_notes']))
            if cuda_compat:
                self.assertIn('CUDA COMPAT ENABLED: NVIDIA_DISABLE_REQUIRE=true', terminal.getvalue())
            self.assertEqual([name for name, cmd in captured], ['preflight', 'inference', 'preflight', 'inference'])
            inference = [cmd for name, cmd in captured if name == 'inference']
            expected = ['/bin/bash', '/code/predict.sh', '--data-root', '/data', '--split',
                        'private_test', '--output', '/result/submission.jsonl']
            self.assertEqual(inference, [expected + ['--limit', '3'], expected])
            self.assertTrue((output / '.private_test_k48_46_rc2.host.lock').is_file())
            self.assertTrue((output / '.validation-GPU-cpu-test.lock').is_file())
            self.assertEqual(before, sorted(str(p.relative_to(workspace)) for p in workspace.rglob('*')))
            self.assertEqual(dataset_zip.read_bytes(), b'CPU TEST FIXTURE, NOT A DATASET')


if __name__ == '__main__':
    unittest.main()
