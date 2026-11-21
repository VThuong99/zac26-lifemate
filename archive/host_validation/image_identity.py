"""Verify sealed archive provenance and derive, rather than whitelist, store IDs.

No Docker calls, extraction, image mutation, or permissive DiffID-only fallback.
"""
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tarfile

RELEASE_MANIFEST_SHA256 = '27ea1b3fdd371cf76a85d6981329e81d28bf1e32b1f12dbbcfff87b243d1e7a9'
DEFAULT_RELEASE_MANIFEST = Path(__file__).resolve().parent.parent / 'lifemate-release-k-20261115/artifacts/ARTIFACTS.json'
DOCKER_MANIFEST = 'application/vnd.docker.distribution.manifest.v2+json'
OCI_MANIFEST = 'application/vnd.oci.image.manifest.v1+json'
OCI_INDEX = 'application/vnd.oci.image.index.v1+json'


class IdentityError(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__('Image identity verification failed:\n' + json.dumps(issues, ensure_ascii=False, indent=2))


def require_equal(field, expected, actual):
    if type(expected) is not type(actual) or expected != actual:
        raise IdentityError([{'field': field, 'expected': expected, 'actual': actual}])


def digest(raw):
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def compact(value, sort_keys=False):
    return json.dumps(value, separators=(',', ':'), sort_keys=sort_keys, ensure_ascii=False).encode('utf8')


def parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    def bad(value):
        raise ValueError('Non-finite JSON value: ' + value)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)


def authority(raw, trusted_sha256=None):
    expected = RELEASE_MANIFEST_SHA256 if trusted_sha256 is None else trusted_sha256
    require_equal('authoritative_release_manifest.sha256', expected, hashlib.sha256(raw).hexdigest())
    result = parse(raw)
    for key in ('archive', 'archive_sha256', 'archive_md5', 'archive_bytes', 'image_config_id',
                'oci_manifest_digest', 'uncompressed_layer_diff_id', 'local_tag'):
        if key not in result:
            raise IdentityError([{'field': 'release_manifest.' + key, 'expected': 'present', 'actual': 'missing'}])
    return result


class HashingReader:
    def __init__(self, stream):
        self.stream = stream
        self.sha256 = hashlib.sha256()
        self.md5 = hashlib.md5()
        self.size = 0

    def read(self, size=-1):
        data = self.stream.read(size)
        self.sha256.update(data); self.md5.update(data); self.size += len(data)
        return data


def _verify_sealed_archive(manifest_path, archive_path=None, *, trusted_sha256=None):
    """Single streaming pass: compressed SHA/MD5, gzip CRC, config and raw layer SHA.

    trusted_sha256 is only for isolated unit fixtures; the CLI has no override.
    No archive member is extracted to disk or interpreted as an inner filesystem.
    """
    manifest_path = Path(manifest_path)
    raw_authority = manifest_path.read_bytes()
    release = authority(raw_authority, trusted_sha256)
    # Historical /workspace prefix is not a host path. Locate the sibling archive.
    archive_path = Path(archive_path) if archive_path else manifest_path.parent / Path(release['archive']).name
    config_name = release['image_config_id'].split(':', 1)[1] + '.json'
    layer_name = release['uncompressed_layer_diff_id'].split(':', 1)[1] + '/layer.tar'
    small = {}; layers = []; seen = set()
    with archive_path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        reader = HashingReader(stream)
        with gzip.GzipFile(fileobj=reader, mode='rb') as uncompressed:
            with tarfile.open(fileobj=uncompressed, mode='r|', bufsize=1024 * 1024) as archive:
                for member in archive:
                    name = member.name.removeprefix('./')
                    if member.isdir():
                        continue
                    if name in seen or not member.isfile() or name not in ('manifest.json', config_name, layer_name):
                        raise IdentityError([{'field': 'archive.member', 'expected': 'unique sealed manifest/config/layer regular file', 'actual': name}])
                    if PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts:
                        raise IdentityError([{'field': 'archive.member.path', 'expected': 'relative path', 'actual': name}])
                    seen.add(name)
                    source = archive.extractfile(member)  # A read-only stream, not filesystem extraction.
                    if name != layer_name:
                        if member.size > 1024 * 1024:
                            raise IdentityError([{'field': name + '.size', 'expected': '<= 1 MiB JSON metadata', 'actual': member.size}])
                        small[name] = source.read().decode('utf8')
                    else:
                        h = hashlib.sha256(); size = 0
                        for block in iter(lambda: source.read(4 * 1024 * 1024), b''):
                            h.update(block); size += len(block)
                        require_equal('archive.layer.size', member.size, size)
                        layers.append({'path': name, 'digest': 'sha256:' + h.hexdigest(), 'size': size})
            # Validate gzip footer/CRC and include the complete compressed archive in the hash.
            while uncompressed.read(4 * 1024 * 1024):
                pass
        while reader.read(4 * 1024 * 1024):
            pass
        after = os.fstat(stream.fileno())
        require_equal('archive.stat_during_verification', [before.st_size, before.st_mtime_ns, before.st_ctime_ns],
                      [after.st_size, after.st_mtime_ns, after.st_ctime_ns])
    require_equal('archive.members', sorted(['manifest.json', config_name, layer_name]), sorted(seen))
    sealed = {
        'schema_version': 1, 'release_manifest_text': raw_authority.decode('utf8'),
        'release_manifest_sha256': hashlib.sha256(raw_authority).hexdigest(),
        'archive': {'name': archive_path.name, 'sha256': reader.sha256.hexdigest(),
                    'md5': reader.md5.hexdigest(), 'bytes': reader.size, 'gzip_crc_verified': True},
        'config_text': small[config_name], 'docker_save_manifest_text': small['manifest.json'], 'layers': layers,
    }
    verified_sealed_metadata(sealed, trusted_sha256=trusted_sha256)
    return sealed


