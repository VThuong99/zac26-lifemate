import contextlib
import io
import json
import shutil
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validation import HERE, analyze, references, sha, write_json
from image_identity import make_identity_record
from identity_fixtures import build_fixture, inspected


class AnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.run = Path(self.temp.name)
        self.f = build_fixture(self.run / 'fixture')
        self.trust_patch = patch('image_identity.RELEASE_MANIFEST_SHA256', self.f.trust)
        self.trust_patch.start(); self.addCleanup(self.trust_patch.stop)
        write_json(self.run / 'image-inspect.json', inspected(self.f))
        self.identity = make_identity_record(self.run / 'image-inspect.json', self.f.sealed)
        write_json(self.run / 'image-identity.json', self.identity)
        self.image_id = self.identity['verified_docker_image_reference']
        m, refs = references(); ref = refs[0]
        write_json(self.run / 'plan.json', {'mode': 'smoke', 'workflow': 'cli', 'count': 1, 'expected_ids': [ref['id']], 'reference_manifest_sha256': sha(HERE / 'reference/manifest.json'), 'image_identity_sha256': sha(self.run / 'image-identity.json'), **{key: self.identity[key] for key in ('image_config_digest', 'docker_store_image_id', 'verified_docker_image_reference')}})
        prediction = {k: ref[k] for k in ('id', 'tool_calls', 'state_hash')}
        (self.run / 'submission.jsonl').write_text(json.dumps({**prediction, 'time': 1000}) + '\n')
        diag = self.run / 'submission.diagnostics'; diag.mkdir()
        write_json(diag / '000000.result.json', {'id': ref['id'], 'index': 0, 'status': ref['status'], 'error': ref['error'], 'toolenv_instances': 1, 'prediction': prediction, 'dispatch_seconds': 1, 'events': [{'type': 'tool_result', 'action': c} for c in ref['tool_calls']]})
        write_json(diag / 'loading.json', {'backend': 'sm120', 'split': 'public_test', 'all_models_load_seconds': 7})
        write_json(self.run / 'container-final.json', [{'Image': self.image_id, 'Config': {'Image': self.image_id}, 'State': {'Running': False, 'ExitCode': 0, 'OOMKilled': False}}])
        write_json(self.run / 'exit.json', {'docker_attach_exit_code': 0, 'tee_exit_code': 0})
        write_json(self.run / 'container-created.json', [{'Image': self.image_id, 'Config': {'Hostname': 'lifemate-offline', 'Image': self.image_id}, 'HostConfig': {'NetworkMode': 'none', 'NanoCpus': 16000000000, 'Memory': 48 * 1024**3, 'MemorySwap': 48 * 1024**3, 'ShmSize': 2 * 1024**3, 'ExtraHosts': ['lifemate-offline:127.0.0.1']}, 'Mounts': [{'Destination': '/data/public_test', 'RW': False}]}])
        write_json(self.run / 'container-preflight.json', {'success': True, 'packaged_data_audit_pass': True, 'sdk_packaging_audit_pass': True, 'packaged_sdk_paths': [], 'gpu_available': True, 'predict_sha256': m['release_source_files']['source/predict.py'], 'notebook_sha256': m['release_source_files']['source/predict_notebook.ipynb']})
        (self.run / 'harness').mkdir(); (self.run / 'harness/sitecustomize.py').write_text('# fixture\n')
        write_json(self.run / 'harness-sha256.json', {'sitecustomize.py': sha(self.run / 'harness/sitecustomize.py')})
        (self.run / 'sdk-imports.1.jsonl').write_text(json.dumps({'event': 'sdk_exec', 'allowed': True, 'path': '/data/public_test/zaic_tools/executor.py', 'sha256': m['input_files']['zaic_tools/executor.py']}) + '\n')

    def tearDown(self): self.temp.cleanup()
    def analyze(self):
        with contextlib.redirect_stdout(io.StringIO()): return analyze(self.run)

    def test_synthetic_success_and_repeat_analysis_never_overwrites(self):
        self.assertTrue(self.analyze()); self.assertTrue(self.analyze())
        self.assertEqual(len(list(self.run.glob('analysis-*'))), 2)

    def test_containerd_verified_reference_used_by_analyzer(self):
        (self.run / 'image-inspect.json').write_text(json.dumps(inspected(self.f, 'containerd_docker_save_manifest')))
        identity = make_identity_record(self.run / 'image-inspect.json', self.f.sealed)
        (self.run / 'image-identity.json').write_text(json.dumps(identity))
        plan = json.loads((self.run / 'plan.json').read_text())
        plan.update({key: identity[key] for key in ('image_config_digest', 'docker_store_image_id', 'verified_docker_image_reference')})
        plan['image_identity_sha256'] = sha(self.run / 'image-identity.json')
        (self.run / 'plan.json').write_text(json.dumps(plan))
        for name in ('container-created.json', 'container-final.json'):
            data = json.loads((self.run / name).read_text()); data[0]['Image'] = identity['docker_store_image_id']; data[0]['Config']['Image'] = identity['verified_docker_image_reference']
            (self.run / name).write_text(json.dumps(data))
        self.assertTrue(self.analyze())

    def test_missing_identity_receipt_fails_closed(self):
        (self.run / 'image-identity.json').unlink()
        self.assertFalse(self.analyze())

    def test_container_failure_separate_from_exact_prediction(self):
        p = self.run / 'container-final.json'; d = json.loads(p.read_text()); d[0]['State']['ExitCode'] = 37; p.write_text(json.dumps(d))
        self.assertFalse(self.analyze())
        report = json.loads(next(self.run.glob('analysis-*/report.json')).read_text())
        self.assertTrue(report['exact_k_trajectory_parity']['parity_pass']); self.assertFalse(report['docker_execution_success'])

    def test_legacy_sdk_blocks_compliance_without_hiding_behavior(self):
        p = self.run / 'container-preflight.json'; d = json.loads(p.read_text())
        d.update(sdk_packaging_audit_pass=False, packaged_sdk_paths=['/code/runtime/lifemate/train/zaic_tools'])
        p.write_text(json.dumps(d))
        self.assertFalse(self.analyze())
        report = json.loads(next(self.run.glob('analysis-*/report.json')).read_text())
        self.assertTrue(report['selected_behavioral_checks_pass'])
        self.assertTrue(report['mounted_toolenv_imports']['pass'])
        self.assertFalse(report['sdk_compliance_pass'])
        self.assertEqual(report['offline_compliance'], 'PASS_WITH_HOSTNAME_WORKAROUND')

    def test_no_sdk_audit_cannot_pass(self):
        (self.run / 'sdk-imports.1.jsonl').unlink(); self.assertFalse(self.analyze())

    def test_partial_file_never_counts_as_complete(self):
        (self.run / 'submission.jsonl').rename(self.run / 'submission.jsonl.partial')
        self.assertFalse(self.analyze())

    def test_mismatching_peer_fails_combined_check(self):
        with tempfile.TemporaryDirectory() as t:
            peer = Path(t)
            plan = json.loads((self.run / 'plan.json').read_text()); plan['workflow'] = 'notebook'
            write_json(peer / 'plan.json', plan)
            rows = json.loads((self.run / 'submission.jsonl').read_text()); rows['state_hash'] = 'changed'
            (peer / 'jupyter_submission.jsonl').write_text(json.dumps(rows) + '\n')
            shutil.copytree(self.run / 'submission.diagnostics', peer / 'jupyter_submission.diagnostics')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(analyze(self.run, peer))

    def test_network_isolation_required(self):
        p = self.run / 'container-created.json'; d = json.loads(p.read_text()); d[0]['HostConfig']['NetworkMode'] = 'bridge'; p.write_text(json.dumps(d))
        self.assertFalse(self.analyze())


if __name__ == '__main__': unittest.main()
