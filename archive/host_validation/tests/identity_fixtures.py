"""Small synthetic archives for CPU-only identity verification tests."""
import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
from types import SimpleNamespace

from image_identity import compact, digest, OCI_MANIFEST, verify_sealed_archive, verified_sealed_metadata


def build_fixture(root):
    root = Path(root); root.mkdir()
    layer = b'synthetic uncompressed filesystem content for identity tests\n'
    diff_id = digest(layer)
    config = {'architecture': 'amd64', 'os': 'linux', 'created': '2026-11-15T00:00:00Z',
              'rootfs': {'type': 'layers', 'diff_ids': [diff_id]},
              'config': {'Cmd': ['/bin/bash', '/code/predict.sh'], 'Entrypoint': ['/entry.sh'],
                         'WorkingDir': '/code', 'Env': ['A=one', 'HF_HUB_OFFLINE=1'],
                         'Labels': {'release': 'sealed'}, 'OnBuild': None}}
    raw = compact(config)
    config_id = digest(raw)
    manifest = [{'Config': config_id[7:] + '.json', 'Layers': [diff_id[7:] + '/layer.tar'], 'RepoTags': ['lifemate-k:test']}]
    path = root / 'sealed.tar.gz'
    with tarfile.open(path, 'w:gz') as archive:
        for name, content in [('manifest.json', compact(manifest)), (config_id[7:] + '.json', raw), (diff_id[7:] + '/layer.tar', layer)]:
            member = tarfile.TarInfo(name); member.size = len(content); archive.addfile(member, io.BytesIO(content))
    oci = {'schemaVersion': 2, 'mediaType': OCI_MANIFEST,
           'config': {'mediaType': 'application/vnd.oci.image.config.v1+json', 'digest': config_id, 'size': len(raw)},
           'layers': [{'mediaType': 'application/vnd.oci.image.layer.v1.tar', 'digest': diff_id, 'size': len(layer)}]}
    release = {'archive': '/original/workspace/sealed.tar.gz', 'archive_bytes': path.stat().st_size,
               'archive_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'archive_md5': hashlib.md5(path.read_bytes()).hexdigest(),
               'image_config_id': config_id, 'oci_manifest_digest': digest(compact(oci, sort_keys=True)),
               'uncompressed_layer_diff_id': diff_id, 'local_tag': 'lifemate-k:test'}
    release_path = root / 'ARTIFACTS.json'; release_path.write_bytes(compact(release))
    trust = hashlib.sha256(release_path.read_bytes()).hexdigest()
    sealed = verify_sealed_archive(release_path, trusted_sha256=trust)
    return SimpleNamespace(root=root, path=path, release=release, release_path=release_path, trust=trust, sealed=sealed, config=config)


def inspected(fixture, kind='legacy'):
    model = verified_sealed_metadata(fixture.sealed, trusted_sha256=fixture.trust)
    obj = {'Id': model['config_digest'], 'Os': 'linux', 'Architecture': 'amd64',
           'RootFS': {'Type': 'layers', 'Layers': model['rootfs_diff_ids']}, 'Config': copy.deepcopy(fixture.config['config'])}
    if kind != 'legacy':
        desc = next(x for x in model['descriptors'].values() if x['kind'] == kind)
        obj['Id'] = desc['digest']
        obj['Descriptor'] = {k: desc[k] for k in ('mediaType', 'digest', 'size')}
    return [obj]
