"""Host preparation and evidence checks. No model or environment imports."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parent
VALIDATOR = ROOT / 'lifemate-host-validation'
sys.path.insert(0, str(VALIDATOR))
import validation as V
import image_identity as I

ORIGINAL_CONTEXT_SHA256 = 'e6f9f2872fb0d4507f165d51483c4909cd2eb5184ea2212298c59a7bcc9e9b25'
EMPTY_TAR_DIFF_ID = 'sha256:' + hashlib.sha256(bytes(1024)).hexdigest()


def read(path):
    return V.read_json(Path(path))


def write(path, value):
    V.write_json(Path(path), value)


def check_context():
    manifest = read(HERE / 'CONTEXT_SHA256.json')
    actual = {str(p.relative_to(HERE)) for group in ('overlay', 'tools', 'container')
              for p in (HERE / group).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    actual |= {'Dockerfile', 'host.sh', '.dockerignore', 'evidence/base-image-identity.json',
               'evidence/base-image-inspect.json', 'evidence/base-receipt-sha256.json', 'evidence/preparation.json',
               'evidence/identity-correction.json', 'evidence/lock-correction.json'}
    actual |= {str(p.relative_to(HERE)) for p in (HERE / 'evidence/identity-before').iterdir() if p.is_file()}
    actual |= {str(p.relative_to(HERE)) for p in (HERE / 'evidence/lock-before').iterdir() if p.is_file()}
    I.require_equal('candidate.file_set', sorted(manifest), sorted(actual))
    for name, digest in manifest.items():
        I.require_equal('candidate.' + name, digest, V.sha(HERE / name))
    return V.sha(HERE / 'CONTEXT_SHA256.json')


def base(inspect_path):
    saved = HERE / 'evidence/base-image-identity.json'
    expected = read(HERE / 'evidence/base-receipt-sha256.json')
    for name, digest in expected.items():
        I.require_equal(name, digest, V.sha(HERE / 'evidence' / name))
    receipt = I.read_identity_record(saved, HERE / 'evidence/base-image-inspect.json')
    identity = I.make_identity_record(inspect_path, receipt['sealed_archive_verification'])
    return identity['verified_docker_image_reference']


def normalized_config(config, os_name):
    # Validate all fields/types first. ArgsEscaped only controls Windows command-line
    # escaping (OCI image-spec config.md); retain every other existing strict check.
    normalized = I.normalized_config(config)
    if os_name == 'linux':
        normalized['ArgsEscaped'] = False
    return normalized


def fingerprint(image):
    return {'Id': image['Id'], 'Os': image['Os'], 'Architecture': image['Architecture'],
            'RootFS': image['RootFS'], 'Config': normalized_config(image['Config'], image['Os'])}


def validate_build_metadata(actual):
    I.require_equal('candidate.OS', 'linux', actual['Os'])
    I.require_equal('candidate.architecture', 'amd64', actual['Architecture'])
    previous = read(HERE / 'evidence/base-image-inspect.json')[0]
    expected_config = dict(previous['Config'])
    expected_config['Labels'] = dict(expected_config.get('Labels') or {})
    expected_config['Labels'].update({
        'org.opencontainers.image.version': 'k48.46-20261116-rc2',
        'org.opencontainers.image.description': 'Final candidate; mounted SDK only; A30 runtime and training/transfer rights unverified'})
    I.require_equal('candidate.config', normalized_config(expected_config, 'linux'),
                    normalized_config(actual['Config'], actual['Os']))
    I.require_equal('candidate.rootfs_type', 'layers', actual['RootFS']['Type'])
    layers = actual['RootFS']['Layers']
    if len(layers) not in (1, 2):
        raise ValueError(f'candidate.layers: expected one flattened layer, optionally one empty tar; actual: {layers!r}')
    if len(layers) == 2:
        I.require_equal('candidate.empty_tail_DiffID', EMPTY_TAR_DIFF_ID, layers[1])
    if not all(re.fullmatch(r'sha256:[a-f0-9]{64}', layer) for layer in layers):
        raise ValueError(f'candidate.layers: expected SHA-256 DiffIDs; actual: {layers!r}')


def record_build(run, provenance=None):
    actual = read(run / 'image-inspect.json')[0]
    validate_build_metadata(actual)
    write(HERE / 'BUILD.json', {'image': fingerprint(actual), 'image_inspect_sha256': V.sha(run / 'image-inspect.json'),
          'context_sha256': check_context(), 'base_receipt_sha256': V.sha(HERE / 'evidence/base-image-identity.json'),
          'build_run': str(run.relative_to(HERE)), 'runtime_tested': False, 'transfer_authorized': False,
          **(provenance or {})})
    print(actual['Id'])


def original_build_provenance():
    """Authenticate saved build evidence and prove all image inputs are unchanged."""
    check_context()
    original_path = HERE / 'evidence/identity-before/CONTEXT_SHA256.json'
    I.require_equal('resume.original_context', ORIGINAL_CONTEXT_SHA256, V.sha(original_path))
    original = read(original_path)
    allowed_host_changes = {'host.sh', 'tools/candidate.py', 'tools/package.py'}
    for name, digest in original.items():
        if name not in allowed_host_changes:
            I.require_equal('resume.unchanged.' + name, digest, V.sha(HERE / name))
        else:
            I.require_equal('resume.original_tool.' + name, digest,
                            V.sha(HERE / 'evidence/identity-before' / Path(name).name))
    correction = read(HERE / 'evidence/identity-correction.json')
    I.require_equal('resume.receipt_context', ORIGINAL_CONTEXT_SHA256, correction['original_context_sha256'])
    for name, digest in correction['original_evidence_sha256'].items():
        I.require_equal('resume.evidence.' + name, digest, V.sha(HERE / name))
    saved = HERE / correction['original_build_run']
    I.require_equal('resume.base_unchanged', base(saved / 'base-inspect.json'), base(saved / 'base-after.json'))
    log = (saved / 'build.log').read_text()
    checks = [json.loads(row) for row in re.findall(r'(\{"checked":.*\})', log)]
    I.require_equal('resume.release_file_checks', [{'checked': 42199, 'mismatches': []}], checks)
    for kind, key in (('config', 'image_config_digest'), ('manifest', 'oci_manifest_digest')):
        I.require_equal('resume.exported_' + kind, [correction[key]],
                        re.findall(r'exporting ' + kind + r' (sha256:[a-f0-9]{64}) done', log))
    image = read(saved / 'image-inspect.json')[0]
    I.require_equal('resume.exported_image', correction['oci_manifest_digest'], image['Id'])
    I.require_equal('resume.saved_rootfs', correction['rootfs'], image['RootFS'])
    validate_build_metadata(image)
    return correction, image


def resume_build(run):
    correction, original_image = original_build_provenance()
    current = read(run / 'image-inspect.json')[0]
    I.require_equal('resume.built_image', fingerprint(original_image), fingerprint(current))
    # Resuming this exact stored image also pins raw metadata, including ArgsEscaped.
    I.require_equal('resume.raw_config', original_image['Config'], current['Config'])
    if (HERE / 'BUILD.json').exists():
        check_image(run / 'image-inspect.json')
        return
    record_build(run, {'original_build_run': correction['original_build_run'],
                      'original_context_sha256': ORIGINAL_CONTEXT_SHA256,
                      'identity_correction_sha256': V.sha(HERE / 'evidence/identity-correction.json'),
                      'image_config_digest': correction['image_config_digest'],
                      'oci_manifest_digest': correction['oci_manifest_digest'],
                      'raw_args_escaped': current['Config'].get('ArgsEscaped'),
                      'resumed_without_rebuild': True})


def check_image(path):
    built = read(HERE / 'BUILD.json')
    check_build_context(built)
    actual = read(path)[0]
    I.require_equal('built_image_identity', built['image'], fingerprint(actual))
    print(actual['Id'])


def check_build_context(built):
    """Allow only the documented host lock fix; preserve BUILD and past receipts."""
    current = check_context()
    if built['context_sha256'] == current:
        return current
    correction = read(HERE / 'evidence/lock-correction.json')
    previous_path = HERE / 'evidence/lock-before/CONTEXT_SHA256.json'
    I.require_equal('lock_fix.previous_context', built['context_sha256'], V.sha(previous_path))
    I.require_equal('lock_fix.receipt_context', built['context_sha256'], correction['previous_context_sha256'])
    I.require_equal('lock_fix.preserved_build', correction['preserved_build_sha256'], V.sha(HERE / 'BUILD.json'))
    allowed_changes = {'host.sh', 'tools/candidate.py'}
    I.require_equal('lock_fix.allowed_changes', sorted(allowed_changes), sorted(correction['changed_host_files']))
    previous = read(previous_path)
    added = {'evidence/lock-correction.json', 'evidence/lock-before/CONTEXT_SHA256.json',
             'evidence/lock-before/host.sh', 'evidence/lock-before/candidate.py'}
    I.require_equal('lock_fix.file_set', sorted(set(previous) | added), sorted(read(HERE / 'CONTEXT_SHA256.json')))
    for name, digest in previous.items():
        path = HERE / name if name not in allowed_changes else HERE / 'evidence/lock-before' / Path(name).name
        I.require_equal('lock_fix.unchanged.' + name, digest, V.sha(path))
    for name, digest in correction['preserved_evidence_sha256'].items():
        I.require_equal('lock_fix.preserved_evidence.' + name, digest, V.sha(HERE / name))
    return current


def inputs(run, stage):
    split = ROOT / 'lifemate/public_test'
    manifest, refs = V.references()
    for name, digest in manifest['input_files'].items():
        I.require_equal('input.' + name, digest, V.sha(split / name))
    cases = V.read_rows(split / 'public_test.jsonl')
    I.require_equal('input.ids', [r['id'] for r in refs], [r['id'] for r in cases])
    count = 1 if stage in ('gpu', 'smoke') else 10
    audio = read(VALIDATOR / 'reference/audio_sha256.json')
    for case in cases[:count]:
        I.require_equal('input.fields', ['audio', 'context', 'history', 'id'], sorted(case))
        for name in V.audio_paths(case):
            path = split / name
            if not path.resolve().is_relative_to((split / 'audio').resolve()):
                raise ValueError('Audio path escapes split: ' + name)
            I.require_equal('audio.' + name, audio[name], V.sha(path))
    write(run / 'plan.json', {'stage': stage, 'count': count, 'expected_ids': [r['id'] for r in refs[:count]],
          'build_sha256': V.sha(HERE / 'BUILD.json'), 'context_sha256': check_context(),
          'reference_manifest_sha256': V.sha(VALIDATOR / 'reference/manifest.json')})


def completed(stage):
    if stage not in ('gpu', 'smoke', 'pilot', 'notebook'):
        raise ValueError('Unsupported reusable stage: ' + stage)
    marker_path = HERE / 'evidence' / (stage + '-pass.json')
    if not marker_path.exists():
        return False
    check_build_context(read(HERE / 'BUILD.json'))
    marker = read(marker_path)
    I.require_equal('prerequisite.build', V.sha(HERE / 'BUILD.json'), marker['build_sha256'])
    report_path = HERE / marker['report']
    I.require_equal('prerequisite.report_hash', marker['report_sha256'], V.sha(report_path))
    report = read(report_path)
    I.require_equal('prerequisite.stage', stage, report['stage'])
    I.require_equal('prerequisite.pass', True, report['selected_stage_pass'])
    return True


def prerequisite(stage):
    required = {'gpu': None, 'smoke': 'gpu', 'pilot': 'smoke', 'notebook': 'pilot', 'package': 'notebook'}[stage]
    if required is not None and not completed(required):
        raise ValueError('Missing prerequisite pass evidence: ' + required)


def analyze(run):
    plan = read(run / 'plan.json')
    stage = plan['stage']
    report = {'selected_stage_pass': False, 'stage': stage, 'sdk_checks_pass': False,
              'behavioral_parity_pass': None, 'overall_release_compliance': 'UNRESOLVED',
              'remaining_blockers': ['Training restoration and immutable authorized inputs incomplete',
                                     'Redistribution authorization unresolved', 'Actual A30 runtime unverified']}
    # Always compute parity, even when a separate SDK/operational gate fails.
    if stage != 'gpu':
        _, refs = V.references()
        stem = 'jupyter_submission' if stage == 'notebook' else 'submission'
        comparison = V.compare(run / (stem + '.jsonl'), run / (stem + '.diagnostics'), refs[:plan['count']])
        report.update(comparison=comparison, behavioral_parity_pass=comparison['parity_pass'])
    try:
        check_image(run / 'image-inspect.json')
        I.require_equal('run.build', V.sha(HERE / 'BUILD.json'), plan['build_sha256'])
        preflight = read(run / 'container-preflight.json')
        I.require_equal('preflight.success', True, preflight['success'])
        I.require_equal('source.predict', V.sha(HERE / 'overlay/predict.py'), preflight['predict_sha256'])
        I.require_equal('source.notebook', V.sha(HERE / 'overlay/predict_notebook.ipynb'), preflight['notebook_sha256'])
        container = read(run / 'container-final.json')[0]
        built = read(HERE / 'BUILD.json')
        I.require_equal('container.requested_image', built['image']['Id'], container['Config']['Image'])
        I.require_equal('container.network', 'none', container['HostConfig']['NetworkMode'])
        I.require_equal('container.extra_hosts', [], container['HostConfig'].get('ExtraHosts') or [])
        I.require_equal('container.exit_code', 0, container['State']['ExitCode'])
        I.require_equal('container.running', False, container['State']['Running'])
        I.require_equal('attach.exit', 0, read(run / 'exit.json')['docker_attach_exit_code'])
        I.require_equal('log.exit', 0, read(run / 'exit.json')['tee_exit_code'])
        rows = [row for p in run.glob('sdk-imports.*.jsonl') for row in V.read_rows(p)]
        imports = [r for r in rows if r.get('event') == 'sdk_exec']
        opens = [r for r in rows if r.get('event') == 'environment_open']
        for row in imports:
            name = Path(row['path']).relative_to('/data/public_test/zaic_tools')
            I.require_equal('SDK.allowed', True, row['allowed'])
            I.require_equal('SDK.' + str(name), V.sha(ROOT / 'lifemate/public_test/zaic_tools' / name), row['sha256'])
        if stage != 'gpu':
            assert any(r['path'].endswith('/zaic_tools/__init__.py') for r in imports), 'No actual SDK import'
            assert any(r['path'].endswith('/zaic_tools/executor.py') for r in imports), 'No mounted executor import'
            I.require_equal('environment.open_count', plan['count'], len(opens))
            I.require_equal('environment.sample_order', plan['expected_ids'], [Path(r['path']).parent.name for r in opens])
            assert all(r['allowed'] for r in opens), 'Environment read outside SDK'
        report['sdk_checks_pass'] = True
        report['sdk_module_executions'] = len(imports)
        report['permitted_environment_opens'] = len(opens)
        if stage == 'notebook':
            notebook = read(run / 'notebook-execution.json')
            I.require_equal('notebook.success', True, notebook['success'])
            I.require_equal('notebook.modified_cells', False, notebook['modified_cells'])
        report['operational_checks_pass'] = True
        report['selected_stage_pass'] = stage == 'gpu' or (report['comparison']['parity_pass'] and report['comparison']['timing']['pass'])
    except (Exception, AssertionError) as error:
        report['operational_error'] = str(error)
    write(run / 'report.json', report)
    if report['selected_stage_pass']:
        marker = HERE / 'evidence' / (stage + '-pass.json')
        # Repeated bounded attempts can update only their own success pointer; every run is preserved.
        marker.write_text(json.dumps({'build_sha256': V.sha(HERE / 'BUILD.json'),
            'report': str((run / 'report.json').relative_to(HERE)), 'report_sha256': V.sha(run / 'report.json')}, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['selected_stage_pass'] else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['context', 'base', 'record-build', 'resume-build', 'image', 'inputs', 'prerequisite', 'completed', 'analyze'])
    parser.add_argument('path', nargs='?')
    parser.add_argument('stage', nargs='?')
    args = parser.parse_args()
    if args.action == 'context': print(check_context())
    elif args.action == 'base': print(base(Path(args.path)))
    elif args.action == 'record-build': record_build(Path(args.path))
    elif args.action == 'resume-build': resume_build(Path(args.path))
    elif args.action == 'image': check_image(Path(args.path))
    elif args.action == 'inputs': inputs(Path(args.path), args.stage)
    elif args.action == 'prerequisite': prerequisite(args.path)
    elif args.action == 'completed': return 0 if completed(args.path) else 1
    elif args.action == 'analyze': return analyze(Path(args.path))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2)
