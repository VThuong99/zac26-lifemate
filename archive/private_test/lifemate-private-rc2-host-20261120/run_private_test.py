#!/usr/bin/env python3
"""Manual host-only smoke/full orchestration. Never rebuilds or patches RC2."""
import argparse
import csv
from datetime import datetime, timezone
import fcntl
import gzip
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import traceback
import wave
import zipfile

sys.dont_write_bytecode = True
from check_results import analyze, exact, parse, read, rows, sha, write

HERE = Path(__file__).resolve().parent
TAG = 'lifemate-k:k48.46-20261116-rc2'
MANIFEST = 'sha256:e212336277d5b37c5359599961c56b7f9331e4f63b3985902a2e7c588c114a8c'
CONFIG = 'sha256:00cf5905325e57fa68e7034d4e773bc81fcea8e347d41c3e3e100e47de486306'
ARCHIVE_SHA = 'e2aaa0a3c8f54e673f7700c443846a974be09257f3e28145ca9f0fb5076232f5'
ZIP_SHA = '66cf238f4d1a6c64fa48d92690ddd2f56aba6a621ef86c08eefa6d22df13d65c'
INPUT_SHA = '8af388eed3cd164e71b3273d70895565e7baae129dff561c161968c920a8b880'
CATALOG_SHA = '86da1001fd7642448fdb197455f3e1ad026d180920b09860f04fea18653c7585'
PINS = {
    'lifemate-final-20261116-rc2/BUILD.json': 'cc21548d068e44aa82d616d526285bd211af380f0f2d73fafb574776c25de981',
    'lifemate-final-20261116-rc2/artifacts/RELEASE.json': '73bdf17ae4f7da4115b4e586e7fcb46d0d3d79228a7413a07a801810ed72cc19',
    'lifemate-final-20261116-rc2/CONTEXT_SHA256.json': '4e0787eaf9c3f2d72f7c3e89e7f83c91fb1ac605626f2be2918bcd3e8d9a7b48',
    'lifemate-host-validation/image_identity.py': '818d3ab6ca897a99717b854024353c0eca1fc2e491813921efed3638ff2bd984',
    'lifemate-host-validation/validation.py': '12732ebe0121dcbc6dafad152ee93f2db7b3b886cdd2bd298a33e5c534ccf325',
    'lifemate/docs/organizer/Docker_Guide_ZAC2026_LifeMate.pdf': '9824a989dede28c1e6fe10a28033548a0a3325759ec5b2a5bd2d38ab71638364',
}
HELPERS = ('run_private_test.py', 'check_results.py', 'container/preflight.py', 'container/sitecustomize.py')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def command(argv, *, check=True, timeout=60):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f'Command failed ({result.returncode}): {shlex.join(argv)}\n{result.stdout}\n{result.stderr}')
    return result


def ensure_host():
    require(not Path('/.dockerenv').exists() and not Path('/run/.containerenv').exists() and not os.environ.get('container'),
            'HOST REQUIRED: refusing to execute Docker from a development container.')
    if shutil.which('systemd-detect-virt'):
        require(command(['systemd-detect-virt', '--container', '--quiet'], check=False).returncode != 0,
                'HOST REQUIRED: container virtualization detected.')
    require(os.geteuid() != 0, 'Run as the host user with Docker access, without sudo.')
    require(sys.version_info >= (3, 10), 'Host Python 3.10 or newer is required.')
    for tool in ('docker', 'nvidia-smi'):
        require(shutil.which(tool), 'Required host command unavailable: ' + tool)


def local_docker_endpoint():
    # Docker's explicit context environment takes precedence over DOCKER_HOST.
    context = os.environ.get('DOCKER_CONTEXT')
    if context:
        endpoint = command(['docker', 'context', 'inspect', context, '--format', '{{.Endpoints.docker.Host}}']).stdout.strip()
    elif os.environ.get('DOCKER_HOST'):
        endpoint = os.environ['DOCKER_HOST']
    else:
        endpoint = command(['docker', 'context', 'inspect', '--format', '{{.Endpoints.docker.Host}}']).stdout.strip()
    require(endpoint.startswith('unix://'), 'Only a local HOST Docker daemon is supported; remote bind mappings are not assumed')
    return endpoint


def lock(path):
    stream = path.open('a')
    try:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        stream.close()
        raise RuntimeError('Another workflow owns this lock; do not remove it: ' + str(path))
    return stream


def source_fingerprint():
    return {name: sha(HERE / name) for name in HELPERS}


def prepare_output_dir(requested=None):
    results = (Path(requested) if requested is not None else Path.home() / 'lifemate-private-rc2-results').expanduser().resolve()
    require(not any(x in str(results) for x in (',', '\n')), 'Unsupported comma/newline in --output-dir bind-mount path')
    results.mkdir(parents=True, exist_ok=True)
    require(os.access(results, os.W_OK | os.X_OK),
            'Host user cannot write --output-dir: ' + str(results) + '. Choose a writable directory; no sudo or workspace permission changes are needed.')
    return results