def verify_sealed_archive(manifest_path, archive_path=None, *, trusted_sha256=None):
    try:
        return _verify_sealed_archive(manifest_path, archive_path, trusted_sha256=trusted_sha256)
    except IdentityError:
        raise
    except (OSError, EOFError, tarfile.TarError, UnicodeError) as error:
        raise IdentityError([{'field': 'sealed_archive.stream',
                              'expected': 'readable, complete gzip Docker-save archive with valid metadata',
                              'actual': str(error)}]) from error


def verified_sealed_metadata(sealed, *, trusted_sha256=None):
    """Recheck saved provenance/derivations; analysis does not reread 17 GB per report.

    The host run creates this measurement receipt by verify_sealed_archive. Analysis
    validates its contents against pinned release authority and retained inspect data.
    """
    require_equal('sealed.schema_version', 1, sealed.get('schema_version'))
    raw_authority = sealed['release_manifest_text'].encode('utf8')
    release = authority(raw_authority, trusted_sha256)
    require_equal('release_manifest_sha256', hashlib.sha256(raw_authority).hexdigest(), sealed['release_manifest_sha256'])
    measurement = sealed['archive']
    for name, key in [('sha256', 'archive_sha256'), ('md5', 'archive_md5'), ('bytes', 'archive_bytes')]:
        require_equal('sealed_archive.' + name, release[key], measurement.get(name))
    require_equal('sealed_archive.gzip_crc_verified', True, measurement.get('gzip_crc_verified'))
    require_equal('sealed_archive.name', Path(release['archive']).name, measurement.get('name'))
    config_raw = sealed['config_text'].encode('utf8')
    require_equal('image_configuration_digest', release['image_config_id'], digest(config_raw))
    config = parse(config_raw)
    require_equal('sealed_config.os', 'linux', config.get('os'))
    require_equal('sealed_config.architecture', 'amd64', config.get('architecture'))
    require_equal('sealed_config.rootfs', {'type': 'layers', 'diff_ids': [release['uncompressed_layer_diff_id']]}, config.get('rootfs'))
    layers = sealed['layers']
    require_equal('sealed_archive.layer_count', 1, len(layers))
    require_equal('sealed_archive.layer_diff_id', release['uncompressed_layer_diff_id'], layers[0]['digest'])
    require_equal('sealed_archive.layer_path', release['uncompressed_layer_diff_id'][7:] + '/layer.tar', layers[0]['path'])
    if type(layers[0]['size']) is not int or layers[0]['size'] <= 0:
        raise IdentityError([{'field': 'layer.size', 'expected': 'positive integer', 'actual': layers[0]['size']}])
    require_equal('docker_save_manifest', [{'Config': release['image_config_id'][7:] + '.json',
                                          'Layers': [layers[0]['path']], 'RepoTags': [release['local_tag']]}],
                  parse(sealed['docker_save_manifest_text']))
    descriptors = {}
    # Reproduce containerd's Docker-save importer serialization. No observed host ID is used.
    docker_manifest = {'schemaVersion': 2, 'mediaType': DOCKER_MANIFEST,
                       'config': {'mediaType': 'application/vnd.docker.container.image.v1+json',
                                  'digest': digest(config_raw), 'size': len(config_raw)},
                       'layers': [{'mediaType': 'application/vnd.docker.image.rootfs.diff.tar',
                                   'digest': x['digest'], 'size': x['size']} for x in layers]}
    def add(raw, media_type, kind):
        d = {'mediaType': media_type, 'digest': digest(raw), 'size': len(raw), 'kind': kind}
        descriptors[d['digest']] = d
        return d
    add(compact(docker_manifest), DOCKER_MANIFEST, 'containerd_docker_save_manifest')
    oci_manifest = {'schemaVersion': 2, 'mediaType': OCI_MANIFEST,
                    'config': {'mediaType': 'application/vnd.oci.image.config.v1+json',
                               'digest': digest(config_raw), 'size': len(config_raw)},
                    'layers': [{'mediaType': 'application/vnd.oci.image.layer.v1.tar',
                                'digest': x['digest'], 'size': x['size']} for x in layers]}
    oci_raw = compact(oci_manifest, sort_keys=True)
    require_equal('release_oci_manifest_digest', release['oci_manifest_digest'], digest(oci_raw))
    oci_desc = add(oci_raw, OCI_MANIFEST, 'sealed_oci_manifest')
    index = {'schemaVersion': 2, 'manifests': [{k: oci_desc[k] for k in ('mediaType', 'digest', 'size')} | {
        'platform': {'architecture': 'amd64', 'os': 'linux'},
        'annotations': {'org.opencontainers.image.ref.name': release['local_tag']}}]}
    index_desc = add(compact(index, sort_keys=True), OCI_INDEX, 'sealed_single_platform_oci_index')
    return {'release': release, 'config': config, 'config_digest': digest(config_raw),
            'rootfs_diff_ids': config['rootfs']['diff_ids'], 'descriptors': descriptors,
            'oci_index_digest': index_desc['digest']}


