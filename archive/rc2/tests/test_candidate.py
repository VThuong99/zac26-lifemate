"""CPU-only compatibility and provenance checks. All state fixtures are synthetic."""
import ast
import copy
import hashlib
import importlib
import importlib.util
import itertools
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parent
OLD = ROOT / 'lifemate-release-k-20261115/source'
NEW = HERE / 'overlay'
sys.path.insert(0, str(HERE / 'tools'))
sys.path.insert(0, str(ROOT / 'lifemate-host-validation/tests'))
import schema_helpers as new
from test_hostname_fix import function as hostname_function


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


legacy = load_file('schema_reference_only', OLD / 'runtime/lifemate/train/zaic_tools/validate.py')


class SchemaTests(unittest.TestCase):
    def test_formats_exhaustive_boundaries(self):
        values = [None, False, 2, [], {}, '', 'x', '2024-02-29', '2023-02-29',
                  '2026-11-16\n', '2026-11-16T17:00:99+99:99', '١٧:٠٥']
        values += [f'{year:04}-{month:02}-{day:02}' for year, month, day in itertools.product(
            (0, 1900, 2000, 2024, 2026), (0, 1, 2, 4, 12, 13), (0, 1, 28, 29, 30, 31, 32))]
        values += [f'{h}:{m:02}{s}' for h, m, s in itertools.product(
            ('0', '00', '09', '23', '24', '99'), (0, 59, 60, 99), ('', ':00', ':99', '\n'))]
        values += ['2026-11-16T' + value + offset for value in ('00:00', '23:59', '24:00', '05:60', '17:02:99.5')
                   for offset in ('', 'Z', '+07:00', '+0700', '+99:99', 'z', '\n')]
        for fmt, value in itertools.product(('date', 'date-time', 'time', 'unknown'), values):
            self.assertEqual(legacy.format_ok(value, fmt), new.format_ok(value, fmt), (value, fmt))

    def test_schema_catalogs_and_generated_edge_cases(self):
        # Catalogs are public tool descriptions, never environment state or labels.
        catalog = json.loads((ROOT / 'lifemate/public_test/public_test_tools_catalog.json').read_text())
        tools = legacy.catalog_tools(catalog)
        values = [None, '', [], {}, False, True, 0, 1, -1, 1.5, float('inf'), float('nan'),
                  '2026-11-16', '2026-11-16T17:00:99+99:99', '23:59', '24:00',
                  'abc', ['abc'], [False, 0], [[1]], {'x': 1}]
        rng = random.Random(20261116)
        checks = 0
        for name, tool in tools.items():
            props = tool.get('parameters', {}).get('properties', {})
            allowed = {name}
            for _ in range(60):
                args = {key: copy.deepcopy(rng.choice(values)) for key in props if rng.random() < .8}
                self.assertEqual(legacy.schema_error(name, args, [tool], allowed),
                                 new.schema_error(name, args, [tool], allowed), (name, args))
                checks += 1
            for key, spec in props.items():
                # No required fields here, so every property's type/bound/format branch is reached.
                isolated = {'name': name, 'parameters': {'properties': {key: spec}}}
                for value in values + list(spec.get('enum') or []):
                    args = {key: value}
                    self.assertEqual(legacy.schema_error(name, args, [isolated]), new.schema_error(name, args, [isolated]), (name, args))
                    checks += 1
        for kind in ('integer', 'number', 'string', 'array', 'object', 'boolean', 'unknown'):
            specs = [{'type': kind, 'minimum': 0, 'maximum': 1},
                     {'type': kind, 'exclusiveMinimum': 0, 'exclusiveMaximum': 1},
                     {'type': kind, 'enum': [True, 1, 'x']},
                     {'type': kind, 'items': {'type': 'array', 'items': {'type': 'integer'}}}]
            for spec, value in itertools.product(specs, values):
                c = [{'name': 'test.check', 'parameters': {'properties': {'value': spec}}}]
                self.assertEqual(legacy.schema_error('test.check', {'value': value}, c), new.schema_error('test.check', {'value': value}, c))
        for form in (None, [], {}, {'tools': []}, {'apps': []},
                     [{'name': 'a.b', 'parameters': {'required': ['a', 'b'], 'x-one-of': [['a'], ['b', 'c']]}}]):
            for name, args, allowed in itertools.product(('a.b', 'missing.x', None, 5), (None, [], {}, {'a': 0}, {'a': False}), (None, set(), {'a.b'})):
                self.assertEqual(legacy.schema_error(name, args, form, allowed), new.schema_error(name, args, form, allowed))
        print('Schema differential checks against actual public catalog:', checks)
        self.assertGreater(checks, 10000)

    def test_policy_code_changes_only_imports(self):
        for suffix in ('schema_feedback_review_v1/policy.py', 'scoped_adapter_read_review_v1/policy.py'):
            relative = Path('runtime/lifemate/experiments/continuous_improvement') / suffix
            expected = (OLD / relative).read_text().replace('from train.zaic_tools.validate import ', 'from k_schema_helpers import ')
            self.assertEqual(expected, (NEW / relative).read_text())

    def test_policy_imports_without_any_packaged_sdk(self):
        script = '''import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from experiments.continuous_improvement.schema_feedback_review_v1 import policy as a
from experiments.continuous_improvement.scoped_adapter_read_review_v1 import policy as b
import k_schema_helpers
assert a.format_ok is k_schema_helpers.format_ok
assert a.schema_error is b.schema_error is k_schema_helpers.schema_error
assert not any('zaic_tools' in name for name in sys.modules)
print(k_schema_helpers.__file__)
'''
        done = subprocess.run([sys.executable, '-B', '-c', script, str(NEW / 'runtime/lifemate')], text=True, capture_output=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(str(NEW / 'runtime/lifemate/k_schema_helpers.py'), done.stdout)


class RuntimeTests(unittest.TestCase):
    def test_no_packaged_sdk_or_direct_state_access(self):
        self.assertEqual(list(NEW.rglob('zaic_tools')), [])
        self.assertEqual(list(NEW.rglob('*_environment')), [])
        for path in (NEW / 'runtime/lifemate').rglob('*.py'):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    self.assertNotIn(node.attr, ('get_state', 'states', 'Executor', 'Simulator', 'load_environment'), str(path))
                if isinstance(node, ast.ImportFrom):
                    self.assertFalse((node.module or '').startswith('train.zaic_tools'), str(path))
            self.assertNotIn('_environment/', path.read_text(), str(path))

    def test_backend_selection_and_unchanged_transport(self):
        before, after = ast.parse((OLD / 'predict.py').read_text()), ast.parse((NEW / 'predict.py').read_text())
        node = next(n for n in after.body if isinstance(n, ast.FunctionDef) and n.name == 'backend_for_device')
        for tree in (before, after):
            tree.body = [n for n in tree.body if not isinstance(n, ast.FunctionDef) or n.name != 'backend_for_device']
        self.assertEqual(ast.dump(before), ast.dump(after))
        space = {'Path': Path}
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<backend>', 'exec'), space)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for kind in ('sm80', 'sm120'):
                (root / kind / 'bin').mkdir(parents=True)
                (root / kind / 'bin/llama-server').touch()
            for cap, expected in (((8, 0), 'sm80'), ((12, 0), 'sm120')):
                torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True, get_device_capability=lambda _: cap))
                with patch.dict(sys.modules, torch=torch):
                    self.assertEqual(space['backend_for_device'](root)[0], expected)
            with patch.dict(sys.modules, torch=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True, get_device_capability=lambda _: (9, 0)))):
                with self.assertRaisesRegex(RuntimeError, 'capability'): space['backend_for_device'](root)
            with patch.dict(sys.modules, torch=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))):
                with self.assertRaisesRegex(RuntimeError, 'CUDA GPU'): space['backend_for_device'](root)

    def test_hostname_fix_actual_candidate(self):
        relative = 'runtime/third_party/icefall-p12-3f848bb6/icefall/env.py'
        metadata = hostname_function((NEW / relative).read_text())()
        self.assertIsNone(metadata['IP address'])
        self.assertEqual(metadata['hostname'], 'unresolvable-host')

    def test_mounted_toolenv_with_synthetic_state_and_wrong_origin(self):
        relative = Path('runtime/lifemate/results/p19_submission_staging_v1/scripts/run_p10_audio.py')
        self.assertEqual((NEW / relative).read_bytes(), (OLD / relative).read_bytes())
        tree = ast.parse((NEW / relative).read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'tool_env_for_split')
        space = {'Path': Path, 'sys': sys, 'importlib': importlib}
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<factory>', 'exec'), space)
        old_path = sys.path[:]
        modules = {n: m for n, m in sys.modules.items() if n.startswith('zaic_tools')}
        try:
            for n in modules: del sys.modules[n]
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory); split = root / 'public_test'; split.mkdir()
                shutil.copytree(ROOT / 'lifemate/public_test/zaic_tools', split / 'zaic_tools', ignore=shutil.ignore_patterns('__pycache__'))
                state = split / 'public_test_environment/synthetic'; state.mkdir(parents=True)
                (state / 'state.json').write_text(json.dumps({'_meta': {'tools': [], 'current_time': '2026-11-16T17:00:00+07:00'}}))
                (split / 'public_test_tools_catalog.json').write_text('{"tools": []}')
                factory = space['tool_env_for_split'](root, 'public_test')
                self.assertEqual(Path(sys.modules[factory.__module__].__file__).resolve(), split / 'zaic_tools/__init__.py')
                env = factory('public_test', 'synthetic', root=root)  # exactly one synthetic instance
                self.assertEqual(env.get_tool_calls(), [])
                self.assertEqual(len(env.get_state_hash()), 64)
                self.assertFalse(env.validate('not.installed', {})['ok'])
                self.assertFalse(env.call('not.installed', {})['ok'])
                self.assertEqual(env.get_tool_calls(), [{'name': 'not.installed', 'arguments': {}}])
                with patch.dict(sys.modules, zaic_tools=SimpleNamespace(__file__='/code/bundled/zaic_tools/__init__.py')):
                    with self.assertRaisesRegex(RuntimeError, 'different split'): space['tool_env_for_split'](root, 'public_test')
                with self.assertRaises(ValueError): space['tool_env_for_split'](root, '../private_test')
        finally:
            for n in list(sys.modules):
                if n.startswith('zaic_tools'): del sys.modules[n]
            sys.modules.update(modules); sys.path[:] = old_path

    def test_environment_audit_allows_sdk_rejects_direct_reader(self):
        tree = ast.parse((HERE / 'container/sitecustomize.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'environment_reader')
        space = {'Path': Path, 'SDK': Path('/data/public_test/zaic_tools'), 'STDLIB': Path('/usr/lib/python3.12')}
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<audit>', 'exec'), space)
        def frame(filename, parent=None): return SimpleNamespace(f_code=SimpleNamespace(co_filename=filename), f_back=parent)
        stdlib = '/usr/lib/python3.12/pathlib.py'
        sdk = frame('/data/public_test/zaic_tools/__init__.py', frame('/code/predict.py'))
        direct = frame('/code/predict.py')
        self.assertTrue(space['environment_reader'](frame(stdlib, sdk))[0])
        self.assertFalse(space['environment_reader'](frame(stdlib, direct))[0])
        self.assertFalse(space['environment_reader'](frame('/code/runtime/lifemate/train/zaic_tools/__init__.py'))[0])

    def test_notebook_weights_dependencies_and_frozen_k_unchanged(self):
        for name in ('predict_notebook.ipynb', 'predict.sh', 'verify_release.py', 'manifests/models.json', 'manifests/python-files.json'):
            self.assertEqual((NEW / name).read_bytes(), (OLD / name).read_bytes(), name)
        self.assertEqual(hashlib.sha256((ROOT / 'lifemate/submissions/submission_K.jsonl').read_bytes()).hexdigest(),
                         'cf3a5a654fdfb59f0e8ddb385319ed6c74b3cb8595c6072456d9f64e4e777898')
        native = json.loads((NEW / 'manifests/native.json').read_text())
        old = json.loads((OLD / 'manifests/native.json').read_text())
        self.assertEqual(native[:len(old)], old)
        self.assertEqual(hashlib.sha256((NEW / 'native/sm80/bin/libggml-cuda.so').read_bytes()).hexdigest(),
                         'b33ce9eab9871e95a8b5436e57086bc8b6aeacad7d6e2f2fa72f704147b2d359')


class PackagingTests(unittest.TestCase):
    def test_single_pass_tar_gzip_and_checksum_roundtrip(self):
        import gzip
        import io
        import tarfile
        from package import HashWriter, SaveReader
        plain = io.BytesIO()
        payload = b'layer fixture bytes' * 1000
        with tarfile.open(fileobj=plain, mode='w') as archive:
            member = tarfile.TarInfo('layer.tar'); member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
        original = plain.getvalue(); plain.seek(0)
        output = io.BytesIO(); writer = HashWriter(output)
        with gzip.GzipFile(fileobj=writer, mode='wb', filename='', mtime=0) as compressed:
            stream = SaveReader(plain, compressed)
            with tarfile.open(fileobj=stream, mode='r|') as archive:
                for member in archive:
                    self.assertEqual(archive.extractfile(member).read(), payload)
            while stream.read(1024): pass
        encoded = output.getvalue()
        self.assertEqual(gzip.decompress(encoded), original)
        self.assertEqual(writer.size, len(encoded))
        self.assertEqual(writer.sha256.hexdigest(), hashlib.sha256(encoded).hexdigest())
        self.assertEqual(writer.md5.hexdigest(), hashlib.md5(encoded).hexdigest())

    def test_pilot_input_preflight_without_docker(self):
        import candidate
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); run = root / 'cpu_fixture'; run.mkdir()
            (root / 'BUILD.json').write_text('{"synthetic_cpu_test_fixture": true}')
            with patch.object(candidate, 'HERE', root), patch.object(candidate, 'check_context', return_value='cpu-test-fixture'):
                candidate.inputs(run, 'pilot')
            plan = json.loads((run / 'plan.json').read_text())
            self.assertEqual(plan['count'], 10)
            self.assertEqual(plan['expected_ids'], [f'public_{n:04d}' for n in [2, 3, 4, 5, 6, 7, 8, 9, 10, 12]])

    def test_build_fingerprint_rejects_runtime_and_filesystem_changes(self):
        from candidate import fingerprint
        image = json.loads((HERE / 'evidence/base-image-inspect.json').read_text())[0]
        original = fingerprint(image)
        for key, value in [('Architecture', 'arm64'), ('Os', 'windows'), ('Id', 'sha256:wrong'),
                           ('RootFS', {'Type': 'layers', 'Layers': ['sha256:wrong']})]:
            changed = copy.deepcopy(image); changed[key] = value
            self.assertNotEqual(original, fingerprint(changed))
        changed = copy.deepcopy(image); changed['Config']['Env'].append('UNVERIFIED=1')
        self.assertNotEqual(original, fingerprint(changed))

    def test_report_keeps_real_parity_separate_from_sdk_failure(self):
        import candidate
        saved = ROOT / 'lifemate-host-validation/runs/20261116T125938Z-cli-smoke-tj5doa'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); run = root / 'runs/test'; run.mkdir(parents=True)
            (root / 'overlay').symlink_to(NEW, target_is_directory=True)
            old_container = json.loads((saved / 'container-final.json').read_text())[0]
            (root / 'BUILD.json').write_text(json.dumps({'image': {'Id': old_container['Config']['Image']}}))
            for name in ('submission.jsonl', 'container-preflight.json', 'exit.json'):
                shutil.copy2(saved / name, run / name)
            shutil.copytree(saved / 'submission.diagnostics', run / 'submission.diagnostics')
            old_container['HostConfig']['ExtraHosts'] = []
            (run / 'container-final.json').write_text(json.dumps([old_container]))
            preflight = json.loads((run / 'container-preflight.json').read_text())
            preflight['predict_sha256'] = candidate.V.sha(NEW / 'predict.py')
            (run / 'container-preflight.json').write_text(json.dumps(preflight))
            (run / 'plan.json').write_text(json.dumps({'stage': 'smoke', 'count': 1, 'expected_ids': ['public_0002'],
                'build_sha256': candidate.V.sha(root / 'BUILD.json')}))
            (run / 'sdk-imports.bad.jsonl').write_text(json.dumps({'event': 'sdk_exec', 'path': '/code/zaic_tools/__init__.py', 'allowed': False}) + '\n')
            with patch.object(candidate, 'HERE', root), patch.object(candidate, 'check_image', return_value=None):
                self.assertEqual(candidate.analyze(run), 1)
            report = json.loads((run / 'report.json').read_text())
            self.assertTrue(report['behavioral_parity_pass'])
            self.assertFalse(report['sdk_checks_pass'])
            self.assertFalse(report['selected_stage_pass'])

    def test_archive_configuration_and_negative_metadata(self):
        from package import verify_metadata
        from candidate import I
        cfg = {'os': 'linux', 'architecture': 'amd64', 'rootfs': {'type': 'layers', 'diff_ids': ['sha256:layer']},
               'config': {'Env': ['A=B'], 'Cmd': ['run']}}
        image = {'Os': 'linux', 'Architecture': 'amd64', 'RootFS': {'Layers': ['sha256:layer']}, 'Config': I.normalized_config(cfg['config'])}
        objects = {'config.json': cfg, 'manifest.json': [{'Config': 'config.json', 'Layers': ['layer.tar'],
                    'RepoTags': ['lifemate-k:k48.46-20261116-rc2']}]}
        members = {'config.json': {'sha256': 'abc', 'bytes': 1}, 'layer.tar': {'sha256': 'layer', 'diff_id': 'sha256:layer', 'bytes': 1}}
        self.assertEqual(verify_metadata(objects, members, image)['image_config_digest'], 'sha256:abc')
        for key, value in [('architecture', 'arm64'), ('config', {'Cmd': ['wrong']}), ('rootfs', {'diff_ids': ['sha256:wrong']})]:
            bad = copy.deepcopy(objects); bad['config.json'][key] = value
            with self.assertRaises(Exception): verify_metadata(bad, members, image)
        with self.assertRaises(ValueError): verify_metadata(objects, {'config.json': members['config.json']}, image)
        bad = copy.deepcopy(objects); bad['manifest.json'][0]['RepoTags'] = []
        with self.assertRaises(ValueError): verify_metadata(bad, members, image)
        bad = copy.deepcopy(members); bad['layer.tar']['diff_id'] = 'sha256:tampered'
        with self.assertRaises(Exception): verify_metadata(objects, bad, image)

    def test_compressed_and_plain_layer_digests(self):
        import gzip
        from package import MemberDigest
        payload = b'example layer contents' * 20000
        for data in (payload, gzip.compress(payload)):
            digest = MemberDigest()
            for pos in range(0, len(data), 73): digest.update(data[pos:pos+73])
            stored, expanded = digest.finish()
            self.assertEqual(stored, hashlib.sha256(data).hexdigest())
            self.assertEqual(expanded, 'sha256:' + hashlib.sha256(payload).hexdigest())
        digest = MemberDigest(); digest.update(gzip.compress(payload)[:-5])
        with self.assertRaises(ValueError): digest.finish()

    def test_image_is_flattened_and_host_has_no_network_workaround(self):
        dockerfile = (HERE / 'Dockerfile').read_text()
        self.assertIn('FROM scratch\nCOPY --from=patched / /', dockerfile)
        script = (HERE / 'host.sh').read_text()
        self.assertNotIn('--add-host', script)
        self.assertNotIn('--hostname', script)
        self.assertIn('--network none', script)
        self.assertNotIn('docker load', script)
        self.assertNotIn('docker push', script)


if __name__ == '__main__':
    unittest.main()
