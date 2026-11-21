"""CPU-only regression tests for the actual completed rc2 build and resume path."""
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'tools'))
import candidate as C
import package as P

SAVED = HERE / 'runs/20261116T135201Z-build-RNHQa5/image-inspect.json'


class LinuxConfigTests(unittest.TestCase):
    def test_complete_observed_difference_is_only_argsescaped(self):
        correction = C.read(HERE / 'evidence/identity-correction.json')
        self.assertEqual(correction['complete_config_diff'],
                         {'ArgsEscaped': {'expected': False, 'actual': True}})
        actual = C.read(SAVED)[0]
        expected = copy.deepcopy(C.read(HERE / 'evidence/base-image-inspect.json')[0]['Config'])
        expected['Labels'].update({key: value for key, value in actual['Config']['Labels'].items()
                                   if key in ('org.opencontainers.image.version', 'org.opencontainers.image.description')})
        left, right = C.I.normalized_config(expected), C.I.normalized_config(actual['Config'])
        self.assertEqual([key for key in left if left[key] != right[key]], ['ArgsEscaped'])
        self.assertEqual(C.normalized_config(expected, 'linux'), C.normalized_config(actual['Config'], 'linux'))

    def test_linux_boolean_variants_and_json_order(self):
        original = {'Cmd': ['run', '--strict'], 'Env': ['A=B'], 'Labels': {'a': '1', 'b': '2'}}
        expected = C.normalized_config(original, 'linux')
        for value in (False, True, None):
            config = dict(reversed(list(original.items()))); config['ArgsEscaped'] = value
            self.assertEqual(expected, C.normalized_config(config, 'linux'))
            self.assertEqual(config['ArgsEscaped'], value)  # normalization never mutates input

    def test_windows_and_unknown_os_do_not_ignore_argsescaped(self):
        for os_name in ('windows', 'unknown', ''):
            self.assertNotEqual(C.normalized_config({'ArgsEscaped': False}, os_name),
                                C.normalized_config({'ArgsEscaped': True}, os_name))

    def test_malformed_argsescaped_and_unknown_config_fail(self):
        for value in ('true', 1, 0, [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                C.normalized_config({'ArgsEscaped': value}, 'linux')
        with self.assertRaises(ValueError): C.normalized_config({'UnrecognizedSecurityField': True}, 'linux')

    def test_every_other_configuration_field_remains_significant(self):
        baseline = C.normalized_config({}, 'linux')
        for key, default in C.I.CONFIG_DEFAULTS.items():
            if key == 'ArgsEscaped':
                continue
            if key == 'Env': value = ['SECURITY=changed']
            elif isinstance(default, bool): value = not default
            elif isinstance(default, str): value = 'changed'
            elif isinstance(default, list): value = ['changed']
            elif isinstance(default, dict): value = {'changed': 'value'}
            elif key == 'Healthcheck': value = {'Test': ['CMD', 'false']}
            else: value = 42
            with self.subTest(field=key):
                self.assertNotEqual(baseline, C.normalized_config({key: value}, 'linux'))
        with self.assertRaises(ValueError): C.normalized_config({'Env': ['A=1', 'A=2']}, 'linux')

    def test_actual_build_metadata_and_empty_layer_are_valid(self):
        image = C.read(SAVED)[0]
        C.validate_build_metadata(image)
        self.assertEqual(image['RootFS']['Layers'][1], 'sha256:' + hashlib.sha256(bytes(1024)).hexdigest())
        self.assertEqual(len(image['RootFS']['Layers']), 2)

    def test_changed_runtime_platform_and_extra_nonempty_layer_rejected(self):
        image = C.read(SAVED)[0]
        mutations = [('Os', 'windows'), ('Architecture', 'arm64'),
                     ('RootFS', {'Type': 'invalid', 'Layers': image['RootFS']['Layers']}),
                     ('RootFS', {'Type': 'layers', 'Layers': image['RootFS']['Layers'] + [C.EMPTY_TAR_DIFF_ID]}),
                     ('RootFS', {'Type': 'layers', 'Layers': [image['RootFS']['Layers'][0], 'sha256:' + 'a' * 64]})]
        for key, value in mutations:
            bad = copy.deepcopy(image); bad[key] = value
            with self.subTest(field=key, value=value), self.assertRaises(ValueError): C.validate_build_metadata(bad)
        for key, value in [('Cmd', ['unexpected']), ('Entrypoint', ['/bad']), ('User', 'unexpected'),
                           ('Env', ['PATH=/bad']), ('WorkingDir', '/bad'), ('Volumes', {'/secret': {}}),
                           ('Healthcheck', {'Test': ['CMD', 'false']}), ('Labels', {})]:
            bad = copy.deepcopy(image); bad['Config'][key] = value
            with self.subTest(field=key), self.assertRaises(ValueError): C.validate_build_metadata(bad)


class ResumeTests(unittest.TestCase):
    def test_actual_original_build_provenance(self):
        correction, image = C.original_build_provenance()
        self.assertEqual(image['Id'], correction['oci_manifest_digest'])
        self.assertEqual(correction['image_config_digest'],
                         'sha256:00cf5905325e57fa68e7034d4e773bc81fcea8e347d41c3e3e100e47de486306')

    def test_original_image_input_and_build_evidence_tampering_rejected(self):
        original_sha = C.V.sha
        for relative in ('overlay/predict.py', 'Dockerfile', 'container/sitecustomize.py',
                         'runs/20261116T135201Z-build-RNHQa5/build.log',
                         'evidence/identity-before/CONTEXT_SHA256.json'):
            def altered(path):
                return '0' * 64 if Path(path) == HERE / relative else original_sha(path)
            with self.subTest(file=relative), patch.object(C, 'check_context', return_value='fixture'), \
                    patch.object(C.V, 'sha', side_effect=altered), self.assertRaises(ValueError):
                C.original_build_provenance()

    def test_resume_pins_existing_image_records_provenance_and_is_repeatable(self):
        correction = C.read(HERE / 'evidence/identity-correction.json'); image = C.read(SAVED)[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); run = root / 'runs/verify'; run.mkdir(parents=True)
            (root / 'evidence').mkdir()
            for name in ('base-image-inspect.json', 'base-image-identity.json', 'identity-correction.json'):
                shutil.copy2(HERE / 'evidence' / name, root / 'evidence' / name)
            shutil.copy2(SAVED, run / 'image-inspect.json')
            with patch.object(C, 'HERE', root), patch.object(C, 'check_context', return_value='fixture'), \
                    patch.object(C, 'original_build_provenance', return_value=(correction, image)), redirect_stdout(io.StringIO()):
                C.resume_build(run)
                built_bytes = (root / 'BUILD.json').read_bytes()
                C.resume_build(run)
                self.assertEqual(built_bytes, (root / 'BUILD.json').read_bytes())
                built = C.read(root / 'BUILD.json')
                self.assertTrue(built['resumed_without_rebuild'])
                self.assertTrue(built['raw_args_escaped'])
                self.assertFalse(built['image']['Config']['ArgsEscaped'])
                self.assertEqual(built['image_config_digest'], correction['image_config_digest'])
                for key, value in [('Id', 'sha256:' + '0' * 64),
                                   ('RootFS', {'Type': 'layers', 'Layers': [C.EMPTY_TAR_DIFF_ID]})]:
                    bad = copy.deepcopy(image); bad[key] = value
                    (run / 'image-inspect.json').write_text(json.dumps([bad]))
                    with self.subTest(field=key), self.assertRaises(ValueError): C.resume_build(run)
                bad = copy.deepcopy(image); bad['Config']['ArgsEscaped'] = False
                (run / 'image-inspect.json').write_text(json.dumps([bad]))
                with self.assertRaises(ValueError): C.resume_build(run)

    def test_resume_shell_sequence_never_builds_and_stops_on_failure(self):
        script = (HERE / 'host.sh').read_text()
        block = script.split('if [[ "$MODE" == resume ]]; then', 1)[1].split('\nfi', 1)[0]
        for failure in ('', 'pilot'):
            program = ('set -euo pipefail\nHERE=/fixture; GPU=0\n'
                       'python3() { return 1; }\n'
                       'bash() { echo "$2"; [[ "$2" != "' + failure + '" ]]; }\n' + block)
            result = subprocess.run(['/bin/bash', '-c', program], text=True, capture_output=True)
            expected = ['verify', 'gpu', 'smoke', 'pilot']
            if not failure: expected += ['notebook', 'package']
            self.assertEqual(result.stdout.splitlines(), expected)
            self.assertEqual(result.returncode, 1 if failure else 0)


class ArchiveIdentityTests(unittest.TestCase):
    def fixture(self, escaped=True):
        cfg = {'os': 'linux', 'architecture': 'amd64', 'rootfs': {'type': 'layers', 'diff_ids': ['sha256:layer']},
               'config': {'ArgsEscaped': escaped, 'Cmd': ['run']}}
        digest = hashlib.sha256(json.dumps(cfg).encode()).hexdigest()
        name = 'blobs/sha256/' + digest
        manifest = {'config': {'digest': 'sha256:' + digest, 'size': 123}, 'layers': []}
        manifest_digest = hashlib.sha256(json.dumps(manifest).encode()).hexdigest()
        manifest_path = 'blobs/sha256/' + manifest_digest
        objects = {name: cfg, manifest_path: manifest, 'manifest.json': [{'Config': name, 'Layers': ['layer.tar'],
                   'RepoTags': ['lifemate-k:k48.46-20261116-rc2']}]}
        members = {name: {'sha256': digest, 'bytes': 123}, manifest_path: {'sha256': manifest_digest, 'bytes': 234},
                   'layer.tar': {'sha256': 'layer', 'diff_id': 'sha256:layer', 'bytes': 100}}
        image = {'Os': 'linux', 'Architecture': 'amd64', 'RootFS': {'Type': 'layers', 'Layers': ['sha256:layer']},
                 'Config': C.normalized_config(cfg['config'], 'linux')}
        return objects, members, image, 'sha256:' + digest, 'sha256:' + manifest_digest

    def test_linux_semantics_accept_both_boolean_representations(self):
        for escaped in (False, True):
            objects, members, image, config_digest, manifest_digest = self.fixture(escaped)
            self.assertEqual(P.verify_metadata(objects, members, image, config_digest, manifest_digest)['image_config_digest'], config_digest)

    def test_semantically_equivalent_config_with_wrong_bytes_still_fails(self):
        objects, members, image, config_digest, manifest_digest = self.fixture(True)
        other_digest = self.fixture(False)[3]
        self.assertNotEqual(config_digest, other_digest)
        with self.assertRaisesRegex(ValueError, 'saved.build_config_digest'):
            P.verify_metadata(objects, members, image, other_digest, manifest_digest)
        with self.assertRaisesRegex(ValueError, 'Saved build manifest missing'):
            P.verify_metadata(objects, members, image, config_digest, 'sha256:' + '0' * 64)

    def test_changed_runtime_layer_content_and_windows_escaping_fail(self):
        objects, members, image, config_digest, manifest_digest = self.fixture()
        name = 'blobs/' + config_digest.replace(':', '/')
        for key, value in [('os', 'windows'), ('architecture', 'arm64'), ('config', {'Cmd': ['bad']}),
                           ('rootfs', {'type': 'unknown', 'diff_ids': ['sha256:layer']})]:
            bad = copy.deepcopy(objects); bad[name][key] = value
            with self.subTest(field=key), self.assertRaises(ValueError): P.verify_metadata(bad, members, image)
        bad_members = copy.deepcopy(members); bad_members['layer.tar']['diff_id'] = 'sha256:tampered'
        with self.assertRaises(ValueError): P.verify_metadata(objects, bad_members, image)
        objects[name]['os'] = image['Os'] = 'windows'
        with self.assertRaises(ValueError): P.verify_metadata(objects, members, image)


if __name__ == '__main__':
    unittest.main()
