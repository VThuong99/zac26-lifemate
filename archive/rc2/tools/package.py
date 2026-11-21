"""One-pass Docker save, compressed checksums, archive metadata verification. No upload."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import zlib
from datetime import datetime, timezone

from candidate import HERE, V, I, check_context, normalized_config, prerequisite, read, write


class HashWriter:
    def __init__(self, stream):
        self.stream = stream
        self.sha256 = hashlib.sha256()
        self.md5 = hashlib.md5()
        self.size = 0

    def write(self, block):
        result = self.stream.write(block)
        self.sha256.update(block)
        self.md5.update(block)
        self.size += len(block)
        return result

    def flush(self):
        self.stream.flush()


class SaveReader:
    def __init__(self, source, compressed):
        self.source, self.compressed = source, compressed
        self.bytes_read, self.next_update = 0, 1024**3

    def read(self, size=-1):
        block = self.source.read(size)
        self.compressed.write(block)
        self.bytes_read += len(block)
        if self.bytes_read >= self.next_update:
            print(f'Export stream: {self.bytes_read / 1024**3:.1f} GiB processed', flush=True)
            self.next_update += 1024**3
        return block


class MemberDigest:
    """Digest stored bytes and, for gzip layers, bounded uncompressed bytes."""
    def __init__(self):
        self.raw = hashlib.sha256()
        self.expanded = hashlib.sha256()
        self.decoder = None
        self.started = False

    def update(self, block):
        if not self.started:
            self.started = True
            if block.startswith(b'\x1f\x8b'):
                self.decoder = zlib.decompressobj(31)
        self.raw.update(block)
        if self.decoder is None:
            self.expanded.update(block)
        else:
            while block:
                self.expanded.update(self.decoder.decompress(block, 8 * 1024**2))
                block = self.decoder.unconsumed_tail

    def finish(self):
        if self.decoder is not None:
            self.expanded.update(self.decoder.flush())
            if not self.decoder.eof or self.decoder.unused_data:
                raise ValueError('Incomplete or concatenated gzip member')
        return self.raw.hexdigest(), 'sha256:' + self.expanded.hexdigest()


def verify_metadata(objects, members, image, expected_config_digest=None, expected_manifest_digest=None):
    configs = [(name, obj) for name, obj in objects.items()
               if isinstance(obj, dict) and 'rootfs' in obj and 'architecture' in obj]
    if len(configs) != 1:
        raise ValueError('Expected one saved image configuration; actual: ' + repr([n for n, _ in configs]))
    name, config = configs[0]
    I.require_equal('saved.OS', image['Os'], config.get('os'))
    I.require_equal('saved.architecture', image['Architecture'], config['architecture'])
    I.require_equal('saved.rootfs_type', 'layers', config['rootfs'].get('type'))
    I.require_equal('saved.DiffIDs', image['RootFS']['Layers'], config['rootfs']['diff_ids'])
    I.require_equal('saved.runtime', image['Config'], normalized_config(config['config'], config['os']))
    config_digest = 'sha256:' + members[name]['sha256']
    if expected_config_digest is not None:
        I.require_equal('saved.build_config_digest', expected_config_digest, config_digest)
    if expected_manifest_digest is not None:
        manifest_path = 'blobs/' + expected_manifest_digest.replace(':', '/')
        if manifest_path not in members or manifest_path not in objects:
            raise ValueError('Saved build manifest missing: expected ' + manifest_path)
        I.require_equal('saved.build_manifest_digest', expected_manifest_digest,
                        'sha256:' + members[manifest_path]['sha256'])
        I.require_equal('saved.build_manifest_config', config_digest,
                        objects[manifest_path]['config']['digest'])
    # Docker-compatible manifest is included by docker save, including the containerd store.
    manifests = objects.get('manifest.json')
    if not isinstance(manifests, list) or len(manifests) != 1:
        raise ValueError('Saved archive lacks a single-image Docker load manifest')
    manifest = manifests[0]
    I.require_equal('saved.config_path', name, manifest['Config'])
    if 'lifemate-k:k48.46-20261116-rc2' not in (manifest.get('RepoTags') or []):
        raise ValueError('Final tag missing from saved archive')
    if not manifest.get('Layers') or any(layer not in members for layer in manifest['Layers']):
        raise ValueError('Saved layer missing')
    I.require_equal('saved.layer_content_DiffIDs', config['rootfs']['diff_ids'],
                    [members[layer]['diff_id'] for layer in manifest['Layers']])
    for path, item in members.items():
        if path.startswith('blobs/sha256/'):
            I.require_equal('saved.blob.' + path, Path(path).name, item['sha256'])
    for obj in objects.values():
        if not isinstance(obj, dict):
            continue
        descriptors = list(obj.get('manifests', [])) + list(obj.get('layers', []))
        if isinstance(obj.get('config'), dict) and 'digest' in obj['config']:
            descriptors.append(obj['config'])
        for desc in descriptors:
            path = 'blobs/' + desc['digest'].replace(':', '/')
            if path not in members:
                raise ValueError('OCI descriptor missing from save: ' + path)
            I.require_equal('saved.descriptor_size', desc['size'], members[path]['bytes'])
    return {'image_config_digest': 'sha256:' + members[name]['sha256'],
            'rootfs_diff_ids': config['rootfs']['diff_ids'], 'members': len(members)}


def main():
    reference, run = sys.argv[1], Path(sys.argv[2])
    check_context()
    prerequisite('package')
    built = read(HERE / 'BUILD.json')
    image = built['image']
    I.require_equal('package.image', image['Id'], reference)
    artifacts = HERE / 'artifacts'
    artifacts.mkdir(exist_ok=True)
    archive = artifacts / 'lifemate-k-k48.46-20261116-rc2.tar.gz'
    partial = archive.with_name(archive.name + '.partial')
    if archive.exists() or partial.exists():
        raise FileExistsError('Export already exists; preserved for inspection, never overwritten')
    objects, members = {}, {}
    print('Exporting rc2 once; checking configuration, stored blobs and uncompressed layer identities while compressing.', flush=True)
    with (run / 'docker-save.stderr').open('w') as error:
        process = subprocess.Popen(['timeout', '--foreground', '--kill-after=10s', '1800s',
                                    'docker', 'image', 'save', 'lifemate-k:k48.46-20261116-rc2'],
                                   stdout=subprocess.PIPE, stderr=error)
        try:
            with partial.open('xb') as raw:
                writer = HashWriter(raw)
                with gzip.GzipFile(fileobj=writer, mode='wb', filename='', mtime=0, compresslevel=1) as compressed:
                    stream = SaveReader(process.stdout, compressed)
                    with tarfile.open(fileobj=stream, mode='r|') as tf:
                        for member in tf:
                            name = member.name.removeprefix('./')
                            if Path(name).is_absolute() or '..' in Path(name).parts or name in members:
                                raise ValueError('Invalid/duplicate archive path: ' + name)
                            if not member.isfile():
                                continue
                            digest = MemberDigest()
                            content = bytearray() if member.size < 4 * 1024**2 else None
                            with tf.extractfile(member) as data:
                                for block in iter(lambda: data.read(8 * 1024**2), b''):
                                    digest.update(block)
                                    if content is not None: content.extend(block)
                            raw_digest, diff_id = digest.finish()
                            members[name] = {'sha256': raw_digest, 'diff_id': diff_id, 'bytes': member.size}
                            if content is not None:
                                try: objects[name] = json.loads(content)
                                except (ValueError, UnicodeDecodeError): pass
                    while stream.read(8 * 1024**2):
                        pass
                raw.flush()
                import os
                os.fsync(raw.fileno())
            if process.wait(timeout=30) != 0:
                raise RuntimeError('docker save failed; partial preserved, never marked complete')
            metadata = verify_metadata(objects, members, image, built.get('image_config_digest'),
                                       built.get('oci_manifest_digest'))
        except BaseException:
            process.terminate()
            try: process.wait(timeout=15)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
            raise
        finally:
            process.stdout.close()
    partial.rename(archive)
    for algorithm in ('sha256', 'md5'):
        digest = getattr(writer, algorithm).hexdigest()
        (artifacts / (archive.name + '.' + algorithm)).write_text(digest + '  ' + archive.name + '\n')
    # Small supplementary source archive; models and native binaries are already in Docker.
    source_archive = artifacts / 'lifemate-k-source-20261116-rc2.tar.gz'
    with source_archive.open('xb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) as gz, tarfile.open(fileobj=gz, mode='w') as tf:
        for path in sorted((HERE / 'overlay').rglob('*')):
            if not path.is_file() or path.is_relative_to(HERE / 'overlay/native'):
                continue
            tf.add(path, arcname='source/' + str(path.relative_to(HERE / 'overlay')), recursive=False)
        for relative in ('Dockerfile', 'CONTEXT_SHA256.json', 'BUILD.json', 'evidence/preparation.json',
                         'evidence/identity-before/CONTEXT_SHA256.json', 'evidence/identity-correction.json'):
            tf.add(HERE / relative, arcname=relative, recursive=False)
    receipt = {'created_utc': datetime.now(timezone.utc).isoformat(), 'tag': 'lifemate-k:k48.46-20261116-rc2',
               'docker_store_image_id': reference, 'archive': archive.name, 'bytes': writer.size,
               'oci_manifest_digest': built.get('oci_manifest_digest'),
               'original_build_context_sha256': built.get('original_context_sha256'),
               'sha256': writer.sha256.hexdigest(), 'md5': writer.md5.hexdigest(), **metadata,
               'source_archive': source_archive.name, 'source_sha256': V.sha(source_archive),
               'build_sha256': V.sha(HERE / 'BUILD.json'), 'context_sha256': check_context(),
               'validation': {name: read(HERE / 'evidence' / (name + '-pass.json')) for name in ('gpu', 'smoke', 'pilot', 'notebook')},
               'full634_rc2_tested': False, 'a30_tested': False, 'complete_training_restoration': False,
               'redistribution_authorized': False, 'uploaded': False, 'submitted': False}
    write(artifacts / 'RELEASE.json', receipt)
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