def load_verifier(workspace):
    for rel, expected in PINS.items():
        require(sha(workspace / rel) == expected, 'Pinned release/document/verifier mismatch: ' + rel)
    rc = workspace / 'lifemate-final-20261116-rc2'
    context = read(rc / 'CONTEXT_SHA256.json')
    # Verify original helper bytes before importing the existing RC2 verifier.
    for rel, expected in context.items():
        path = (rc / rel).resolve()
        require(path.is_relative_to(rc) and sha(path) == expected, 'RC2 context mismatch: ' + rel)
    sys.path.insert(0, str(rc / 'tools'))
    package = importlib.import_module('package')
    package.check_context()
    release = read(rc / 'artifacts/RELEASE.json')
    require(release['sha256'] == ARCHIVE_SHA and release['tag'] == TAG, 'Wrong release authority')
    historical = {}
    for stage, entry in release['validation'].items():
        path = rc / entry['report']
        require(sha(path) == entry['report_sha256'], 'Historical report changed: ' + stage)
        historical[stage] = read(path)
    for stage in ('pilot', 'notebook'):
        comparison = historical[stage]['comparison']
        require(comparison['expected'] == comparison['exact_cases'] == 10 and comparison['parity_pass'],
                'Recorded 10-case RC2 parity not established: ' + stage)
    return package, read(rc / 'BUILD.json'), release, historical


def verify_archive(archive, package, build, release):
    print('Verifying original 16.8 GB archive, compressed checksum, blob hashes and expanded layer digests...', flush=True)
    objects, members = {}, {}
    with archive.open('rb') as source:
        before = os.fstat(source.fileno())
        reader = package.I.HashingReader(source)
        with gzip.GzipFile(fileobj=reader, mode='rb') as expanded:
            with tarfile.open(fileobj=expanded, mode='r|', bufsize=1024**2) as tf:
                for member in tf:
                    path = PurePosixPath(member.name)
                    require(not path.is_absolute() and '..' not in path.parts,
                            'Unsafe archive path: ' + member.name)
                    if member.isdir():
                        continue
                    require(member.isfile() and member.name not in members,
                            'Unexpected archive member: ' + member.name)
                    digest = package.MemberDigest()
                    small, size = [], 0
                    with tf.extractfile(member) as stream:
                        for block in iter(lambda: stream.read(8 * 1024**2), b''):
                            size += len(block)
                            digest.update(block)
                            if member.size < 4 * 1024**2:
                                small.append(block)
                    raw, diff_id = digest.finish()
                    require(size == member.size, 'Truncated member: ' + member.name)
                    members[member.name] = {'sha256': raw, 'diff_id': diff_id, 'bytes': size}
                    if small:
                        try:
                            objects[member.name] = parse(b''.join(small))
                        except (ValueError, UnicodeError):
                            pass
                    print('Verified archive member:', member.name, flush=True)
            while expanded.read(8 * 1024**2):
                pass
        while reader.read(8 * 1024**2):
            pass
        after = os.fstat(source.fileno())
    stamp = lambda s: [s.st_size, s.st_mtime_ns, s.st_ctime_ns]
    require(stamp(before) == stamp(after), 'Archive changed during verification')
    require(reader.sha256.hexdigest() == ARCHIVE_SHA and reader.size == release['bytes'] and reader.md5.hexdigest() == release['md5'],
            'Original Docker archive checksum/size mismatch')
    verified = package.verify_metadata(objects, members, build['image'], CONFIG, MANIFEST)
    # Supported image stores may return the config ID or this authenticated target.
    descriptors = {}
    for name, obj in objects.items():
        if isinstance(obj, dict) and obj.get('schemaVersion') == 2 and obj.get('mediaType'):
            digest = 'sha256:' + members[name]['sha256']
            if digest == MANIFEST or name == 'index.json':
                if name == 'index.json':
                    require(len(obj.get('manifests', [])) == 1 and obj['manifests'][0]['digest'] == MANIFEST,
                            'Archive index must refer only to the RC2 manifest')
                descriptors[digest] = {'digest': digest, 'size': members[name]['bytes'], 'mediaType': obj['mediaType']}
    require(MANIFEST in descriptors, 'Authenticated OCI descriptor absent')
    return {'archive': str(archive), 'sha256': ARCHIVE_SHA, 'bytes': reader.size, 'gzip_crc_verified': True,
            'stat': stamp(after), 'metadata': verified, 'descriptors': descriptors, 'members': members}


