import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from image_identity import (IdentityError, compact, digest, authority, verify_sealed_archive,
                            verified_sealed_metadata, verify_loaded_image, make_identity_record, read_identity_record, verify_container_reference)
from identity_fixtures import build_fixture, inspected


class ImageIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.f = build_fixture(self.root / 'release')
    def tearDown(self): self.temp.cleanup()
    def check(self, value): return verify_loaded_image(value, self.f.sealed, trusted_sha256=self.f.trust)

    def test_legacy_config_id(self):
        report = self.check(inspected(self.f))
        self.assertEqual(report['docker_store_id_semantics'], 'legacy_configuration_digest')
        self.assertEqual(report['verified_docker_image_reference'], self.f.release['image_config_id'])

    def test_containerd_manifest_id_is_derived_from_archive(self):
        value = inspected(self.f, 'containerd_docker_save_manifest'); report = self.check(value)
        self.assertNotEqual(report['image_config_digest'], report['docker_store_image_id'])
        self.assertEqual(report['verified_docker_image_reference'], value[0]['Id'])
        self.assertEqual(report['docker_store_id_semantics'], 'containerd_target_descriptor')

    def test_containerd_authenticated_oci_manifest_and_index(self):
        for kind in ('sealed_oci_manifest', 'sealed_single_platform_oci_index'):
            with self.subTest(kind=kind): self.assertTrue(self.check(inspected(self.f, kind))['runtime_config_verified'])

    def test_legacy_and_containerd_reject_all_changed_runtime_fields(self):
        changes = {'Entrypoint': ['/evil'], 'Cmd': ['/evil'], 'Env': ['A=other'], 'WorkingDir': '/elsewhere',
                   'User': 'unexpected', 'Labels': {'release': 'changed'}, 'OnBuild': ['RUN evil'],
                   'Volumes': {'/data': {}}, 'ExposedPorts': {'80/tcp': {}}, 'Healthcheck': {'Test': ['CMD', 'false']},
                   'Shell': ['/evil'], 'StopSignal': 'SIGKILL', 'StopTimeout': 42, 'NetworkDisabled': True,
                   'Tty': True, 'ArgsEscaped': True, 'UnexpectedField': 'new'}
        for kind in ('legacy', 'containerd_docker_save_manifest'):
            for field, value in changes.items():
                with self.subTest(kind=kind, field=field):
                    obj = inspected(self.f, kind); obj[0]['Config'][field] = value
                    with self.assertRaises(IdentityError) as error: self.check(obj)
                    self.assertIn('expected', str(error.exception)); self.assertIn('actual', str(error.exception))

    def test_both_stores_reject_os_arch_and_rootfs_changes(self):
        changes = {'Os': 'windows', 'Architecture': 'arm64', 'Variant': 'v8',
                   'RootFS': {'Type': 'layers', 'Layers': ['sha256:' + 'f' * 64]}}
        for kind in ('legacy', 'containerd_docker_save_manifest'):
            for field, value in changes.items():
                with self.subTest(kind=kind, field=field):
                    obj = inspected(self.f, kind); obj[0][field] = value
                    with self.assertRaises(IdentityError): self.check(obj)

    def test_same_rootfs_and_runtime_with_unbound_id_rejected(self):
        for kind in ('legacy', 'containerd_docker_save_manifest'):
            obj = inspected(self.f, kind); obj[0]['Id'] = 'sha256:' + 'a' * 64
            obj[0]['RepoDigests'] = ['lifemate-k@' + obj[0]['Id']]
            with self.assertRaises(IdentityError): self.check(obj)

    def test_containerd_requires_matching_descriptor_digest_type_and_size(self):
        for key, value in [('digest', 'sha256:' + 'b' * 64), ('mediaType', 'untrusted'), ('size', 12)]:
            obj = inspected(self.f, 'containerd_docker_save_manifest'); obj[0]['Descriptor'][key] = value
            with self.assertRaises(IdentityError): self.check(obj)
        obj = inspected(self.f, 'containerd_docker_save_manifest'); del obj[0]['Descriptor']
        with self.assertRaises(IdentityError): self.check(obj)

    def test_legacy_cannot_hide_conflicting_descriptor(self):
        obj = inspected(self.f); obj[0]['Descriptor'] = {'digest': 'sha256:' + 'c' * 64}
        with self.assertRaises(IdentityError): self.check(obj)

    def test_default_elision_and_environment_order_are_supported(self):
        for kind in ('legacy', 'containerd_docker_save_manifest'):
            obj = inspected(self.f, kind); obj[0]['Config'].pop('OnBuild'); obj[0]['Config']['User'] = ''
            obj[0]['Config']['Env'].reverse()
            self.check(obj)

    def test_duplicate_env_and_unknown_identity_record_fail_closed(self):
        obj = inspected(self.f); obj[0]['Config']['Env'].append('A=two')
        with self.assertRaises(IdentityError): self.check(obj)
        with self.assertRaises((IdentityError, KeyError)): verify_loaded_image(inspected(self.f), {}, trusted_sha256=self.f.trust)

    def test_archive_hash_size_and_md5_checks(self):
        for field in ('sha256', 'md5', 'bytes'):
            sealed = copy.deepcopy(self.f.sealed); sealed['archive'][field] = 0 if field == 'bytes' else '0' * 64
            with self.assertRaises(IdentityError) as error: verified_sealed_metadata(sealed, trusted_sha256=self.f.trust)
            self.assertIn('sealed_archive.' + field, str(error.exception))

    def test_untrusted_release_manifest_rejected(self):
        raw = self.f.release_path.read_bytes() + b' '
        with self.assertRaises(IdentityError): authority(raw, self.f.trust)
        with self.assertRaises(IdentityError): verify_sealed_archive(self.f.release_path)  # No production trust override.

    def test_archive_configuration_identity_is_independent_of_rootfs(self):
        sealed = copy.deepcopy(self.f.sealed)
        config = json.loads(sealed['config_text']); config['config']['Cmd'] = ['/evil']
        sealed['config_text'] = compact(config).decode()
        with self.assertRaises(IdentityError) as error: verified_sealed_metadata(sealed, trusted_sha256=self.f.trust)
        self.assertIn('image_configuration_digest', str(error.exception))

    def test_archive_layer_identity_and_manifest_reference_required(self):
        for change in ('layer', 'manifest'):
            sealed = copy.deepcopy(self.f.sealed)
            if change == 'layer': sealed['layers'][0]['digest'] = 'sha256:' + 'e' * 64
            else: sealed['docker_save_manifest_text'] = '[{"Config":"other"}]'
            with self.assertRaises(IdentityError): verified_sealed_metadata(sealed, trusted_sha256=self.f.trust)

    def test_receipt_binds_actual_inspect_bytes_and_execution_reference(self):
        path = self.root / 'inspect.json'; path.write_text(json.dumps(inspected(self.f, 'containerd_docker_save_manifest')))
        record = make_identity_record(path, self.f.sealed, trusted_sha256=self.f.trust)
        receipt = self.root / 'identity.json'; receipt.write_text(json.dumps(record))
        read_identity_record(receipt, path, trusted_sha256=self.f.trust)
        record['verified_docker_image_reference'] = self.f.release['image_config_id']; receipt.write_text(json.dumps(record))
        with self.assertRaises(IdentityError): read_identity_record(receipt, path, trusted_sha256=self.f.trust)
        record = make_identity_record(path, self.f.sealed, trusted_sha256=self.f.trust); receipt.write_text(json.dumps(record))
        path.write_text(path.read_text() + '\n')
        with self.assertRaises(IdentityError): read_identity_record(receipt, path, trusted_sha256=self.f.trust)

    def test_container_identity_requires_bound_digest_and_exact_requested_reference(self):
        for kind in ('legacy', 'containerd_docker_save_manifest'):
            record = self.check(inspected(self.f, kind))
            for stored in (record['image_config_digest'], record['docker_store_image_id']):
                obj = [{'Image': stored, 'Config': {'Image': record['verified_docker_image_reference']}}]
                self.assertTrue(verify_container_reference(obj, record))
                obj[0]['Config']['Image'] = 'lifemate-k:mutable-tag'
                with self.assertRaises(IdentityError): verify_container_reference(obj, record)
            with self.assertRaises(IdentityError):
                verify_container_reference([{'Image': 'sha256:' + 'a' * 64, 'Config': {'Image': record['verified_docker_image_reference']}}], record)

    def test_truncated_archive_fails_with_expected_actual_diagnostics(self):
        data = self.f.path.read_bytes(); self.f.path.write_bytes(data[:len(data)//2])
        with self.assertRaises(IdentityError) as error:
            verify_sealed_archive(self.f.release_path, trusted_sha256=self.f.trust)
        self.assertIn('expected', str(error.exception)); self.assertIn('actual', str(error.exception))

    def test_malformed_or_multiple_inspect_objects_rejected(self):
        for value in ([], {}, [inspected(self.f)[0]] * 2):
            with self.assertRaises(IdentityError): self.check(value)


class ReleaseIdentityRegressionTests(unittest.TestCase):
    def test_actual_host_descriptor_from_verified_full_archive(self):
        root = Path(__file__).resolve().parents[1]
        check = root / 'local_checks/identity-correction-dMA4RU'
        record = read_identity_record(check / 'image-identity.json', check / 'image-inspect.json')
        self.assertEqual(record['image_config_digest'], 'sha256:ca9030a7989aed1279c3ad850bc49d2a9950fc6b74c10bcb96811785757b8247')
        self.assertEqual(record['verified_docker_image_reference'], 'sha256:92212d536574ef62f6ab32edaf4c9ce926e64ffb4863e6864bd61c979d708755')
        self.assertEqual(record['store_descriptor']['size'], 427)
        actual = json.loads((check / 'image-inspect.json').read_text())
        actual[0]['Id'] = record['image_config_digest']; del actual[0]['Descriptor']
        verify_loaded_image(actual, record['sealed_archive_verification'])
        actual[0]['Config']['Entrypoint'] = ['/unexpected']
        with self.assertRaises(IdentityError): verify_loaded_image(actual, record['sealed_archive_verification'])


if __name__ == '__main__': unittest.main()
