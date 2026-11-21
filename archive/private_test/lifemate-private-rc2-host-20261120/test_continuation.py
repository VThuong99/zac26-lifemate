"""CPU-only recovery regressions: no Docker, models, GPU or ToolEnv execution."""
import copy
from contextlib import ExitStack, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import check_results as checks
import continue_private_test as recovery
import recovery_checks as rc
import run_private_test as host

ROOT = Path(__file__).resolve().parent
AUDIT = ROOT.parent / 'lifemate/results/private_test_k48_46_rc2_audit_20261120T114547Z/dataset/private_test'
spec = importlib.util.spec_from_file_location('continuation_driver', ROOT / 'container/continue_inference.py')
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


class Receipts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stage = self.root / 'inference'
        self.stage.mkdir()
        self.diagnostic = self.stage / 'submission.diagnostics'
        self.diagnostic.mkdir()
        self.validator = checks.official_validator(AUDIT)
        self.catalog = checks.read(AUDIT / 'private_test_tools_catalog.json')
        self.cases = [{'id': f'private_{i+1:04d}', 'context': {'installed_apps': {}}, 'history': [], 'audio': 'audio.wav'}
                      for i in range(3)]
        self.call = {'name': 'sys.ask_missing_info', 'arguments': {'tool_name': 'tasks.list', 'params': ['title']}}
        self.events = [{'type': 'tool_result', 'action': {'type': 'call', **self.call}, 'result': {'ok': True}}]
        self.receipt = {'id': self.cases[0]['id'], 'index': 0, 'status': 'finished', 'error': None,
                        'toolenv_instances': 1, 'dispatch_seconds': .123,
                        'prediction': {'id': self.cases[0]['id'], 'tool_calls': [self.call], 'state_hash': 'a' * 64},
                        'events': self.events}
        self.manifest = {'zaic_tools/executor.py': 'b' * 64}
        self.audit = [{'event': 'audit_installed'}, {'event': 'sdk_exec', 'allowed': True,
                      'path': '/data/private_test/zaic_tools/executor.py', 'sha256': 'b' * 64}]
        self.loading = checks.read(ROOT.parent / 'lifemate-final-20261116-rc2/runs/20261116T143345Z-pilot-65KOaw/submission.diagnostics/loading.json')
        self.loading['split'] = 'private_test'
        checks.write(self.diagnostic / 'loading.json', self.loading)
        (self.diagnostic / 'llama-server.log').write_text('srv load_model: initializing, n_slots = 1, n_ctx_slot = 8192\n')

    def validate(self, saved=None):
        return rc.validate_receipt(self.receipt, self.cases[0], 0, self.events, self.validator, self.catalog, saved)

    def persist(self, receipt=None, write_row=True):
        receipt = receipt or self.receipt
        i, rid = receipt['index'], receipt['id']
        checks.write(self.diagnostic / f'{i:06d}.result.json', receipt)
        (self.diagnostic / f'{i:06d}.events.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in receipt['events']))
        if write_row:
            with (self.stage / 'submission.jsonl.partial').open('a') as stream:
                stream.write(json.dumps({**receipt['prediction'], 'time': int(receipt['dispatch_seconds'] * 1000)}) + '\n')
        self.audit.append({'event': 'environment_open', 'allowed': True,
                           'path': f'/data/private_test/private_test_environment/{rid}/state.json'})
        (self.stage / 'sdk-imports.1.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in self.audit))

    def collect(self):
        return rc.collect_stage(self.stage, self.cases, range(3), self.manifest, self.validator, self.catalog)

    def test_original_loading_passes_and_16k_is_rejected(self):
        rc.check_loading(self.loading)
        self.loading['command'][8] = '16384'
        with self.assertRaisesRegex(ValueError, 'differs'):
            rc.check_loading(self.loading)

    def test_failure_receipt_uses_actual_calls_hash_and_elapsed_time(self):
        self.receipt.update(status='inference_error', error='LLM HTTP 400 exceed_context_size_error')
        row, detail = self.validate()
        self.assertEqual(row, {**self.receipt['prediction'], 'time': 123})
        self.assertTrue(detail['inference_failure'] and detail['context_overflow'])

    def test_missing_or_invalid_hash_cannot_be_synthesized(self):
        for prediction in (None, {}, {**self.receipt['prediction'], 'state_hash': 'unknown'}):
            with self.subTest(prediction=prediction):
                self.receipt['prediction'] = prediction
                with self.assertRaises(ValueError):
                    self.validate()

    def test_exactly_one_env_and_deadline_still_required(self):
        original = copy.deepcopy(self.receipt)
        for fields in ({'toolenv_instances': 2}, {'toolenv_instances': True}, {'dispatch_seconds': 30},
                       {'dispatch_seconds': float('nan')}, {'dispatch_seconds': True}, {'status': 'timeout'}):
            self.receipt = {**original, **fields}
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.validate()

    def test_prevalidation_rejection_is_not_an_executed_call(self):
        invalid = {'name': 'sys.ask_missing_info', 'arguments': {}}
        result = self.validator([invalid], self.catalog, {'sys.ask_missing_info'})[0]
        event = {'type': 'tool_result', 'action': {'type': 'call', **invalid},
                 'result': {'ok': False, 'error': result['error']}}
        self.events.append(event)
        self.receipt['status'] = 'tool_error'
        row, detail = self.validate()
        self.assertEqual(row['tool_calls'], [self.call])
        self.assertEqual(len(detail['rejected_proposals']), 1)
        self.assertTrue(detail['execution_failure'])

    def test_rejected_proposal_cannot_hide_an_actual_sdk_call(self):
        invalid = {'name': 'sys.ask_missing_info', 'arguments': {}}
        result = self.validator([invalid], self.catalog, {'sys.ask_missing_info'})[0]
        self.events.append({'type': 'tool_result', 'action': {'type': 'call', **invalid},
                            'result': {'ok': False, 'error': result['error']}})
        self.receipt['prediction']['tool_calls'].append(invalid)
        with self.assertRaisesRegex(ValueError, 'SDK calls differ'):
            self.validate()

    def test_successful_event_cannot_be_dropped(self):
        self.receipt['prediction']['tool_calls'] = []
        with self.assertRaisesRegex(ValueError, 'SDK calls differ'):
            self.validate()

    def test_receipt_must_match_saved_hash_and_timing(self):
        row, _ = self.validate()
        for changed in ({'state_hash': 'c' * 64}, {'time': 124}, {'time': True}, {'extra': 1}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.validate({**row, **changed})

    def test_collect_preserves_original_bytes_and_recovers_missing_row(self):
        self.persist()
        original = (self.stage / 'submission.jsonl.partial').read_bytes()
        second = copy.deepcopy(self.receipt)
        second.update(id=self.cases[1]['id'], index=1, status='inference_error', error='exceed_context_size_error')
        second['prediction']['id'] = second['id']
        self.persist(second, write_row=False)
        verified, attempted, blocked = self.collect()
        self.assertEqual(verified[0]['raw'], original)
        self.assertEqual(attempted, {0, 1})
        self.assertEqual(blocked, [])
        self.assertFalse(verified[1]['copied_existing_row'])

    def test_multiple_envs_and_wrong_sdk_rejected(self):
        self.persist()
        self.audit.append(copy.deepcopy(self.audit[-1]))
        path = self.stage / 'sdk-imports.1.jsonl'
        path.write_text(''.join(json.dumps(e) + '\n' for e in self.audit))
        with self.assertRaisesRegex(ValueError, 'Multiple ToolEnv'):
            self.collect()
        self.audit.pop()
        self.audit[1]['sha256'] = 'c' * 64
        path.write_text(''.join(json.dumps(e) + '\n' for e in self.audit))
        with self.assertRaisesRegex(ValueError, 'SDK origin/hash'):
            self.collect()

    def test_attempt_without_receipt_is_not_selected_for_automatic_retry(self):
        (self.stage / 'attempts.jsonl').write_text(json.dumps({'id': self.cases[1]['id'], 'index': 1}) + '\n')
        verified, attempted, blocked = self.collect()
        self.assertEqual(verified, {})
        self.assertEqual(attempted, {1})
        self.assertEqual(blocked[0]['id'], self.cases[1]['id'])
        self.assertEqual(set(range(3)) - attempted, {0, 2})

    def test_duplicate_attempt_across_runs_rejected(self):
        with self.assertRaisesRegex(ValueError, 'multiple source runs'):
            rc.merge_inventory([({}, {1}, []), ({}, {1}, [])])

    def fake_runtime(self, failures=(), missing=()):
        fixture = self
        class Runtime:
            proc = SimpleNamespace(is_alive=lambda: True)
            seen = []
            def infer(self, item, index):
                self.seen.append(index)
                if index in missing:
                    raise TimeoutError('No receipt')
                r = copy.deepcopy(fixture.receipt)
                r.update(id=item['id'], index=index)
                r['prediction']['id'] = item['id']
                if index in failures:
                    r.update(status='inference_error', error='HTTP 400 exceed_context_size_error')
                checks.write(fixture.diagnostic / f'{index:06d}.result.json', r)
                (fixture.diagnostic / f'{index:06d}.events.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in r['events']))
                if index in failures:
                    raise RuntimeError(r['error'])
                return {**r['prediction'], 'time': 123}
        return Runtime()

    def test_driver_continues_after_multiple_overflows_without_retry(self):
        runtime = self.fake_runtime(failures=(0, 1))
        complete = driver.run_selected(runtime, self.cases, [0, 1, 2], self.stage, self.validator, self.catalog)
        self.assertTrue(complete)
        self.assertEqual(runtime.seen, [0, 1, 2])
        self.assertEqual(len(checks.rows(self.stage / 'submission.jsonl')), 3)
        self.assertEqual(sum(x['execution_failure'] for x in checks.rows(self.stage / 'outcomes.jsonl')), 2)

    def test_driver_honors_selection_and_original_indices(self):
        runtime = self.fake_runtime(failures=(2,))
        driver.run_selected(runtime, self.cases, [2], self.stage, self.validator, self.catalog)
        self.assertEqual(runtime.seen, [2])
        self.assertTrue((self.diagnostic / '000002.result.json').exists())
        self.assertFalse((self.diagnostic / '000000.result.json').exists())

    def test_driver_stops_on_missing_receipt_without_empty_prediction(self):
        runtime = self.fake_runtime(missing=(1,))
        with self.assertRaisesRegex(RuntimeError, 'no receipt'):
            driver.run_selected(runtime, self.cases, [0, 1, 2], self.stage, self.validator, self.catalog)
        self.assertEqual(runtime.seen, [0, 1])
        self.assertFalse((self.stage / 'submission.jsonl').exists())
        self.assertEqual(len(checks.rows(self.stage / 'submission.jsonl.partial')), 1)

    def test_assembly_preserves_bytes_orders_rows_and_records_failures(self):
        self.persist()
        original = (self.stage / 'submission.jsonl.partial').read_bytes()
        verified, attempted, blocked = self.collect()
        destination = self.root / 'final.jsonl'
        report_dir = self.root / 'merged'
        report_dir.mkdir()
        result = recovery.assemble(report_dir, destination, verified, attempted, blocked, self.cases[:1])
        self.assertEqual(destination.read_bytes(), original)
        self.assertEqual(result['sha256'], checks.sha(destination))
        self.assertEqual(result['official_tool_schema_validation'], 'PASS')
        self.assertFalse(result['organizer_exact_execution'])

    def test_incomplete_assembly_never_publishes(self):
        report_dir = self.root / 'merged'
        report_dir.mkdir()
        with self.assertRaisesRegex(ValueError, 'Incomplete authentic'):
            recovery.assemble(report_dir, self.root / 'final.jsonl', {}, set(), [], self.cases)
        self.assertFalse((self.root / 'final.jsonl').exists())


class RecoverySafety(unittest.TestCase):
    def test_host_guard_precedes_docker_and_writes(self):
        with patch.object(host, 'ensure_host', side_effect=RuntimeError('HOST REQUIRED')), \
                patch.object(host, 'command') as docker, patch.object(host, 'prepare_output_dir') as output:
            with self.assertRaisesRegex(RuntimeError, 'HOST REQUIRED'):
                recovery.main(['--resume-from', '/not-accessed'])
            docker.assert_not_called()
            output.assert_not_called()

    def test_evidence_changes_or_extra_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'receipt.json').write_text('{}')
            report = {'evidence_sha256': {'receipt.json': checks.sha(root / 'receipt.json')}}
            recovery.verify_seal(root, report)
            (root / 'extra.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'added or removed'):
                recovery.verify_seal(root, report)

    def test_unsealed_previous_continuation_blocks_duplicate_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / 'original'
            base.mkdir()
            checks.write(base / 'REPORT.json', {})
            child = root / '20261120-continue-fixture'
            child.mkdir()
            checks.write(child / 'RECOVERY.json', {'source_run': str(base), 'source_report_sha256': checks.sha(base / 'REPORT.json')})
            with self.assertRaisesRegex(ValueError, 'Unsealed continuation'):
                recovery.discover_sources(base, root)


class HostContinuation(Receipts):
    # The parent fixtures describe synthetic receipts, never model predictions.
    # Keep only this class's integration test when loading it below.
    def test_host_resume_after_partial_stage_preserves_rows_and_cuda_checks(self):
        output = self.root / 'host-output'
        output.mkdir()
        base = output / 'original-full'
        base.mkdir()
        workspace = self.root / 'host-workspace'
        workspace.mkdir()
        original_report = {'mode': 'full', 'workspace': str(workspace), 'gpu': {'uuid': 'GPU-test', 'driver': 'fixture'},
                           'cuda_compat': True, 'evidence_sha256': {'original.txt': checks.sha(ROOT / 'check_results.py')}}
        (base / 'original.txt').write_bytes((ROOT / 'check_results.py').read_bytes())
        checks.write(base / 'REPORT.json', original_report)
        self.persist()
        original_inventory = self.collect()
        original_raw = original_inventory[0][0]['raw']
        calls, selections = [], []
        real_run_container = host.run_container

        def extract(unused, run):
            split = run / 'dataset/private_test'
            split.mkdir(parents=True)
            checks.write(split / 'private_test_tools_catalog.json', self.catalog)
            checks.write(run / 'input-manifest.json', self.manifest)
            # No manifest hashing happens against these synthetic SDK entries.
            return split, self.cases, {}

        def source(run, *args):
            recovery.verify_seal(run, checks.read(run / 'REPORT.json'))
            if run == base:
                return original_inventory
            if not (run / 'inference').exists():
                return {}, set(), []
            planned = checks.read(run / 'harness/continuation-plan.json')['indices']
            return rc.collect_stage(run / 'inference', self.cases, planned, self.manifest, self.validator, self.catalog)

        def metadata(argv, **kwargs):
            self.assertEqual(argv, ['docker', 'info', '--format', '{{json .}}'])
            return SimpleNamespace(stdout=json.dumps({'OSType': 'linux', 'NCPU': 16,
                'MemTotal': 64 * 1024**3, 'DockerRootDir': '/cpu-fixture'}))

        def container(run, name, cmd, deadline, identity, split, harness, gpu, *, cuda_compat=False):
            class CapturedCreate(Exception):
                pass
            with patch.object(host, 'command', side_effect=CapturedCreate) as create:
                with self.assertRaises(CapturedCreate):
                    real_run_container(run, name, cmd, deadline, identity, split, harness, gpu, cuda_compat=cuda_compat)
            argv = create.call_args.args[0]
            self.assertIn('NVIDIA_DISABLE_REQUIRE=true', argv)
            self.assertNotIn('--entrypoint', argv)
            self.assertEqual(argv[argv.index(host.MANIFEST) + 1:], cmd)
            self.assertIn(f'type=bind,src={split},dst=/data/private_test,readonly', argv)
            self.assertIn(f'type=bind,src={run / name},dst=/result', argv)
            calls.append(name)
            stage = run / name
            if name == 'preflight':
                checks.write(stage / 'preflight.json', {'success': True})
                return stage, True, {}
            self.assertEqual(cmd, recovery.DRIVER_CMD)
            indices = checks.read(harness / 'continuation-plan.json')['indices']
            selections.append(indices)
            # First invocation completes one selected failure then is interrupted
            # before dispatching the next item. The next host invocation resumes it.
            execute = indices[:1] if len(selections) == 1 else indices
            self.stage = stage
            self.diagnostic = stage / 'submission.diagnostics'
            self.diagnostic.mkdir()
            checks.write(self.diagnostic / 'loading.json', self.loading)
            (self.diagnostic / 'llama-server.log').write_text('n_ctx_slot = 8192\n')
            runtime = self.fake_runtime(failures=(1,))
            driver.run_selected(runtime, self.cases, execute, stage, self.validator, self.catalog)
            audit = self.audit[:2] + [{'event': 'environment_open', 'allowed': True,
                'path': f'/data/private_test/private_test_environment/{self.cases[i]["id"]}/state.json'} for i in execute]
            (stage / 'sdk-imports.1.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in audit))
            checks.write(stage / 'container-final.json', [{'State': {'OOMKilled': False, 'Error': ''}}])
            return stage, len(execute) == len(indices), {'wall_seconds': 1}

        with ExitStack() as stack:
            for obj, name, value in (
                (host, 'ensure_host', lambda: None), (host, 'local_docker_endpoint', lambda: 'unix:///fixture'),
                (host, 'load_verifier', lambda p: (None, {}, {'archive': 'fixture.tar.gz'}, {})),
                (host, 'verify_archive', lambda *a: {}),
                (host, 'get_loaded', lambda *a: {'image_id': host.MANIFEST}),
                (host, 'check_gpu', lambda *a: original_report['gpu']),
                (host, 'command', metadata), (host, 'extract_dataset', extract),
                (host, 'run_container', container), (recovery, 'collect_source', source),
                (recovery, 'official_validator', lambda split: self.validator),
                (recovery, 'collect_stage', lambda stage, cases, indices, manifest, validator, catalog:
                    rc.collect_stage(stage, cases, indices, self.manifest, validator, catalog)),
            ):
                stack.enter_context(patch.object(obj, name, value))
            stack.enter_context(patch.object(host.subprocess, 'run', side_effect=AssertionError('No processes allowed')))
            stack.enter_context(patch.object(host.subprocess, 'Popen', side_effect=AssertionError('No processes allowed')))
            stack.enter_context(redirect_stdout(io.StringIO()))
            args = ['--resume-from', str(base), '--output-dir', str(output), '--cuda-compat']
            self.assertEqual(recovery.main(args), 2)
            self.assertFalse((output / 'private_test_k48_46_final.jsonl').exists())
            self.assertEqual(recovery.main(args), 0)
            self.assertEqual(selections, [[1, 2], [2]])
            final = output / 'private_test_k48_46_final.jsonl'
            self.assertTrue(final.read_bytes().startswith(original_raw))
            self.assertEqual([r['id'] for r in checks.rows(final)], [c['id'] for c in self.cases])
            count = len(calls)
            before = final.read_bytes()
            self.assertEqual(recovery.main(args), 0)
            self.assertEqual(len(calls), count)  # Complete output requires no GPU launch.
            self.assertEqual(final.read_bytes(), before)
            reports = [checks.read(p) for p in output.glob('*-continue-*/REPORT.json')]
            completed = [r for r in reports if r['output_created']]
            self.assertTrue(completed)
            self.assertEqual(completed[-1]['result']['inference_failures'], 1)
            self.assertEqual(completed[-1]['result']['context_overflows'], 1)
            self.assertEqual(completed[-1]['result']['sha256'], checks.sha(final))


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(Receipts))
    suite.addTests(loader.loadTestsFromTestCase(RecoverySafety))
    suite.addTest(HostContinuation('test_host_resume_after_partial_stage_preserves_rows_and_cuda_checks'))
    return suite


if __name__ == '__main__':
    unittest.main()