def verify_loaded(inspected, package, build, archive):
    require(isinstance(inspected, list) and len(inspected) == 1, 'Expected exactly one loaded image')
    image = inspected[0]
    for field in ('Os', 'Architecture', 'RootFS'):
        require(exact(image.get(field), build['image'][field]), 'Loaded image mismatch: ' + field)
    require(not image.get('Variant') and not image.get('OsVersion') and not image.get('OsFeatures'), 'Unexpected image platform qualifiers')
    require(exact(package.normalized_config(image['Config'], image['Os']), build['image']['Config']),
            'Loaded runtime configuration differs from frozen RC2')
    target = image.get('Id')
    require(target == CONFIG or target in archive['descriptors'], 'Unknown image ID; matching tags/layers alone are insufficient')
    descriptor = image.get('Descriptor')
    if descriptor is not None or target != CONFIG:
        require(isinstance(descriptor, dict), 'Manifest-backed image must expose its descriptor')
        expected = archive['descriptors'].get(descriptor.get('digest'))
        require(expected and all(descriptor.get(k) == v for k, v in expected.items()), 'Loaded descriptor mismatch')
        require(target == CONFIG or descriptor['digest'] == target, 'Descriptor does not match image ID')
        if 'platform' in descriptor:
            require(descriptor['platform'] == {'architecture': 'amd64', 'os': 'linux'}, 'Wrong descriptor platform')
    return {'image_id': target, 'config_digest': CONFIG, 'manifest_digest': MANIFEST,
            'repo_tags': image.get('RepoTags'), 'repo_digests': image.get('RepoDigests'), 'descriptor': descriptor,
            'entrypoint': image['Config']['Entrypoint'], 'cmd': image['Config']['Cmd'], 'verified': True}


def get_loaded(package, build, archive, run, docker_root):
    for reference in (MANIFEST, CONFIG, TAG):
        result = command(['docker', 'image', 'inspect', reference], check=False)
        if result.returncode == 0:
            inspected = parse(result.stdout)
            identity = verify_loaded(inspected, package, build, archive)
            write(run / 'image-inspect.json', inspected)
            return identity
    # Do not retag or overwrite an existing candidate. This branch is only reached
    # when neither immutable ID nor submitted tag is loaded.
    require(archive_path_stat(archive['archive']) == archive['stat'], 'Archive changed before docker load')
    require(shutil.disk_usage(docker_root).free >= 64 * 1024**3,
            'Image load needs 64 GiB free on the Docker storage filesystem; do not prune existing artifacts')
    print('Exact image is absent; loading the verified original archive (no build).', flush=True)
    result = command(['docker', 'load', '-i', archive['archive']], timeout=1800)
    (run / 'docker-load.log').write_text(result.stdout + result.stderr)
    for reference in (MANIFEST, CONFIG, TAG):
        result = command(['docker', 'image', 'inspect', reference], check=False)
        if result.returncode == 0:
            inspected = parse(result.stdout)
            identity = verify_loaded(inspected, package, build, archive)
            write(run / 'image-inspect.json', inspected)
            return identity
    raise RuntimeError('Original archive loaded but its image cannot be inspected')


def archive_path_stat(path):
    s = Path(path).stat()
    return [s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def extract_dataset(zip_path, run):
    require(sha(zip_path) == ZIP_SHA, 'Official Private Test ZIP checksum differs from the audited release')
    data = run / 'dataset'
    data.mkdir()
    with zipfile.ZipFile(zip_path) as archive:
        seen = set()
        for member in archive.infolist():
            p = PurePosixPath(member.filename)
            mode = member.external_attr >> 16
            require(not p.is_absolute() and '..' not in p.parts and '\\' not in member.filename and member.filename not in seen,
                    'Unsafe/duplicate ZIP entry: ' + member.filename)
            require(not stat.S_ISLNK(mode) and stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR), 'Special ZIP entry')
            seen.add(member.filename)
        require(sum(i.file_size for i in archive.infolist()) < 2 * 1024**3, 'Unexpected extraction size')
        # Archive extraction is opaque. Hidden environment content is never parsed.
        # Reading each member to EOF validates its CRC; preserve every original byte.
        for member in archive.infolist():
            target = data.joinpath(*PurePosixPath(member.filename).parts)
            require(target.resolve().is_relative_to(data.resolve()), 'ZIP path escapes destination')
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as src, target.open('xb') as dst:
                    shutil.copyfileobj(src, dst, 1024**2)
    split = data / 'private_test'
    require(sha(split / 'private_test.jsonl') == INPUT_SHA, 'Private input checksum mismatch')
    require(sha(split / 'private_test_tools_catalog.json') == CATALOG_SHA, 'Private catalog checksum mismatch')
    cases = rows(split / 'private_test.jsonl')
    require(len(cases) == 625 and len({r['id'] for r in cases}) == 625, 'Expected 625 unique official requests')
    require((split / 'private_test_environment').is_dir(), 'Missing SDK environment directory')
    manifest = {}
    for path in sorted((split / 'zaic_tools').rglob('*.py')):
        manifest[str(path.relative_to(split))] = sha(path)
    for name in ('private_test.jsonl', 'private_test_tools_catalog.json'):
        manifest[name] = sha(split / name)
    audio_seen = set()
    for row in cases:
        require(set(row) == {'id', 'audio', 'context', 'history'}, 'Unexpected input fields')
        require(isinstance(row['id'], str) and re.fullmatch('private_[0-9]{4}', row['id']), 'Invalid request ID')
        for turn in row['history']:
            require(not ({'label', 'audio_text', 'final_state', 'state_hash'} & set(turn)), 'Reference field present in input')
        for rel in [row['audio']] + [t['audio'] for t in row['history'] if 'audio' in t]:
            path = (split / rel).resolve()
            require(path.is_relative_to(split / 'audio') and path.is_file(), 'Invalid/missing audio: ' + rel)
            if rel in audio_seen:
                continue
            audio_seen.add(rel)
            with wave.open(str(path), 'rb') as wav:
                require((wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) == (1, 2, 16000, 'NONE'),
                        'Unexpected WAV format: ' + rel)
            manifest[rel] = sha(path)
    require(len(audio_seen) == 3647, 'Unexpected number of audio files')
    write(run / 'input-manifest.json', manifest)
    write(run / 'dataset.json', {'zip': str(zip_path), 'zip_sha256': ZIP_SHA, 'crc_integrity': 'PASS', 'requests': 625,
                                'audio_files': len(audio_seen), 'split': str(split), 'ids': [r['id'] for r in cases]})
    return split, cases, manifest


