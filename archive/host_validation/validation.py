#!/usr/bin/env python3
"""Host-only preflight and post-run audit. Never imports models or ToolEnv."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
from image_identity import (DEFAULT_RELEASE_MANIFEST, IdentityError, verify_sealed_archive,
                            make_identity_record, read_identity_record, require_equal, verify_container_reference)

HERE = Path(__file__).resolve().parent
COUNTS = {'smoke': 1, 'pilot': 10, 'full': 634}
FIELDS = ('id', 'tool_calls', 'state_hash')

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def write_json(path, obj):
    with Path(path).open('x', encoding='utf8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')

def reject_constant(value):
    raise ValueError('Non-finite JSON number: ' + value)

def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key: ' + key)
        result[key] = value
    return result

def parse_json(text):
    return json.loads(text, parse_constant=reject_constant, object_pairs_hook=unique_object)

def read_json(path):
    return parse_json(Path(path).read_text())

def read_rows(path):
    return [parse_json(line) for line in Path(path).read_text().splitlines() if line.strip()]

def exact(a, b):
    # JSON object order is immaterial; list order and JSON numeric types are preserved.
    return json.dumps(a, sort_keys=True, ensure_ascii=False, allow_nan=False) == json.dumps(b, sort_keys=True, ensure_ascii=False, allow_nan=False)

def references():
    m = read_json(HERE / 'reference/manifest.json')
    for name, expected in m['reference_files'].items():
        if sha(HERE / 'reference' / name) != expected:
            raise ValueError('Reference integrity failure: ' + name)
    rows = read_rows(HERE / 'reference/frozen_k.jsonl')
    assert len(rows) == 634 and len({r['id'] for r in rows}) == 634
    return m, rows

def audio_paths(row):
    paths = [row['audio']]
    paths += [turn['audio'] for turn in row['history'] if isinstance(turn, dict) and turn.get('audio')]
    return paths

def prepare(split, out, mode, workflow):
    identity = read_identity_record(out / 'image-identity.json', out / 'image-inspect.json')
    m, baseline = references()
    inputs = m['input_files']
    for rel, expected in inputs.items():
        p = split / rel
        if not p.resolve().is_relative_to(split.resolve()) or sha(p) != expected:
            raise ValueError('Input identity mismatch: ' + rel)
    cases = read_rows(split / 'public_test.jsonl')
    if [r['id'] for r in cases] != [r['id'] for r in baseline]:
        raise ValueError('Complete 634-input ID sequence differs from frozen K')
    chosen = cases[:COUNTS[mode]]
    audio = read_json(HERE / 'reference/audio_sha256.json')
    checked = set()
    for row in chosen:
        if set(row) != {'id', 'audio', 'context', 'history'}:
            raise ValueError('Unexpected input fields: ' + row['id'])
        for rel in audio_paths(row):
            p = split / rel
            if Path(rel).is_absolute() or '..' in Path(rel).parts or not rel.startswith('audio/'):
                raise ValueError('Invalid audio path')
            if not p.resolve().is_relative_to((split / 'audio').resolve()):
                raise ValueError('Audio escapes split')
            if rel not in checked and (rel not in audio or sha(p) != audio[rel]):
                raise ValueError('Missing/changed audio: ' + rel)
            checked.add(rel)
    # Never descend into or read public_test_environment. Only the mounted SDK may do so.
    if not (split / 'public_test_environment').is_dir():
        raise ValueError('Required SDK environment directory is absent')
    write_json(out / 'plan.json', {
        'schema_version': 1, 'mode': mode, 'workflow': workflow, 'count': len(chosen),
        'expected_ids': [r['id'] for r in chosen],
        'image_config_digest': identity['image_config_digest'],
        'docker_store_image_id': identity['docker_store_image_id'],
        'verified_docker_image_reference': identity['verified_docker_image_reference'],
        'image_identity_sha256': sha(out / 'image-identity.json'),
        'reference_manifest_sha256': sha(HERE / 'reference/manifest.json'),
        'input_files': inputs, 'verified_audio_files': len(checked),
        'data_root': str(split), 'prepared_utc': datetime.now(timezone.utc).isoformat(),
        'resources': {'cpus': 16, 'memory_bytes': 48 * 1024**3, 'shm_bytes': 2 * 1024**3},
    })

def image_check(path, release_manifest, archive_path, output):
    print('Verifying complete sealed archive SHA-256/MD5, configuration and layer; no extraction.', file=sys.stderr, flush=True)
    sealed = verify_sealed_archive(release_manifest, archive_path)
    record = make_identity_record(path, sealed)
    write_json(output, record)
    print(json.dumps({key: record[key] for key in ('image_config_digest', 'docker_store_image_id', 'docker_store_id_semantics', 'rootfs_diff_ids')}, indent=2), file=sys.stderr)
    print(record['verified_docker_image_reference'])
    return record


def compare(predictions, diagnostics, expected):
    issues, rows = [], []
    def issue(kind, **detail):
        issues.append({'kind': kind, **detail})
    try:
        for line_no, line in enumerate(predictions.read_text().splitlines(), 1):
            try:
                if not line.strip():
                    raise ValueError('Blank JSONL record')
                row = parse_json(line)
                if not isinstance(row, dict) or not isinstance(row.get('id'), str):
                    raise ValueError('Record must be an object with a string id')
                rows.append(row)
            except (ValueError, TypeError) as e:
                issue('malformed_record', line=line_no, error=str(e))
    except OSError as e:
        issue('missing_predictions', error=str(e))
    expected_ids = [r['id'] for r in expected]
    actual_ids = [r['id'] for r in rows]
    counts = Counter(actual_ids)
    for rid, count in counts.items():
        if count > 1:
            issue('duplicate_request', id=rid, count=count)
        if rid not in expected_ids:
            issue('unexpected_request', id=rid)
    for index, rid in enumerate(expected_ids):
        if rid not in counts:
            issue('missing_request', index=index, id=rid)
    if actual_ids != expected_ids:
        issue('request_order_or_coverage', expected=expected_ids, actual=actual_ids)
    receipts = {}
    for path in sorted(diagnostics.glob('*.result.json')):
        try:
            rec = read_json(path)
            rid = rec['id']
            if not isinstance(rid, str):
                raise ValueError('Receipt id must be a string')
            if rid in receipts:
                issue('duplicate_receipt', id=rid, file=path.name)
            receipts[rid] = rec
            if rid not in expected_ids:
                issue('unexpected_receipt', id=rid, file=path.name)
        except (OSError, ValueError, KeyError, TypeError) as e:
            issue('invalid_receipt', file=path.name, error=str(e))
    actual_map = {r['id']: r for r in rows}
    matched, statuses, times, divergences = 0, Counter(), [], []
    timing_issues = []
    for index, ref in enumerate(expected):
        rid = ref['id']; row = actual_map.get(rid); rec = receipts.get(rid)
        start = len(issues)
        if row is not None:
            if set(row) != {*FIELDS, 'time'}:
                issue('output_schema', index=index, id=rid, fields=sorted(row))
            calls = row.get('tool_calls')
            if not isinstance(calls, list):
                issue('invalid_tool_calls', index=index, id=rid, actual=calls)
                calls = []
            for n in range(max(len(calls), len(ref['tool_calls']))):
                a = calls[n] if n < len(calls) else None
                b = ref['tool_calls'][n] if n < len(ref['tool_calls']) else None
                if not exact(a, b):
                    d = {'index': index, 'id': rid, 'call_index': n, 'expected': b, 'actual': a}
                    issue('ordered_tool_call', **d); divergences.append(d)
            if not exact(row.get('state_hash'), ref['state_hash']):
                issue('state_hash', index=index, id=rid, expected=ref['state_hash'], actual=row.get('state_hash'))
            t = row.get('time')
            if type(t) is not int or not 0 <= t < 30000:
                timing_issues.append({'index': index, 'id': rid, 'field': 'time_ms', 'actual': t})
            else:
                times.append(t)
        if rec is None:
            issue('missing_receipt', index=index, id=rid)
        else:
            statuses[str(rec.get('status'))] += 1
            for key in ('status', 'error'):
                if key not in rec or not exact(rec[key], ref[key]):
                    issue('completion_' + key, index=index, id=rid, expected=ref[key], actual=rec.get(key))
            if rec.get('status') not in ('finished', 'max_steps') or rec.get('error'):
                issue('failed_request', index=index, id=rid, status=rec.get('status'), error=rec.get('error'))
            if rec.get('toolenv_instances') != 1 or type(rec.get('toolenv_instances')) is not int:
                issue('toolenv_count', index=index, id=rid, actual=rec.get('toolenv_instances'))
            if rec.get('index') != index:
                issue('receipt_order', index=index, id=rid, actual=rec.get('index'))
            if row is not None:
                prediction = {k: row.get(k) for k in FIELDS}
                if not exact(rec.get('prediction'), prediction):
                    issue('receipt_prediction', index=index, id=rid)
                try:
                    emitted = [{'name': e['action']['name'], 'arguments': e['action']['arguments']}
                               for e in rec['events'] if e.get('type') == 'tool_result']
                    if not exact(emitted, row.get('tool_calls')):
                        issue('actual_call_log', index=index, id=rid, expected=emitted, actual=row.get('tool_calls'))
                except (KeyError, TypeError, AttributeError) as e:
                    issue('invalid_call_log', index=index, id=rid, error=str(e))
            seconds = rec.get('dispatch_seconds')
            if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 <= seconds < 30:
                timing_issues.append({'index': index, 'id': rid, 'field': 'dispatch_seconds', 'actual': seconds})
            elif row is not None and row.get('time') != int(seconds * 1000):
                timing_issues.append({'index': index, 'id': rid, 'field': 'time_vs_receipt', 'actual': row.get('time'), 'expected': int(seconds * 1000)})
        if row is not None and len(issues) == start and counts[rid] == 1:
            matched += 1
    failed_receipts = [{'id': rid, 'status': rec.get('status'), 'error': rec.get('error'),
                        'prediction': rec.get('prediction'), 'events': rec.get('events')}
                       for rid, rec in receipts.items() if rec.get('status') not in ('finished', 'max_steps') or rec.get('error')]
    consequential = [i for i in issues if i['kind'] in ('ordered_tool_call', 'state_hash', 'completion_status', 'completion_error', 'missing_request', 'failed_request')]
    consequential.sort(key=lambda d: (d.get('index', -1), d.get('call_index', 10**6)))
    return {'expected': len(expected), 'records': len(rows), 'exact_cases': matched,
            'parity_pass': not issues, 'issues': issues,
            'first_divergence': consequential[0] if consequential else (issues[0] if issues else None),
            'all_action_divergences': divergences, 'failed_receipts': failed_receipts, 'status_counts': dict(statuses),
            'timing': {'pass': not timing_issues and len(times) == len(expected) and len(receipts) == len(expected),
                       'issues': timing_issues, 'measured_records': len(times), 'max_ms': max(times) if times else None,
                       'mean_ms': sum(times) / len(times) if times else None,
                       'limit_ms_exclusive': 30000, 'equality_to_reference_required': False}}

def analyze(run, peer=None):
    manifest, all_refs = references()
    plan = read_json(run / 'plan.json')
    expected = all_refs[:COUNTS[plan['mode']]]
    if plan['expected_ids'] != [r['id'] for r in expected] or plan['count'] != len(expected):
        raise ValueError('Run plan ID/count mismatch')
    if plan['reference_manifest_sha256'] != sha(HERE / 'reference/manifest.json'):
        raise ValueError('Run uses a different reference manifest')
    name = 'submission' if plan['workflow'] == 'cli' else 'jupyter_submission'
    pred = run / (name + '.jsonl')
    partial = pred.with_suffix('.jsonl.partial')
    compared = pred if pred.exists() else partial
    result = compare(compared, run / (name + '.diagnostics'), expected)
    def optional(name):
        try:
            return read_json(run / name)
        except (OSError, ValueError):
            return None
    final = optional('container-final.json')
    exit_meta = optional('exit.json')
    created = optional('container-created.json')
    preflight = optional('container-preflight.json')
    loading = optional(name + '.diagnostics/loading.json')
    identity = None
    identity_error = None
    try:
        identity = read_identity_record(run / 'image-identity.json', run / 'image-inspect.json')
        require_equal('plan.image_identity_sha256', sha(run / 'image-identity.json'), plan.get('image_identity_sha256'))
        for key in ('image_config_digest', 'docker_store_image_id', 'verified_docker_image_reference'):
            require_equal('plan.' + key, identity[key], plan.get(key))
    except (OSError, ValueError, KeyError, TypeError) as e:
        identity_error = str(e)
        identity = None
    image_reference = identity['verified_docker_image_reference'] if identity else None
    container_identity_errors = []
    def container_matches(value):
        if identity is None or value is None:
            return False
        try:
            return verify_container_reference(value, identity)
        except (ValueError, KeyError, TypeError) as e:
            container_identity_errors.append(str(e))
            return False
    final_image_matches = container_matches(final)
    created_image_matches = container_matches(created)
    docker_ok = bool(final_image_matches and final and not final[0]['State']['Running']
                     and final[0]['State']['ExitCode'] == 0 and not final[0]['State']['OOMKilled']
                     and exit_meta and exit_meta['docker_attach_exit_code'] == 0 and exit_meta['tee_exit_code'] == 0)
    runtime_ok = bool(loading and loading.get('backend') == 'sm120' and loading.get('split') == 'public_test'
                      and loading.get('all_models_load_seconds', 0) > 0)
    isolated = False
    if created:
        obj = created[0]; cfg = obj['HostConfig']; mounts = obj.get('Mounts', [])
        isolated = (created_image_matches and cfg['NetworkMode'] == 'none'
                    and cfg['NanoCpus'] == 16_000_000_000 and cfg['Memory'] == 48 * 1024**3
                    and cfg['MemorySwap'] == cfg['Memory'] and cfg['ShmSize'] == 2 * 1024**3
                    and any(x['Destination'] == '/data/public_test' and not x['RW'] for x in mounts)
                    and obj['Config'].get('Hostname') == 'lifemate-offline'
                    and any(x.replace('=', ':') == 'lifemate-offline:127.0.0.1' for x in cfg.get('ExtraHosts', [])))
    sdk_rows, sdk_errors = [], []
    for p in sorted(run.glob('sdk-imports.*.jsonl')):
        try:
            sdk_rows += read_rows(p)
        except (OSError, ValueError) as e:
            sdk_errors.append(str(e))
    legacy_imported = [r for r in sdk_rows if r.get('event') == 'sdk_exec' and r.get('legacy_packaged_sdk')]
    imported = [r for r in sdk_rows if r.get('event') == 'sdk_exec' and not r.get('legacy_packaged_sdk')]
    for row in imported:
        rel = row.get('path', '').removeprefix('/data/public_test/')
        if not row.get('allowed') or manifest['input_files'].get(rel) != row.get('sha256'):
            sdk_errors.append(row)
    sdk_ok = bool(imported and not sdk_errors and any(r['path'].endswith('/zaic_tools/executor.py') for r in imported))
    packaged_ok = bool(preflight and preflight.get('success') and preflight.get('packaged_data_audit_pass') and preflight.get('gpu_available'))
    harness = optional('harness-sha256.json')
    harness_ok = bool(harness and all((run / 'harness' / name).is_file() and sha(run / 'harness' / name) == digest for name, digest in harness.items()))
    expected_predict = manifest['release_source_files']['source/predict.py']
    expected_notebook = manifest['release_source_files']['source/predict_notebook.ipynb']
    source_ok = bool(preflight and preflight.get('predict_sha256') == expected_predict and preflight.get('notebook_sha256') == expected_notebook)
    sdk_compliance = bool(preflight and preflight.get('sdk_packaging_audit_pass') and not legacy_imported)
    complete = pred.is_file() and not partial.exists()
    notebook_execution = optional('notebook-execution.json')
    notebook_ok = bool(plan['workflow'] == 'notebook' and notebook_execution and notebook_execution.get('success')
                       and notebook_execution.get('source_sha256') == expected_notebook
                       and (run / 'predict_notebook.executed.ipynb').is_file() and result['parity_pass'] and complete)
    peer_result = None
    if peer:
        other_plan = read_json(peer / 'plan.json')
        if other_plan['expected_ids'] != plan['expected_ids'] or other_plan['workflow'] == plan['workflow']:
            raise ValueError('Peer must be the other workflow with exactly the same selected IDs')
        other_name = 'submission' if other_plan['workflow'] == 'cli' else 'jupyter_submission'
        peer_result = compare(peer / (other_name + '.jsonl'), peer / (other_name + '.diagnostics'), expected)
    behavioral_ok = (docker_ok and runtime_ok and isolated and sdk_ok and packaged_ok and harness_ok and source_ok and complete
          and result['parity_pass'] and result['timing']['pass']
          and (plan['workflow'] != 'notebook' or notebook_ok)
          and (peer_result is None or (peer_result['parity_pass'] and peer_result['timing']['pass'])))
    ok = behavioral_ok and sdk_compliance
    resource_summary = {'samples': 0, 'sampled_gpu_peak_mib': None, 'gpu_memory_includes_other_processes': True, 'continuous_peak_verified': False}
    try:
        samples = read_rows(run / 'resources.jsonl')
        gpu_mib = [int(s['gpu']['stdout'].split(',')[1].strip()) for s in samples if s.get('gpu', {}).get('exit_code') == 0]
        resource_summary.update(samples=len(samples), sampled_gpu_peak_mib=max(gpu_mib) if gpu_mib else None)
    except (OSError, ValueError, KeyError, IndexError):
        resource_summary['warning'] = 'Resource samples absent or incomplete; inspect resources.jsonl'
    recommendation = 'Do not proceed to full: resolve failed or missing evidence.'
    if ok and plan['mode'] == 'pilot':
        recommendation = 'All 10 cases verified. Full ' + plan['workflow'] + ' run may be launched explicitly.'
    elif ok:
        recommendation = 'Selected run passed; no automatic full execution.'
    elif behavioral_ok and not sdk_compliance:
        recommendation = f"All {len(expected)} selected behavioral/timing cases verified; packaged SDK compliance remains unresolved. Review this finding before recommending a full run."
    report = {
        'run': str(run), 'mode': plan['mode'], 'workflow': plan['workflow'], 'selected_run_pass': ok,
        'selected_behavioral_checks_pass': behavioral_ok, 'sdk_compliance_pass': sdk_compliance,
        'image_identity_verification': {'pass': identity is not None and created_image_matches and final_image_matches, 'error': identity_error,
            'container_errors': container_identity_errors,
            'image_config_digest': identity['image_config_digest'] if identity else None,
            'docker_store_image_id': image_reference, 'verified_docker_image_reference': image_reference},
        'docker_execution_success': docker_ok, 'runtime_initialization_success': runtime_ok,
        'exact_k_trajectory_parity': result, 'complete_output': complete,
        'timing_compliance': result['timing'], 'notebook_parity': 'PASS_SELECTED_CASES' if notebook_ok else ('NOT_TESTED' if plan['workflow'] == 'cli' else 'FAIL_OR_INCOMPLETE'),
        'peer_parity': peer_result, 'mounted_toolenv_imports': {'pass': sdk_ok, 'executions': len(imported), 'errors': sdk_errors},
        'legacy_packaged_sdk': {'paths': preflight.get('packaged_sdk_paths', []) if preflight else [], 'module_executions': legacy_imported, 'compliance_pass': sdk_compliance},
        'offline_compliance': 'PASS_WITH_HOSTNAME_WORKAROUND' if isolated and behavioral_ok else 'NOT_ESTABLISHED',
        'isolation_and_resource_configuration': isolated, 'packaged_data_audit': packaged_ok,
        'source_identity_verified': source_ok, 'harness_snapshot_verified': harness_ok, 'sampled_resources': resource_summary,
        'model_loading': loading, 'a30_status': 'NOT_TESTED; sealed backend explicitly rejects capability 8.0',
        'recommendation': recommendation, 'release_status': 'RELEASE_BLOCKED',
        'remaining_release_blockers': [
            'Packaged train/zaic_tools is present and used by frozen schema helpers; mounted ToolEnv evidence does not clear this dependency.',
            'Complete host CLI and independent notebook 634-case parity/timing evidence unless already separately verified.',
            'Offline hostname fix must be tested in a separately identified image without extra hostname flags.',
            'Actual A30 behavior, memory and timing remain unverified; the sealed backend rejects A30.',
            'Complete authorized training audio/preparation/environment restoration remains unverified.',
            'Redistribution/company transfer rights and approved destinations remain unresolved.',
            'Local rule A30 versus guide RTX 5090 and CUDA wording require organizer clarification.'
        ],
    }
    analysis_dir = Path(tempfile.mkdtemp(prefix='analysis-', dir=run))
    write_json(analysis_dir / 'report.json', report)
    lines = ['# Host validation report', '', 'Status: RELEASE_BLOCKED', '',
             f"Mode/workflow: {plan['mode']} / {plan['workflow']}", '',
             f'Docker execution: {docker_ok}', f'Runtime initialization: {runtime_ok}',
             f"Exact K parity: {result['exact_cases']}/{len(expected)}; overall parity pass: {result['parity_pass']}",
             f"Timing compliance: {result['timing']['pass']} (no timing equality requirement)",
             f"Notebook parity: {report['notebook_parity']}", f"Offline: {report['offline_compliance']}",
             f'Mounted SDK imports verified: {sdk_ok}', f'SDK packaging/import compliance: {sdk_compliance}', f"A30: {report['a30_status']}", '', recommendation, '',
             'Full mismatch details and first divergence: report.json', '', 'Remaining blockers:', '']
    lines += ['- ' + b for b in report['remaining_release_blockers']]
    (analysis_dir / 'REPORT.md').write_text('\n\n'.join(lines) + '\n')
    print(analysis_dir / 'report.json')
    print(recommendation)
    return ok

def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    s = sub.add_parser('prepare'); s.add_argument('--split', type=Path, required=True); s.add_argument('--out', type=Path, required=True)
    s.add_argument('--mode', choices=COUNTS, required=True); s.add_argument('--workflow', choices=['cli', 'notebook'], required=True)
    s = sub.add_parser('image-check'); s.add_argument('path', type=Path)
    s.add_argument('--release-manifest', type=Path, default=DEFAULT_RELEASE_MANIFEST)
    s.add_argument('--archive', type=Path)
    s.add_argument('--output', type=Path, required=True)
    s = sub.add_parser('container-image-check'); s.add_argument('run', type=Path)
    s = sub.add_parser('analyze'); s.add_argument('run', type=Path); s.add_argument('--peer', type=Path)
    s = sub.add_parser('compare'); s.add_argument('--predictions', type=Path, required=True); s.add_argument('--diagnostics', type=Path, required=True)
    s.add_argument('--mode', choices=COUNTS, required=True); s.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.command == 'prepare': prepare(a.split, a.out, a.mode, a.workflow)
    elif a.command == 'image-check': image_check(a.path, a.release_manifest, a.archive, a.output)
    elif a.command == 'container-image-check':
        identity = read_identity_record(a.run / 'image-identity.json', a.run / 'image-inspect.json')
        verify_container_reference(read_json(a.run / 'container-created.json'), identity)
    elif a.command == 'analyze': return 0 if analyze(a.run.resolve(), a.peer.resolve() if a.peer else None) else 1
    else:
        _, refs = references(); report = compare(a.predictions, a.diagnostics, refs[:COUNTS[a.mode]])
        write_json(a.output, report); return 0 if report['parity_pass'] and report['timing']['pass'] else 1
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError, AssertionError) as e:
        print('Validation error: ' + str(e), file=sys.stderr); sys.exit(2)