# Missing/null/empty API defaults have the same meaning; all nondefault fields are checked.
CONFIG_DEFAULTS = {
    'Hostname': '', 'Domainname': '', 'User': '', 'AttachStdin': False, 'AttachStdout': False,
    'AttachStderr': False, 'ExposedPorts': {}, 'Tty': False, 'OpenStdin': False, 'StdinOnce': False,
    'Env': [], 'Cmd': [], 'Healthcheck': None, 'ArgsEscaped': False, 'Image': '', 'Volumes': {},
    'WorkingDir': '', 'Entrypoint': [], 'NetworkDisabled': False, 'MacAddress': '',
    'OnBuild': [], 'Labels': {}, 'StopSignal': '', 'StopTimeout': None, 'Shell': [],
}


def normalized_config(config):
    if not isinstance(config, dict):
        raise IdentityError([{'field': 'Config', 'expected': 'object', 'actual': config}])
    unknown = sorted(set(config) - set(CONFIG_DEFAULTS))
    if unknown:
        raise IdentityError([{'field': 'Config.keys', 'expected': sorted(CONFIG_DEFAULTS), 'actual': sorted(config)}])
    result = {}
    for key, default in CONFIG_DEFAULTS.items():
        value = config.get(key)
        value = default if value is None else value
        if default is not None and type(value) is not type(default):
            raise IdentityError([{'field': 'Config.' + key, 'expected': type(default).__name__, 'actual': value}])
        if key == 'Env':
            env = {}
            for pair in value:
                if not isinstance(pair, str) or '=' not in pair or pair.split('=', 1)[0] in env:
                    raise IdentityError([{'field': 'Config.Env', 'expected': 'unique NAME=value entries', 'actual': value}])
                name, content = pair.split('=', 1); env[name] = content
            value = env
        result[key] = value
    return result