def check_gpu(selector):
    require(re.fullmatch(r'[0-9]+|GPU-[a-fA-F0-9-]+', selector), 'GPU must be one index or UUID')
    result = command(['nvidia-smi', '-i', selector, '--query-gpu=uuid,name,driver_version,memory.total,memory.used,memory.free,utilization.gpu', '--format=csv,noheader,nounits'])
    entries = list(csv.reader(result.stdout.strip().splitlines()))
    require(len(entries) == 1, 'Select exactly one GPU')
    uuid, name, driver, total, used, free, util = [s.strip() for s in entries[0]]
    require('RTX 5090' in name, 'This host workflow requires the requested RTX 5090')
    require(int(used) <= 1024 and int(free) >= 12000 and int(util) <= 5, 'GPU busy or insufficient free VRAM; wait for its owner')
    processes = command(['nvidia-smi', '-i', uuid, '--query-compute-apps=pid,process_name,used_gpu_memory', '--format=csv,noheader']).stdout
    require(not processes.strip(), 'Selected GPU has active compute processes; do not stop them')
    return {'uuid': uuid, 'name': name, 'driver': driver, 'memory_total_mib': int(total), 'memory_free_mib': int(free), 'raw': result.stdout}


def verify_container(inspected, identity, split, stage, harness, cmd, gpu_uuid, uid, *, cuda_compat=False):
    require(len(inspected) == 1, 'Expected one container')
    c = inspected[0]
    require(c['Image'] in (CONFIG, identity['image_id']) and c['Config']['Image'] == identity['image_id'], 'Container image identity mismatch')
    require(c['Config']['Entrypoint'] == ['/opt/nvidia/nvidia_entrypoint.sh'] and c['Config']['Cmd'] == cmd and c['Config']['WorkingDir'] == '/code',
            'Container changed original entrypoint/command/working directory')
    require(c['Config']['User'] == uid, 'Wrong container user')
    host = c['HostConfig']
    for key, expected in {'NetworkMode': 'none', 'NanoCpus': 16_000_000_000, 'Memory': 48 * 1024**3,
                          'MemorySwap': 48 * 1024**3, 'ShmSize': 2 * 1024**3, 'PidsLimit': 1024, 'Privileged': False}.items():
        require(host.get(key) == expected, 'Container resource/security mismatch: ' + key)
    require('ALL' in host.get('CapDrop', []) and any(x in ('no-new-privileges', 'no-new-privileges:true') for x in host.get('SecurityOpt', [])), 'Missing container confinement')
    require(not host.get('ExtraHosts') and not host.get('PortBindings'), 'Unexpected hostname/network overrides')
    devices = host.get('DeviceRequests') or []
    require(len(devices) == 1 and devices[0].get('DeviceIDs') == [gpu_uuid] and ['gpu'] in devices[0].get('Capabilities', []), 'GPU request mismatch')
    mounts = {m['Destination']: m for m in c['Mounts']}
    expected = {'/data/private_test': (split, False), '/result': (stage, True), '/validation': (harness, False)}
    require(set(mounts) == set(expected), 'Unexpected container mount set')
    for dest, (source, rw) in expected.items():
        m = mounts[dest]
        require(m['Type'] == 'bind' and Path(m['Source']).resolve() == source.resolve() and m['RW'] is rw, 'Mount mapping/access mismatch: ' + dest)
    env = dict(pair.split('=', 1) for pair in c['Config']['Env'])
    require(env.get('NVIDIA_DISABLE_REQUIRE') == ('true' if cuda_compat else None),
            'Container CUDA compatibility override does not match --cuda-compat')
    for key, value in {'PYTHONHASHSEED': '20261030', 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
                       'CUBLAS_WORKSPACE_CONFIG': ':4096:8', 'PYTHONDONTWRITEBYTECODE': '1',
                       'PYTHONPATH': '/validation:/opt/k-python/main:/opt/k-python/sherpa:/opt/k-python/jupyter'}.items():
        require(env.get(key) == value, 'Unexpected runtime environment: ' + key)
    require('LIFEMATE_PREFLIGHT_FILE' not in env and 'LIFEMATE_TEST_LIMIT' not in env, 'Unexpected inference override')


