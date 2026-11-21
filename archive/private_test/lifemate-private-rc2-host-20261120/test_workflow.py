"""CPU-only safety/provenance tests. No Docker, GPU, inference or ToolEnv calls."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
import check_results as checks
import run_private_test as host

WORKSPACE = Path(__file__).resolve().parent.parent
RC = WORKSPACE / 'lifemate-final-20261116-rc2'
AUDIT = WORKSPACE / 'lifemate/results/private_test_k48_46_rc2_audit_20261120T114547Z'


class HostSafety(unittest.TestCase):
    def test_remote_context_cannot_hide_behind_local_docker_host(self):
        with patch.dict(host.os.environ, {'DOCKER_CONTEXT': 'remote', 'DOCKER_HOST': 'unix:///var/run/docker.sock'}), patch.object(host, 'command', return_value=SimpleNamespace(stdout='ssh://remote\n')) as execute:
            with self.assertRaisesRegex(RuntimeError, 'Only a local HOST'):
                host.local_docker_endpoint()
            self.assertIn('remote', execute.call_args.args[0])

    def test_container_guard_runs_before_commands(self):
        with patch.object(host.Path, 'exists', return_value=True), patch.object(host, 'command') as execute:
            with self.assertRaisesRegex(RuntimeError, 'HOST REQUIRED'):
                host.ensure_host()
            execute.assert_not_called()

    def test_no_clobber_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            source, output = Path(temp) / 'stage.jsonl', Path(temp) / 'final.jsonl'
            source.write_text('new\n')
            output.write_text('preserve\n')
            with self.assertRaisesRegex(RuntimeError, 'refusing to overwrite'):
                host.publish(source, output, checks.sha(source))
            self.assertEqual(output.read_text(), 'preserve\n')

    def test_publication_verifies_bytes_and_keeps_stage(self):
        with tempfile.TemporaryDirectory() as temp:
            source, output = Path(temp) / 'stage.jsonl', Path(temp) / 'final.jsonl'
            source.write_text('{"actual":"SDK output"}\n')
            host.publish(source, output, checks.sha(source))
            self.assertEqual(source.read_bytes(), output.read_bytes())
            self.assertTrue(source.exists())

    def test_changed_prediction_not_published(self):
        with tempfile.TemporaryDirectory() as temp:
            source, output = Path(temp) / 'stage.jsonl', Path(temp) / 'final.jsonl'
            source.write_text('changed')
            with self.assertRaisesRegex(RuntimeError, 'changed after validation'):
                host.publish(source, output, '0' * 64)
            self.assertFalse(output.exists())

    def test_full_requires_genuine_smoke_report(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)
            checks.write(p / 'REPORT.json', {'mode': 'smoke', 'smoke_pass': False})
            with self.assertRaisesRegex(RuntimeError, 'Prior smoke did not pass'):
                host.validate_smoke_reference(p, WORKSPACE, {})


class ImageIdentity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.package, cls.build, _, _ = host.load_verifier(WORKSPACE)
        cls.inspected = checks.read(RC / 'runs/20261116T143345Z-pilot-65KOaw/image-inspect.json')
        sealed = checks.read(AUDIT / 'archive_identity_report.json')
        media_type = sealed['archive_metadata_objects']['blobs/sha256/' + host.MANIFEST[7:]]['mediaType']
        cls.archive = {'descriptors': {host.MANIFEST: {'digest': host.MANIFEST, 'size': 701, 'mediaType': media_type}}}

    def test_recorded_image_passes(self):
        result = host.verify_loaded(self.inspected, self.package, self.build, self.archive)
        self.assertTrue(result['verified'])

    def test_tag_is_not_identity(self):
        value = copy.deepcopy(self.inspected)
        value[0]['Id'] = 'sha256:' + 'a' * 64
        with self.assertRaisesRegex(RuntimeError, 'Unknown image ID'):
            host.verify_loaded(value, self.package, self.build, self.archive)

    def test_matching_layers_with_changed_entrypoint_rejected(self):
        value = copy.deepcopy(self.inspected)
        value[0]['Config']['Entrypoint'] = ['/replacement.sh']
        with self.assertRaisesRegex(RuntimeError, 'runtime configuration differs'):
            host.verify_loaded(value, self.package, self.build, self.archive)

    def test_descriptor_required_for_manifest_store(self):
        value = copy.deepcopy(self.inspected)
        value[0].pop('Descriptor', None)
        with self.assertRaisesRegex(RuntimeError, 'expose its descriptor'):
            host.verify_loaded(value, self.package, self.build, self.archive)

    def test_legacy_config_store_is_accepted_with_full_config(self):
        value = copy.deepcopy(self.inspected)
        value[0]['Id'] = host.CONFIG
        value[0].pop('Descriptor', None)
        result = host.verify_loaded(value, self.package, self.build, self.archive)
        self.assertEqual(result['image_id'], host.CONFIG)

    def container_fixture(self):
        data = checks.read(RC / 'runs/20261116T143345Z-pilot-65KOaw/container-created.json')
        c = data[0]
        split, stage, harness = Path('/tmp/official-private'), Path('/tmp/rc2-result'), Path('/tmp/rc2-observer')
        command = ['/bin/bash', '/code/predict.sh', '--data-root', '/data', '--split', 'private_test', '--output', '/result/submission.jsonl', '--limit', '3']
        c['Config']['Cmd'] = command
        for mount in c['Mounts']:
            if mount['Destination'] == '/data/public_test':
                mount.update(Destination='/data/private_test', Source=str(split), RW=False)
            elif mount['Destination'] == '/result':
                mount['Source'] = str(stage)
            elif mount['Destination'] == '/validation':
                mount['Source'] = str(harness)
        uuid = c['HostConfig']['DeviceRequests'][0]['DeviceIDs'][0]
        return data, {'image_id': host.MANIFEST}, split, stage, harness, command, uuid, c['Config']['User']

    def test_recorded_container_protocol_with_private_mount(self):
        host.verify_container(*self.container_fixture())

    def test_explicit_cuda_compat_container_passes(self):
        args = self.container_fixture()
        args[0][0]['Config']['Env'].append('NVIDIA_DISABLE_REQUIRE=true')
        host.verify_container(*args, cuda_compat=True)

    def test_cuda_compat_requires_exact_container_override(self):
        for override in (None, 'false', 'TRUE', ''):
            with self.subTest(override=override):
                args = self.container_fixture()
                if override is not None:
                    args[0][0]['Config']['Env'].append('NVIDIA_DISABLE_REQUIRE=' + override)
                with self.assertRaisesRegex(RuntimeError, 'CUDA compatibility override'):
                    host.verify_container(*args, cuda_compat=True)

    def test_unrequested_cuda_compat_rejected(self):
        args = self.container_fixture()
        args[0][0]['Config']['Env'].append('NVIDIA_DISABLE_REQUIRE=true')
        with self.assertRaisesRegex(RuntimeError, 'CUDA compatibility override'):
            host.verify_container(*args)

    def test_cuda_compat_cannot_replace_entrypoint(self):
        args = self.container_fixture()
        args[0][0]['Config']['Env'].append('NVIDIA_DISABLE_REQUIRE=true')
        args[0][0]['Config']['Entrypoint'] = ['/replacement.sh']
        with self.assertRaisesRegex(RuntimeError, 'original entrypoint'):
            host.verify_container(*args, cuda_compat=True)

    def test_writable_dataset_mount_rejected(self):
        args = self.container_fixture()
        next(m for m in args[0][0]['Mounts'] if m['Destination'] == '/data/private_test')['RW'] = True
        with self.assertRaisesRegex(RuntimeError, 'Mount mapping/access mismatch'):
            host.verify_container(*args)

    def test_replaced_container_entrypoint_rejected(self):
        args = self.container_fixture()
        args[0][0]['Config']['Entrypoint'] = ['/validation/replacement.py']
        with self.assertRaisesRegex(RuntimeError, 'original entrypoint'):
            host.verify_container(*args)

    def test_network_access_rejected(self):
        args = self.container_fixture()
        args[0][0]['HostConfig']['NetworkMode'] = 'host'
        with self.assertRaisesRegex(RuntimeError, 'NetworkMode'):
            host.verify_container(*args)


class PredictionEvidence(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.run, self.split = root / 'inference', root / 'private_test'
        self.run.mkdir()
        (self.run / 'submission.diagnostics').mkdir()
        (self.split / 'zaic_tools').mkdir(parents=True)
        # Use the organizer's real schema checker; do not construct an environment.
        shutil.copyfile(AUDIT / 'dataset/private_test/zaic_tools/validate.py', self.split / 'zaic_tools/validate.py')
        self.catalog = {'apps': [{'id': 'sys', 'tools': [{'name': 'sys.ask_missing_info', 'parameters': {
            'properties': {'tool_name': {'type': 'string'}, 'params': {'type': 'array', 'items': {'type': 'string'}}},
            'required': ['tool_name', 'params']}}]}]}
        checks.write(self.split / 'private_test_tools_catalog.json', self.catalog)
        self.case = {'id': 'private_0001', 'audio': 'audio/private_0001/private_0001.wav', 'history': [],
                     'context': {'installed_apps': {}}}
        self.call = {'name': 'sys.ask_missing_info', 'arguments': {'tool_name': 'alarm.create', 'params': ['time']}}
        self.pred = {'id': 'private_0001', 'tool_calls': [self.call], 'state_hash': 'a' * 64, 'time': 123}
        self.events = [{'type': 'tool_result', 'action': {'type': 'call', **self.call}, 'result': {'ok': True}}]
        self.receipt = {'id': 'private_0001', 'index': 0, 'status': 'finished', 'error': None,
                        'toolenv_instances': 1, 'dispatch_seconds': .123,
                        'prediction': {k: v for k, v in self.pred.items() if k != 'time'}, 'events': self.events}
        self.audit = [{'event': 'audit_installed'}, {'event': 'sdk_exec', 'path': '/data/private_test/zaic_tools/executor.py', 'allowed': True, 'sha256': 'b' * 64},
                      {'event': 'environment_open', 'path': '/data/private_test/private_test_environment/private_0001/state.json', 'allowed': True}]
        self.manifest = {'zaic_tools/executor.py': 'b' * 64}
        self.persist()
        checks.write(self.run / 'submission.diagnostics/loading.json', {'backend': 'sm120', 'split': 'private_test', 'seed': 20261030, 'all_models_load_seconds': 1})

    def persist(self):
        (self.run / 'submission.jsonl').write_text(json.dumps(self.pred) + '\n')
        (self.run / 'submission.diagnostics/000000.result.json').write_text(json.dumps(self.receipt) + '\n')
        (self.run / 'submission.diagnostics/000000.events.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in self.events))
        (self.run / 'sdk-imports.1.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in self.audit))

    def analyze(self):
        return checks.analyze(self.run, [self.case], self.split, self.manifest)

    def test_complete_sdk_evidence_passes(self):
        result = self.analyze()
        self.assertEqual(result['issues'], [])
        self.assertEqual(result['status'], 'READY FOR SUBMISSION')

    def test_missing_prediction_is_invalid(self):
        (self.run / 'submission.jsonl').rename(self.run / 'submission.jsonl.partial')
        self.assertFalse(self.analyze()['structural_and_provenance_pass'])

    def test_duplicate_id_is_invalid(self):
        with (self.run / 'submission.jsonl').open('a') as stream:
            stream.write(json.dumps(self.pred) + '\n')
        self.assertTrue(any(e['kind'] == 'id_coverage_or_order' for e in self.analyze()['issues']))

    def test_forged_calls_cannot_match_real_events(self):
        self.pred['tool_calls'] = []
        self.receipt['prediction']['tool_calls'] = []
        self.persist()
        self.assertTrue(any(e['kind'] == 'actual_call_order' for e in self.analyze()['issues']))

    def test_forged_hash_disagrees_with_sdk_receipt(self):
        self.pred['state_hash'] = 'c' * 64
        self.persist()
        self.assertTrue(any(e['kind'] == 'prediction_vs_receipt' for e in self.analyze()['issues']))

    def test_second_toolenv_open_rejected(self):
        self.audit.append(copy.deepcopy(self.audit[-1]))
        self.persist()
        self.assertTrue(any(e['kind'] == 'environment_access_counts' for e in self.analyze()['issues']))

    def test_wrong_sdk_rejected(self):
        self.audit[1]['path'] = '/code/runtime/lifemate/train/zaic_tools/executor.py'
        self.persist()
        self.assertTrue(any(e['kind'] == 'sdk_origin_or_hash' for e in self.analyze()['issues']))

    def test_timeout_rejected(self):
        self.receipt['dispatch_seconds'] = 30
        self.pred['time'] = 30000
        self.persist()
        self.assertFalse(self.analyze()['structural_and_provenance_pass'])

    def test_boolean_time_rejected(self):
        self.pred['time'] = True
        self.persist()
        self.assertTrue(any(e['kind'] == 'time_field' for e in self.analyze()['issues']))

    def test_step_limit_is_warning_without_rewriting(self):
        self.receipt['status'] = 'max_steps'
        self.persist()
        before = checks.sha(self.run / 'submission.jsonl')
        result = self.analyze()
        self.assertTrue(result['structural_and_provenance_pass'])
        self.assertEqual(result['status'], 'GENERATED WITH WARNINGS')
        self.assertEqual(checks.sha(self.run / 'submission.jsonl'), before)

    def test_actual_rejected_call_preserved_and_reported(self):
        self.call['arguments'].pop('params')
        self.events[0]['result'] = {'ok': False, 'error': 'missing params'}
        self.persist()
        result = self.analyze()
        self.assertTrue(result['structural_and_provenance_pass'])
        self.assertFalse(result['official_tool_schema_pass'])
        self.assertEqual(len(result['tool_errors']), 1)
        self.assertEqual(result['status'], 'GENERATED WITH WARNINGS')

    def test_debug_fields_rejected(self):
        self.pred['transcript'] = 'debug'
        self.persist()
        self.assertTrue(any(e['kind'] == 'output_fields' for e in self.analyze()['issues']))

    def test_duplicate_json_keys_rejected(self):
        (self.run / 'submission.jsonl').write_text('{"id":"private_0001","id":"private_0002"}\n')
        self.assertTrue(any(e['kind'] == 'jsonl_read' for e in self.analyze()['issues']))

    def test_overflow_json_number_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Non-finite JSON number'):
            checks.parse('{"value":1e999}')

    def test_transport_timeout_without_receipt_is_reported(self):
        (self.run / 'submission.diagnostics/000000.result.json').rename(self.run / 'saved_receipt_fixture.json')
        (self.run / 'submission.jsonl').rename(self.run / 'submission.jsonl.partial')
        (self.run / 'container.log').write_text('TimeoutError: K exceeded 30 seconds; no fabricated output or second ToolEnv\n')
        result = self.analyze()
        self.assertEqual(result['timeouts'], 1)
        self.assertEqual(result['unreceipted_deadline_failures'], 1)
        self.assertFalse(result['structural_and_provenance_pass'])


if __name__ == '__main__':
    unittest.main()