def verify_loaded_image(inspected, sealed, *, trusted_sha256=None):
    model = verified_sealed_metadata(sealed, trusted_sha256=trusted_sha256)
    if not isinstance(inspected, list) or len(inspected) != 1 or not isinstance(inspected[0], dict):
        raise IdentityError([{'field': 'inspect', 'expected': 'exactly one image object', 'actual': inspected}])
    obj = inspected[0]; issues = []
    def compare(field, expected, actual):
        if type(expected) is not type(actual) or expected != actual:
            issues.append({'field': field, 'expected': expected, 'actual': actual})
    compare('Os', model['config']['os'], obj.get('Os'))
    compare('Architecture', model['config']['architecture'], obj.get('Architecture'))
    compare('Variant', model['config'].get('variant', ''), obj.get('Variant') or '')
    compare('OsVersion', model['config'].get('os.version', ''), obj.get('OsVersion') or '')
    compare('OsFeatures', model['config'].get('os.features', []), obj.get('OsFeatures') or [])
    compare('RootFS', {'Type': 'layers', 'Layers': model['rootfs_diff_ids']}, obj.get('RootFS'))
    expected_config = normalized_config(model['config']['config'])
    try:
        actual_config = normalized_config(obj.get('Config'))
        for key in CONFIG_DEFAULTS:
            compare('Config.' + key, expected_config[key], actual_config[key])
    except IdentityError as e:
        issues += e.issues
    store_id = obj.get('Id'); descriptor = obj.get('Descriptor')
    semantics = 'legacy_configuration_digest' if store_id == model['config_digest'] else 'containerd_target_descriptor'
    expected_descriptor = model['descriptors'].get(store_id) if isinstance(store_id, str) else None
    if semantics == 'containerd_target_descriptor' and expected_descriptor is None:
        compare('DockerStoreImageID', [model['config_digest'], *model['descriptors']], store_id)
    # A target ID requires its authenticated descriptor; legacy may omit it.
    if descriptor is not None or semantics != 'legacy_configuration_digest':
        if not isinstance(descriptor, dict):
            compare('Descriptor', 'authenticated manifest/index descriptor', descriptor)
        else:
            descriptor_digest = descriptor.get('digest')
            desc = model['descriptors'].get(descriptor_digest) if isinstance(descriptor_digest, str) else None
            if desc is None:
                compare('Descriptor.digest', list(model['descriptors']), descriptor.get('digest'))
            else:
                for key in ('digest', 'mediaType', 'size'):
                    compare('Descriptor.' + key, desc[key], descriptor.get(key))
                if semantics != 'legacy_configuration_digest':
                    compare('Descriptor.digest_vs_store_id', store_id, descriptor.get('digest'))
                if 'platform' in descriptor:
                    compare('Descriptor.platform', {'architecture': 'amd64', 'os': 'linux'}, descriptor['platform'])
    if issues:
        raise IdentityError(issues)
    return {'image_config_digest': model['config_digest'], 'release_oci_manifest_digest': model['release']['oci_manifest_digest'],
            'release_oci_index_digest': model['oci_index_digest'], 'docker_store_image_id': store_id,
            'docker_store_id_semantics': semantics, 'store_descriptor': descriptor,
            'verified_docker_image_reference': store_id, 'rootfs_diff_ids': model['rootfs_diff_ids'],
            'derived_target_descriptors': model['descriptors'], 'os': obj['Os'], 'architecture': obj['Architecture'],
            'runtime_config_verified': True}


def make_identity_record(inspect_path, sealed, *, trusted_sha256=None):
    inspect_raw = Path(inspect_path).read_bytes()
    identity = verify_loaded_image(parse(inspect_raw), sealed, trusted_sha256=trusted_sha256)
    return {'schema_version': 1, 'sealed_archive_verification': sealed,
            'image_inspect_sha256': hashlib.sha256(inspect_raw).hexdigest(), **identity}


def read_identity_record(path, inspect_path, *, trusted_sha256=None):
    record = parse(Path(path).read_bytes())
    require_equal('identity.schema_version', 1, record.get('schema_version'))
    reconstructed = make_identity_record(inspect_path, record['sealed_archive_verification'], trusted_sha256=trusted_sha256)
    require_equal('verified_identity_record', reconstructed, record)
    return record


def verify_container_reference(inspected, identity):
    """Container APIs may retain config ID or target ID; both must be bound to this receipt.

    Config.Image must still name the exact immutable reference requested by our runner.
    """
    if not isinstance(inspected, list) or len(inspected) != 1 or not isinstance(inspected[0], dict):
        raise IdentityError([{'field': 'container.inspect', 'expected': 'one container object', 'actual': inspected}])
    obj = inspected[0]
    allowed = {identity['image_config_digest'], identity['docker_store_image_id']}
    if obj.get('Image') not in allowed:
        raise IdentityError([{'field': 'container.Image', 'expected': sorted(allowed), 'actual': obj.get('Image')}])
    require_equal('container.Config.Image', identity['verified_docker_image_reference'], obj.get('Config', {}).get('Image'))
    return True