def telemetry(stop, stage, cid, gpu):
    with (stage / 'resources.jsonl').open('x') as stream:
        while not stop.is_set():
            entry = {'utc': datetime.now(timezone.utc).isoformat()}
            for key, argv in [('gpu', ['nvidia-smi', '-i', gpu, '--query-gpu=name,memory.used,utilization.gpu', '--format=csv,noheader,nounits']),
                              ('docker', ['docker', 'stats', '--no-stream', '--format', '{{json .}}', cid])]:
                try:
                    result = command(argv, check=False, timeout=10)
                    entry[key] = {'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
                except Exception as error:
                    entry[key] = {'error': str(error)}
            stream.write(json.dumps(entry) + '\n')
            stream.flush()
            stop.wait(5)


def run_container(run, name, cmd, deadline, identity, split, harness, gpu, *, cuda_compat=False):
    stage = run / name
    stage.mkdir()
    for folder in ('home', 'cache'):
        (stage / folder).mkdir(mode=0o700)
    uid = f'{os.getuid()}:{os.getgid()}'
    container_name = 'lifemate-private-rc2-' + run.name.lower() + '-' + name
    argv = ['docker', 'create', '--pull=never', '--name', container_name, '--label', 'lifemate.private-rc2=' + run.name,
            '--network', 'none', '--gpus', 'device=' + gpu['uuid'], '--cpus', '16', '--memory', '48g', '--memory-swap', '48g',
            '--shm-size', '2g', '--pids-limit', '1024', '--user', uid, '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
            '--mount', f'type=bind,src={split},dst=/data/private_test,readonly', '--mount', f'type=bind,src={stage},dst=/result',
            '--mount', f'type=bind,src={harness},dst=/validation,readonly', '--env', 'HOME=/result/home', '--env', 'XDG_CACHE_HOME=/result/cache',
            '--env', 'PYTHONPATH=/validation:/opt/k-python/main:/opt/k-python/sherpa:/opt/k-python/jupyter']
    if cuda_compat:
        argv += ['--env', 'NVIDIA_DISABLE_REQUIRE=true']
    argv += [identity['image_id'], *cmd]
    write(stage / 'create-command.json', argv)
    (stage / 'create-command.sh').write_text(shlex.join(argv) + '\n')
    cid = command(argv).stdout.strip()
    require(re.fullmatch('[a-f0-9]{64}', cid), 'Invalid created container ID')
    (stage / 'container-id.txt').write_text(cid + '\n')
    attached = None
    monitor = None
    stop = threading.Event()
    started = time.monotonic()
    rc, timed_out, interrupted = None, False, False
    try:
        created = parse(command(['docker', 'inspect', cid]).stdout)
        write(stage / 'container-created.json', created)
        verify_container(created, identity, split, stage, harness, cmd, gpu['uuid'], uid, cuda_compat=cuda_compat)
        print(f'{name}: starting {cid[:12]}; logs: {stage}/container.log', flush=True)
        with (stage / 'container.log').open('x') as log:
            attached = subprocess.Popen(['docker', 'start', '--attach', cid], stdout=log, stderr=subprocess.STDOUT)
            monitor = threading.Thread(target=telemetry, args=(stop, stage, cid, gpu['uuid']), daemon=True)
            monitor.start()
            last = 0
            while attached.poll() is None:
                elapsed = time.monotonic() - started
                if elapsed >= deadline:
                    timed_out = True
                    break
                if elapsed - last >= 30:
                    receipts = list((stage / 'submission.diagnostics').glob('*.result.json'))
                    print(f'{name}: {len(receipts)} request receipts; {elapsed:.0f}s elapsed', flush=True)
                    last = elapsed
                time.sleep(1)
            if not timed_out:
                rc = attached.wait()
    except KeyboardInterrupt:
        interrupted = True
        raise
    finally:
        stop.set()
        # Operate only on this invocation's saved container ID; never prune/remove.
        current = parse(command(['docker', 'inspect', cid]).stdout)
        if current[0]['State']['Running']:
            command(['docker', 'stop', '--time', '20', cid], timeout=45)
            current = parse(command(['docker', 'inspect', cid]).stdout)
            if current[0]['State']['Running']:
                command(['docker', 'kill', cid], timeout=20)
        if attached is not None:
            try:
                rc = attached.wait(timeout=15)
            except subprocess.TimeoutExpired:
                attached.terminate()
                rc = attached.wait(timeout=10)
        if monitor is not None:
            monitor.join(timeout=25)
        final = parse(command(['docker', 'inspect', cid]).stdout)
        write(stage / 'container-final.json', final)
        exit_report = {'attach_exit_code': rc, 'outer_timeout': timed_out, 'interrupted': interrupted,
                       'wall_seconds': time.monotonic() - started, 'container_id': cid, 'container_retained': True}
        write(stage / 'exit.json', exit_report)
    verify_container(final, identity, split, stage, harness, cmd, gpu['uuid'], uid, cuda_compat=cuda_compat)
    state = final[0]['State']
    ok = rc == 0 and not timed_out and not state['Running'] and state['ExitCode'] == 0 and not state['OOMKilled'] and not state.get('Error')
    return stage, ok, exit_report


def validate_smoke_reference(path, workspace, fingerprint, *, cuda_compat=False):
    require(path.is_dir(), '--smoke-run must be the prior smoke run directory')
    report = read(path / 'REPORT.json')
    require(report.get('mode') == 'smoke' and report.get('smoke_pass') is True, 'Prior smoke did not pass')
    require(report.get('workspace') == str(workspace), 'Smoke was run against a different host workspace')
    require(report.get('workflow_sha256') == fingerprint, 'Workflow changed since smoke; perform a fresh smoke test')
    require(report.get('cuda_compat') is cuda_compat,
            'CUDA compatibility mode changed since smoke; use the same --cuda-compat setting or perform a fresh smoke test')
    require(report.get('archive_sha256') == ARCHIVE_SHA and report.get('zip_sha256') == ZIP_SHA, 'Smoke used different artifacts')
    for rel, digest in report['evidence_sha256'].items():
        candidate = (path / rel).resolve()
        require(candidate.is_relative_to(path.resolve()) and sha(candidate) == digest, 'Prior smoke evidence changed: ' + rel)
    return report


def publish(source, destination, expected_sha):
    require(not destination.exists(), 'Final output already exists; refusing to overwrite: ' + str(destination))
    require(sha(source) == expected_sha, 'Prediction changed after validation')
    # Same filesystem, atomic no-clobber publication. Retain the staged original.
    os.link(source, destination)
    require(sha(destination) == expected_sha, 'Published file checksum mismatch')
    fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('smoke', 'full'))
    parser.add_argument('--workspace', type=Path, default=HERE.parent, help='Actual HOST workspace root; never use the development-container path by assumption')
    parser.add_argument('--output-dir', type=Path, help='Writable HOST directory for all run artifacts, locks and final JSONL (default: ~/lifemate-private-rc2-results)')
    parser.add_argument('--gpu', default='0', help='One idle RTX 5090 index or UUID')
    parser.add_argument('--cuda-compat', action='store_true', help='Opt in to NVIDIA_DISABLE_REQUIRE=true for all containers; local compatibility override, not organizer-exact execution. GPU/SDK preflight remains required.')
    parser.add_argument('--smoke-run', type=Path, help='Required for full; prior successful smoke directory, reviewed by the user')
    args = parser.parse_args(argv)
    ensure_host()  # Before any Docker command, write, model import, or archive extraction.
    workspace = args.workspace.expanduser().resolve(strict=True)
    require(not any(x in str(workspace) for x in (',', '\n')), 'Unsupported comma/newline in bind-mount root')
    require((workspace / 'lifemate-final-20261116-rc2').is_dir() and (workspace / 'lifemate/docs/organizer/private_test.zip').is_file(),
            'Host path mapping is wrong: RC2 workspace and official Private Test ZIP must exist under --workspace')
    fingerprint = source_fingerprint()
    if args.mode == 'full':
        require(args.smoke_run is not None, 'Run smoke first, review its output, then supply --smoke-run')
        smoke_report = validate_smoke_reference(args.smoke_run.expanduser().resolve(), workspace, fingerprint, cuda_compat=args.cuda_compat)
    else:
        require(args.smoke_run is None, '--smoke-run is only valid for full')
        smoke_report = None
    results = prepare_output_dir(args.output_dir)
    destination = results / 'private_test_k48_46_rc2.jsonl'
    require(not destination.exists(), 'Requested final output already exists; no results will be overwritten')
    locks = [lock(results / '.private_test_k48_46_rc2.host.lock')]
    run = Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + args.mode + '-', dir=results))
    print('HOST WORKSPACE:', workspace, '\nHOST OUTPUT DIRECTORY:', results, '\nEVIDENCE:', run, flush=True)
    print('The script will stop after this stage. Full inference is never automatic after smoke.', flush=True)
    compatibility = {'cuda_compat': args.cuda_compat,
                     'docker_env_overrides': {'NVIDIA_DISABLE_REQUIRE': 'true'} if args.cuda_compat else {},
                     'organizer_exact_execution': False,
                     'execution_environment': 'local_cuda_compatibility_override' if args.cuda_compat else 'local_default_runtime_requirements'}
    compatibility_note = ('CUDA COMPAT ENABLED: NVIDIA_DISABLE_REQUIRE=true; local compatibility override, not organizer-exact execution. GPU computation, SDK and image-assets preflight remain mandatory.'
                          if args.cuda_compat else 'CUDA COMPAT DISABLED: NVIDIA runtime requirements unchanged; organizer-exact execution is not established.')
    print(compatibility_note, flush=True)
    report = {'mode': args.mode, 'status': 'BLOCKED / INVALID', 'workspace': str(workspace), 'output_dir': str(results), 'run': str(run),
              'workflow_sha256': fingerprint, 'archive_sha256': ARCHIVE_SHA, 'zip_sha256': ZIP_SHA,
              'requested_output': str(destination), 'smoke_pass': False, 'output_created': False, 'semantic_score': None,
              **compatibility}
    try:
        report['docker_endpoint'] = local_docker_endpoint()
        docker_info = parse(command(['docker', 'info', '--format', '{{json .}}']).stdout)
        require(docker_info.get('OSType') == 'linux', 'Linux Docker host required')
        require(docker_info.get('NCPU', 0) >= 16 and docker_info.get('MemTotal', 0) >= 56 * 1024**3, 'Host must provide 16 CPUs and approximately 64 GB RAM')
        write(run / 'docker-info.json', docker_info)
        (run / 'docker-version.txt').write_text(command(['docker', 'version']).stdout)
        (run / 'nvidia-smi.txt').write_text(command(['nvidia-smi']).stdout)
        require(shutil.disk_usage(results).free >= 5 * 1024**3, 'Need at least 5 GiB free in --output-dir for extraction and diagnostics')
        package, build, release, historical = load_verifier(workspace)
        write(run / 'historical-validation.json', historical)
        archive_path = workspace / 'lifemate-final-20261116-rc2/artifacts' / release['archive']
        archive = verify_archive(archive_path, package, build, release)
        write(run / 'archive-identity.json', archive)
        identity = get_loaded(package, build, archive, run, docker_info['DockerRootDir'])
        write(run / 'image-identity.json', identity)
        report['image_identity'] = identity
        gpu = check_gpu(args.gpu)
        locks.append(lock(results / ('.validation-' + gpu['uuid'] + '.lock')))
        gpu = check_gpu(gpu['uuid'])
        if smoke_report:
            require(smoke_report['gpu']['uuid'] == gpu['uuid'] and smoke_report['gpu']['driver'] == gpu['driver'], 'GPU or driver changed since smoke; run a new smoke first')
        report['gpu'] = gpu
        report['environment_notes'] = [
            compatibility_note,
            'One selected RTX 5090, 16 CPU quota (not physical core pinning), 48 GiB container RAM versus the guide host budget of 64 GB.',
            'Original CUDA 13.2 image. Docker guide specifies driver 595.58.03; actual driver is ' + gpu['driver'] + '.',
            'The newer Docker guide specifies RTX 5090; older local rules mention A30. This workflow does not establish A30 compatibility.',
            'Mounted read-only observer is the prior RC2 SDK audit hook with its root changed to private_test; its I/O overhead remains in measured request time.',
            'Fresh model processes; filesystem caches are not flushed. Historical CLI/notebook 10-case parity is verified, not rerun on Public Test.',
        ]
        write(run / 'gpu-before.json', gpu)
        split, all_cases, input_manifest = extract_dataset(workspace / 'lifemate/docs/organizer/private_test.zip', run)
        cases = all_cases[:3] if args.mode == 'smoke' else all_cases
        harness = run / 'harness'
        harness.mkdir()
        for name in ('preflight.py', 'sitecustomize.py'):
            with (HERE / 'container' / name).open('rb') as src, (harness / name).open('xb') as dst:
                shutil.copyfileobj(src, dst)
        write(run / 'plan.json', {'mode': args.mode, 'expected_ids': [r['id'] for r in cases], 'host_input': str(split),
                                  **compatibility,
                                  'host_output_dir': str(results), 'host_inference_output': str(run / 'inference'),
                                  'container_output': '/result',
                                  'container_input': '/data/private_test', 'uid': os.getuid(), 'gid': os.getgid(),
                                  'original_entrypoint': identity['entrypoint'], 'workflow_sha256': fingerprint,
                                  'smoke_run': str(args.smoke_run) if args.smoke_run else None})
        preflight, ok, _ = run_container(run, 'preflight', ['python3', '/validation/preflight.py'], 1800, identity, split, harness, gpu,
                                         cuda_compat=args.cuda_compat)
        require(ok and read(preflight / 'preflight.json')['success'], 'GPU/SDK/image-assets preflight failed; inspect preflight logs')
        check_gpu(gpu['uuid'])
        cmd = ['/bin/bash', '/code/predict.sh', '--data-root', '/data', '--split', 'private_test', '--output', '/result/submission.jsonl']
        if args.mode == 'smoke':
            cmd += ['--limit', '3']
        stage, ok, elapsed = run_container(run, 'inference', cmd, 600 if args.mode == 'smoke' else 625 * 30 + 600,
                                            identity, split, harness, gpu, cuda_compat=args.cuda_compat)
        checked = analyze(stage, cases, split, input_manifest)
        if not ok:
            checked['issues'].append({'kind': 'container_execution_failed', **elapsed})
        # Confirm input bytes outside hidden environment state remained unchanged.
        changed = [rel for rel, digest in input_manifest.items() if sha(split / rel) != digest]
        if changed:
            checked['issues'].append({'kind': 'input_changed', 'paths': changed})
        require(source_fingerprint() == fingerprint, 'Host helpers changed during run')
        checked['structural_and_provenance_pass'] = not checked['issues']
        checked['status'] = 'BLOCKED / INVALID' if checked['issues'] else 'GENERATED WITH WARNINGS' if checked['warnings'] else 'READY FOR SUBMISSION'
        write(run / 'validation.json', checked)
        report['validation'] = checked
        report['container_wall_seconds'] = elapsed['wall_seconds']
        report['status'] = checked['status']
        require(checked['structural_and_provenance_pass'], 'Structural/protocol/runtime validation failed; output retained only in diagnostics')
        if args.mode == 'smoke':
            require(not checked['warnings'], 'Smoke produced warnings; review diagnostics before deciding how to proceed')
            require(checked['tool_calls'] > 0, 'Smoke produced no tool calls; actual SDK tool execution is not yet established')
            report['smoke_pass'] = True
            report['status'] = 'SMOKE PASSED — awaiting manual review; full run not started'
        else:
            publish(stage / 'submission.jsonl', destination, checked['jsonl_sha256'])
            report['output_created'] = True
            report['output_sha256'] = checked['jsonl_sha256']
    except BaseException as error:
        report['status'] = 'BLOCKED / INVALID'
        report['error'] = repr(error)
        (run / 'error.txt').write_text(traceback.format_exc())
    finally:
        # Seal smoke evidence for the explicit later full command. Never hash/read
        # hidden state here; archive integrity and read-only mounts cover it.
        evidence = []
        for entry in run.iterdir():
            if entry.name == 'dataset' or entry.name == 'REPORT.json':
                continue
            evidence.extend([entry] if entry.is_file() else [p for p in entry.rglob('*') if p.is_file()])
        report['evidence_sha256'] = {str(p.relative_to(run)): sha(p) for p in evidence}
        write(run / 'REPORT.json', report)
        for stream in reversed(locks):
            stream.close()
    print('\nSTATUS:', report['status'], flush=True)
    print(compatibility_note, flush=True)
    print('REPORT:', run / 'REPORT.json', flush=True)
    if report.get('error'):
        print('ERROR:', report['error'], flush=True)
    if report.get('validation'):
        checked = report['validation']
        print(json.dumps({k: checked[k] for k in ('expected', 'processed', 'finished', 'step_limit_requests', 'timeouts', 'failed_receipts', 'timing', 'warnings', 'jsonl_sha256')}, indent=2), flush=True)
    if args.mode == 'smoke' and report['smoke_pass']:
        print('STOP HERE. Paste this terminal summary and REPORT.json for review. Full inference has NOT run.', flush=True)
        print('SMOKE_RUN=' + shlex.quote(str(run)), flush=True)
    if report.get('output_created'):
        print('FINAL JSONL:', destination, '\nSHA256:', report['output_sha256'], flush=True)
    return 0 if report['smoke_pass'] or report['output_created'] else 2


def interrupt(signum, frame):
    raise KeyboardInterrupt('Signal ' + str(signum))


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, interrupt)
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, ValueError) as error:
        print('BLOCKED:', error, file=sys.stderr)
        raise SystemExit(2)
