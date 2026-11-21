#!/usr/bin/env python3
"""Host-only RC2 continuation at 8192 tokens; complete output is diagnostic, not certified eligible."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import sys
import tempfile
import traceback

sys.dont_write_bytecode = True
import run_private_test as host
from check_results import exact, official_validator, parse, read, rows, sha, write
from recovery_checks import collect_stage, merge_inventory, require

HERE = Path(__file__).resolve().parent
EXTRA = ('continue_private_test.py', 'recovery_checks.py', 'container/continue_inference.py')
DRIVER_CMD = ['python3', '/validation/continue_inference.py']
ORIGINAL_CMD = ['/bin/bash', '/code/predict.sh', '--data-root', '/data', '--split',
                'private_test', '--output', '/result/submission.jsonl']
ELIGIBILITY = ('NOT ESTABLISHED: original 8192-token model policy and image are preserved, but batch error '
               'handling, request selection and export of genuine failure receipts differ from the submitted '
               'CLI/notebook. Documented rules require frozen-solution reproducibility. No automatic submission.')


def fingerprint():
    return {name: sha(HERE / name) for name in (*host.HELPERS, *EXTRA)}


def evidence_files(run):
    result = []
    for entry in run.iterdir():
        if entry.name in ('dataset', 'REPORT.json'):
            continue
        result.extend([entry] if entry.is_file() else [p for p in entry.rglob('*') if p.is_file()])
    for path in result:
        require(path.resolve().is_relative_to(run.resolve()) and not any(x.endswith('_environment') for x in path.parts)
                and path.name != 'state.json', 'Unsafe evidence path')
    return result


def verify_seal(run, report):
    sealed = report.get('evidence_sha256')
    require(isinstance(sealed, dict) and sealed, 'Missing sealed evidence: ' + str(run))
    actual = {str(p.relative_to(run)): p for p in evidence_files(run)}
    require(set(actual) == set(sealed), 'Evidence files added or removed: ' + str(run))
    for rel, path in actual.items():
        require(sha(path) == sealed[rel], 'Evidence changed: ' + str(path))


def discover_sources(base, output_dir):
    sources = [base]
    digest = sha(base / 'REPORT.json')
    for marker in sorted(output_dir.glob('*-continue-*/RECOVERY.json')):
        value = read(marker)
        if value.get('source_run') != str(base):
            continue
        require(value.get('source_report_sha256') == digest, 'Original source REPORT changed')
        require((marker.parent / 'REPORT.json').is_file(),
                'Unsealed continuation may still be running; refusing duplicate execution: ' + str(marker.parent))
        sources.append(marker.parent)
    return sources


def check_stage_container(run, report, package, build, split, cmd, stage_name, *, live_check):
    stage = run / stage_name
    identity = host.verify_loaded(read(run / 'image-inspect.json'), package, build, read(run / 'archive-identity.json'))
    plan = read(run / 'plan.json')
    for name in ('container-created.json', 'container-final.json'):
        host.verify_container(read(stage / name), identity, split, stage, run / 'harness', cmd,
                              report['gpu']['uuid'], f"{plan['uid']}:{plan['gid']}", cuda_compat=report['cuda_compat'])
    final = read(stage / 'container-final.json')[0]
    require(not final['State']['Running'], 'Source container still running')
    require(not final['State'].get('OOMKilled') and not final['State'].get('Error'),
            'Source container has an OOM/runtime error; evidence retained for review')
    if live_check:
        cid = (stage / 'container-id.txt').read_text().strip()
        require(cid == final['Id'], 'Saved container ID mismatch')
        inspected = host.command(['docker', 'inspect', cid], check=False)
        if inspected.returncode == 0:
            current = parse(inspected.stdout)
            host.verify_container(current, identity, split, stage, run / 'harness', cmd,
                                  report['gpu']['uuid'], f"{plan['uid']}:{plan['gid']}", cuda_compat=report['cuda_compat'])
            require(not current[0]['State']['Running'] and current[0]['State']['StartedAt'] == final['State']['StartedAt']
                    and current[0]['State']['FinishedAt'] == final['State']['FinishedAt'],
                    'Source container was restarted after evidence sealing')
        else:
            require('No such' in inspected.stderr, 'Cannot establish source container state: ' + inspected.stderr)
    return final


def collect_source(run, base, workspace, cases, manifest, catalog, validator, package, build, cuda_compat):
    report = read(run / 'REPORT.json')
    verify_seal(run, report)
    require(report.get('workspace') == str(workspace), 'Source host workspace differs')
    require(report.get('archive_sha256') == host.ARCHIVE_SHA and report.get('zip_sha256') == host.ZIP_SHA,
            'Source artifact identity mismatch')
    require(report.get('cuda_compat') is cuda_compat, 'Use the same --cuda-compat setting as source evidence')
    recorded = report.get('workflow_sha256', {})
    expected = host.source_fingerprint() if run == base else fingerprint()
    require(recorded == expected, 'Source runner files differ; preserve the recorded workflow version')
    if run == base:
        require(report.get('mode') == 'full', '--resume-from must be the original full run')
        indices, cmd = list(range(len(cases))), ORIGINAL_CMD
    else:
        require(report.get('mode') == 'continuation', 'Unexpected continuation mode')
        if not (run / 'inference').exists():
            return {}, set(), []  # Earlier preflight failure; no inference was attempted.
        selection = read(run / 'harness/continuation-plan.json')
        indices, cmd = selection['indices'], DRIVER_CMD
        require(indices == sorted(set(indices)) and all(type(i) is int and 0 <= i < len(cases) for i in indices)
                and [cases[i]['id'] for i in indices] == selection['ids'], 'Invalid previous selection')
    require(exact(read(run / 'input-manifest.json'), manifest), 'Source SDK/input/audio manifest mismatch')
    split = Path(read(run / 'plan.json')['host_input']).resolve(strict=True)
    require(split == (run / 'dataset/private_test').resolve(), 'Unexpected source data mapping')
    # No environment/state file is inspected. Official ZIP extraction and read-only mounts cover those bytes.
    for rel, digest in manifest.items():
        path = (split / rel).resolve()
        require(path.is_relative_to(split) and not any(p.endswith('_environment') for p in path.parts)
                and path.name != 'state.json' and sha(path) == digest, 'Source input/SDK/audio changed: ' + rel)
    for name in ('preflight.py', 'sitecustomize.py'):
        require(sha(run / 'harness' / name) == expected['container/' + name], 'Source preflight/observer changed')
    if run != base:
        for name in ('run_private_test.py', 'check_results.py', 'recovery_checks.py'):
            require(sha(run / 'harness' / name) == expected[name], 'Mounted recovery helper changed')
        require(sha(run / 'harness/continue_inference.py') == expected['container/continue_inference.py'], 'Recovery driver changed')
    preflight = check_stage_container(run, report, package, build, split,
                                     ['python3', '/validation/preflight.py'], 'preflight', live_check=True)
    require(preflight['State']['ExitCode'] == 0 and not preflight['State']['OOMKilled']
            and read(run / 'preflight/preflight.json').get('success') is True, 'Source preflight failed')
    check_stage_container(run, report, package, build, split, cmd, 'inference', live_check=True)
    return collect_stage(run / 'inference', cases, indices, manifest, validator, catalog)


def summary(verified, attempted, blocked, cases):
    details = [verified[i]['detail'] for i in sorted(verified)]
    return {'expected': len(cases), 'processed': len(verified), 'attempted': len(attempted),
            'finished': sum(x['status'] == 'finished' for x in details),
            'step_limit_requests': sum(x['status'] == 'max_steps' for x in details),
            'inference_failures': sum(x['inference_failure'] for x in details),
            'context_overflows': sum(x['context_overflow'] for x in details),
            'execution_failures': sum(x['execution_failure'] for x in details),
            'rejected_proposals': sum(len(x['rejected_proposals']) for x in details),
            'official_tool_schema_validation': 'PASS' if len(verified) == len(cases) else 'INCOMPLETE',
            'jsonl_schema_validation': 'PASS' if len(verified) == len(cases) else 'INCOMPLETE',
            'schema_method': 'Unchanged official zaic_tools/validate.py schema_validate, catalog and installed tools from official input; strict JSONL fields/IDs/types checked by host',
            'missing_ids': [c['id'] for i, c in enumerate(cases) if i not in verified],
            'unresolved_attempts': blocked, 'organizer_exact_execution': False,
            'submission_eligibility': ELIGIBILITY, 'context_size': 8192,
            'hash_verification': 'SDK receipt equality and execution provenance; no hidden-state access or ToolEnv replay'}


def assemble(run, destination, verified, attempted, blocked, cases):
    checked = summary(verified, attempted, blocked, cases)
    write(run / 'validation.json', checked)
    write(run / 'failures.json', {'failures': [verified[i]['detail'] for i in sorted(verified)
          if verified[i]['detail']['execution_failure']], 'unresolved_attempts': blocked})
    write(run / 'row-provenance.json', [{k: value for k, value in verified[i].items() if k not in ('raw', 'row')}
                                      for i in sorted(verified)])
    require(not blocked and set(verified) == set(range(len(cases))),
            'Incomplete authentic coverage; no final file published. Reuse this command for untouched requests; unresolved attempts are never retried automatically.')
    output = run / 'assembled.jsonl'
    with output.open('xb') as stream:
        for index in range(len(cases)):
            stream.write(verified[index]['raw'])
        stream.flush()
        os.fsync(stream.fileno())
    parsed = rows(output)
    require([r['id'] for r in parsed] == [c['id'] for c in cases]
            and all(exact(parsed[i], verified[i]['row']) for i in range(len(cases))), 'Assembly changed validated rows')
    digest = sha(output)
    if destination.exists():
        require(sha(destination) == digest, 'Existing final output differs; refusing to overwrite')
    else:
        host.publish(output, destination, digest)
    sidecar = destination.with_suffix(destination.suffix + '.sha256')
    checksum = f'{digest}  {destination.name}\n'
    if sidecar.exists():
        require(sidecar.read_text() == checksum, 'Existing checksum differs; refusing to overwrite')
    else:
        with sidecar.open('x') as stream:
            stream.write(checksum)
    return {**checked, 'output': str(destination), 'sha256': digest}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume-from', required=True, type=Path, help='Original failed HOST full-run evidence directory')
    parser.add_argument('--workspace', type=Path, help='Actual HOST workspace; defaults to original REPORT.json workspace')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--gpu', default='0')
    parser.add_argument('--cuda-compat', action='store_true')
    args = parser.parse_args(argv)
    host.ensure_host()  # Must precede any Docker operation or output write.
    base = args.resume_from.expanduser().resolve(strict=True)
    base_report = read(base / 'REPORT.json')
    workspace = (args.workspace or Path(base_report['workspace'])).expanduser().resolve(strict=True)
    results = host.prepare_output_dir(args.output_dir)
    require(base.parent == results, 'Use the original full run output directory so locks and continuation discovery cover every attempt')
    locks = [host.lock(results / '.private_test_k48_46_rc2.host.lock')]
    run = None
    report = None
    try:
        sources = discover_sources(base, results)
        package, build, release, _ = host.load_verifier(workspace)
        require(base_report.get('mode') == 'full', 'Select the original failed full run')
        verify_seal(base, base_report)
        run = Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-continue-'), dir=results))
        destination = results / 'private_test_k48_46_final.jsonl'
        source_digest = sha(base / 'REPORT.json')
        write(run / 'RECOVERY.json', {'source_run': str(base), 'source_report_sha256': source_digest})
        report = {'mode': 'continuation', 'status': 'BLOCKED / INCOMPLETE', 'workspace': str(workspace),
                  'source_run': str(base), 'source_report_sha256': source_digest, 'sources': [str(p) for p in sources],
                  'source_reports_sha256': {str(p / 'REPORT.json'): sha(p / 'REPORT.json') for p in sources},
                  'workflow_sha256': fingerprint(), 'archive_sha256': host.ARCHIVE_SHA, 'zip_sha256': host.ZIP_SHA,
                  'cuda_compat': args.cuda_compat, 'docker_env_overrides': {'NVIDIA_DISABLE_REQUIRE': 'true'} if args.cuda_compat else {},
                  'organizer_exact_execution': False, 'submission_eligibility': ELIGIBILITY, 'context_size': 8192,
                  'output_created': False, 'output_dir': str(results), 'requested_output': str(destination)}
        print('EVIDENCE:', run, '\nHOST OUTPUT:', destination, flush=True)
        print('Original RC2 image/context; modified batch failure handling. Complete output remains a diagnostic artifact.', flush=True)
        report['docker_endpoint'] = host.local_docker_endpoint()
        require(shutil.disk_usage(results).free >= 5 * 1024**3, 'Need 5 GiB free in --output-dir')
        split, cases, manifest = host.extract_dataset(workspace / 'lifemate/docs/organizer/private_test.zip', run)
        catalog, validator = read(split / 'private_test_tools_catalog.json'), official_validator(split)
        inventories = [collect_source(p, base, workspace, cases, manifest, catalog, validator, package, build, args.cuda_compat)
                       for p in sources]
        verified, attempted, blocked = merge_inventory(inventories)
        pending = sorted(set(range(len(cases))) - attempted)
        report['reused_rows'] = len(verified)
        report['new_requests_selected'] = len(pending)
        write(run / 'before.json', summary(verified, attempted, blocked, cases))
        print(f'Validated authentic rows: {len(verified)}; untouched requests: {len(pending)}; unresolved attempts: {len(blocked)}', flush=True)
        if pending:
            info = parse(host.command(['docker', 'info', '--format', '{{json .}}']).stdout)
            require(info.get('OSType') == 'linux' and info.get('NCPU', 0) >= 16 and info.get('MemTotal', 0) >= 56 * 1024**3,
                    'Host requires Linux Docker, 16 CPUs and approximately 64 GiB RAM')
            write(run / 'docker-info.json', info)
            archive = host.verify_archive(workspace / 'lifemate-final-20261116-rc2/artifacts' / release['archive'], package, build, release)
            write(run / 'archive-identity.json', archive)
            identity = host.get_loaded(package, build, archive, run, info['DockerRootDir'])
            write(run / 'image-identity.json', identity)
            gpu = host.check_gpu(args.gpu)
            locks.append(host.lock(results / ('.validation-' + gpu['uuid'] + '.lock')))
            gpu = host.check_gpu(gpu['uuid'])
            require(gpu['uuid'] == base_report['gpu']['uuid'] and gpu['driver'] == base_report['gpu']['driver'],
                    'GPU/driver differs from original evidence')
            report['gpu'] = gpu
            report['image_identity'] = identity
            harness = run / 'harness'
            harness.mkdir()
            for name in ('preflight.py', 'sitecustomize.py', 'continue_inference.py'):
                shutil.copyfile(HERE / 'container' / name, harness / name)
            for name in ('run_private_test.py', 'check_results.py', 'recovery_checks.py'):
                shutil.copyfile(HERE / name, harness / name)
            write(harness / 'continuation-plan.json', {'indices': pending, 'ids': [cases[i]['id'] for i in pending],
                                                      'input_sha256': host.INPUT_SHA, 'context_size': 8192})
            write(run / 'plan.json', {'host_input': str(split), 'uid': os.getuid(), 'gid': os.getgid(),
                                      'expected_ids': [cases[i]['id'] for i in pending], 'command': DRIVER_CMD})
            stage, ok, _ = host.run_container(run, 'preflight', ['python3', '/validation/preflight.py'], 1800,
                                              identity, split, harness, gpu, cuda_compat=args.cuda_compat)
            require(ok and read(stage / 'preflight.json').get('success') is True, 'GPU/SDK/image preflight failed')
            host.check_gpu(gpu['uuid'])
            stage, ok, elapsed = host.run_container(run, 'inference', DRIVER_CMD, len(pending) * 30 + 600,
                                                   identity, split, harness, gpu, cuda_compat=args.cuda_compat)
            report['container_exit_ok'] = ok
            report['container_execution'] = elapsed
            state = read(stage / 'container-final.json')[0]['State']
            require(not state.get('OOMKilled') and not state.get('Error'), 'Container OOM/runtime error; final publication blocked')
            new = collect_stage(stage, cases, pending, manifest, validator, catalog)
            verified, attempted, blocked = merge_inventory([(verified, attempted, blocked), new])
        require(fingerprint() == report['workflow_sha256'], 'Runner changed during execution')
        for rel, digest in manifest.items():
            require(sha(split / rel) == digest, 'Input/SDK/audio changed during execution')
        for source in sources:
            require(sha(source / 'REPORT.json') == report['source_reports_sha256'][str(source / 'REPORT.json')],
                    'Source report changed during continuation')
            verify_seal(source, read(source / 'REPORT.json'))
        result = assemble(run, destination, verified, attempted, blocked, cases)
        report.update(status='COMPLETE DIAGNOSTIC — ELIGIBILITY NOT ESTABLISHED', output_created=True, result=result)
    except BaseException as error:
        if report is None:
            raise
        report['error'] = repr(error)
        with (run / 'error.txt').open('x') as stream:
            stream.write(traceback.format_exc())
    finally:
        if report is not None:
            report['evidence_sha256'] = {str(p.relative_to(run)): sha(p) for p in evidence_files(run)}
            write(run / 'REPORT.json', report)
        for stream in reversed(locks):
            stream.close()
    print('STATUS:', report['status'], '\nREPORT:', run / 'REPORT.json', flush=True)
    if report.get('error'):
        print('ERROR:', report['error'], flush=True)
    if report.get('result'):
        print(json.dumps(report['result'], ensure_ascii=False, indent=2), flush=True)
    print('STOP. Paste the terminal summary and REPORT.json for review. Nothing was uploaded.', flush=True)
    return 0 if report['output_created'] else 2


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, host.interrupt)
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, OSError) as error:
        print('BLOCKED:', error, file=sys.stderr)
        raise SystemExit(2)
