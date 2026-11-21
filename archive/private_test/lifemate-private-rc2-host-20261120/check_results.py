"""Validate production receipts without executing tools or reading environment state."""
import collections
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True


def parse(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    def bad(value):
        raise ValueError('Non-finite JSON constant: ' + value)
    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('Non-finite JSON number: ' + value)
        return result
    return json.loads(text, object_pairs_hook=pairs, parse_constant=bad, parse_float=finite_float)


def read(path):
    return parse(Path(path).read_text(encoding='utf8'))


def rows(path):
    result = []
    with Path(path).open(encoding='utf8') as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                raise ValueError(f'Blank line {number}: {path}')
            result.append(parse(line))
    return result


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b''):
            digest.update(block)
    return digest.hexdigest()


def write(path, value):
    with Path(path).open('x', encoding='utf8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def exact(a, b):
    return json.dumps(a, sort_keys=True, ensure_ascii=False, allow_nan=False) == json.dumps(b, sort_keys=True, ensure_ascii=False, allow_nan=False)


def official_validator(split):
    # Load only the original schema module. Importing the SDK CLI would construct
    # a fresh ToolEnv and inspect .allowed, so we deliberately do not run it.
    path = split / 'zaic_tools/validate.py'
    spec = importlib.util.spec_from_file_location('official_private_schema', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.schema_validate


def analyze(run, cases, split, input_manifest):
    issues, warnings, tool_errors, schema_errors = [], [], [], []
    status_counts = collections.Counter()
    times, dispatches, calls_total = [], [], 0
    expected_ids = [c['id'] for c in cases]
    prediction_file = run / 'submission.jsonl'
    partial = run / 'submission.jsonl.partial'
    diagnostic = run / 'submission.diagnostics'
    def issue(kind, **detail):
        issues.append({'kind': kind, **detail})
    def warn(kind, **detail):
        warnings.append({'kind': kind, **detail})
    output = []
    try:
        if not prediction_file.is_file() or partial.exists():
            issue('incomplete_output', final_exists=prediction_file.is_file(), partial_exists=partial.exists())
        output = rows(prediction_file if prediction_file.exists() else partial)
        if not all(isinstance(r, dict) for r in output):
            raise ValueError('Every output row must be an object')
    except (OSError, ValueError, TypeError) as error:
        issue('jsonl_read', error=str(error))
        output = []
    actual_ids = [r.get('id') for r in output]
    if actual_ids != expected_ids:
        issue('id_coverage_or_order', expected=expected_ids, actual=actual_ids)
    receipt_paths = sorted(diagnostic.glob('*.result.json'))
    expected_receipts = [f'{i:06d}.result.json' for i in range(len(cases))]
    if [p.name for p in receipt_paths] != expected_receipts:
        issue('receipt_coverage', expected=expected_receipts, actual=[p.name for p in receipt_paths])
    event_paths = sorted(diagnostic.glob('*.events.jsonl'))
    if [p.name for p in event_paths] != [f'{i:06d}.events.jsonl' for i in range(len(cases))]:
        issue('event_file_coverage')
    catalog = read(split / 'private_test_tools_catalog.json')
    schema_validate = official_validator(split)
    per_request = []
    for index, item in enumerate(cases):
        rid = item['id']
        row = output[index] if index < len(output) else None
        try:
            receipt = read(diagnostic / f'{index:06d}.result.json')
        except (OSError, ValueError) as error:
            issue('missing_or_invalid_receipt', id=rid, error=str(error))
            per_request.append({'id': rid, 'status': 'not_completed'})
            continue
        status = receipt.get('status')
        status_counts[str(status)] += 1
        per_request.append({'id': rid, 'status': status, 'error': receipt.get('error'),
                            'dispatch_seconds': receipt.get('dispatch_seconds')})
        if receipt.get('id') != rid or type(receipt.get('index')) is not int or receipt['index'] != index:
            issue('receipt_id_or_index', id=rid)
        if type(receipt.get('toolenv_instances')) is not int or receipt['toolenv_instances'] != 1:
            issue('toolenv_count', id=rid, actual=receipt.get('toolenv_instances'))
        if status not in ('finished', 'max_steps') or receipt.get('error'):
            issue('failed_request', id=rid, status=status, error=receipt.get('error'))
        if status == 'max_steps':
            warn('step_limit', id=rid)
        seconds = receipt.get('dispatch_seconds')
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 <= seconds < 30:
            issue('request_deadline', id=rid, seconds=seconds)
        else:
            dispatches.append(seconds)
        if row is None:
            continue
        if set(row) != {'id', 'tool_calls', 'state_hash', 'time'}:
            issue('output_fields', id=rid, actual=sorted(row))
        if row.get('id') != rid or not isinstance(row.get('state_hash'), str) or not re.fullmatch('[0-9a-f]{64}', row['state_hash']):
            issue('id_or_state_hash_type', id=rid)
        ms = row.get('time')
        if type(ms) is not int or not 0 <= ms < 30000:
            issue('time_field', id=rid, value=ms)
        elif type(seconds) in (float, int) and math.isfinite(seconds):
            times.append(ms)
            if ms != int(seconds * 1000):
                issue('time_vs_receipt', id=rid)
        prediction = {k: row.get(k) for k in ('id', 'tool_calls', 'state_hash')}
        if not exact(prediction, receipt.get('prediction')):
            issue('prediction_vs_receipt', id=rid)
        calls = row.get('tool_calls')
        if not isinstance(calls, list) or any(not isinstance(c, dict) or set(c) != {'name', 'arguments'} or not isinstance(c.get('name'), str) or not isinstance(c.get('arguments'), dict) for c in calls):
            issue('tool_call_structure', id=rid)
            continue
        calls_total += len(calls)
        try:
            events = receipt['events']
            if not isinstance(events, list):
                raise ValueError('receipt events must be a list')
            emitted = [{'name': e['action']['name'], 'arguments': e['action']['arguments']} for e in events if e.get('type') == 'tool_result']
            if not exact(emitted, calls):
                issue('actual_call_order', id=rid)
            event_rows = rows(diagnostic / f'{index:06d}.events.jsonl')
            if not exact(event_rows, events):
                issue('event_file_vs_receipt', id=rid)
            for call_index, event in enumerate(e for e in events if e.get('type') == 'tool_result'):
                result = event.get('result')
                if not isinstance(result, dict) or 'ok' not in result:
                    issue('invalid_tool_result', id=rid, call_index=call_index)
                elif result.get('ok') is not True:
                    tool_errors.append({'id': rid, 'call_index': call_index, 'result': result})
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            issue('execution_evidence', id=rid, error=str(error))
        allowed = {name for app in item['context']['installed_apps'].values() for name in app.get('tools', [])} | {'sys.ask_missing_info'}
        for call_index, result in enumerate(schema_validate(calls, catalog, allowed)):
            if result['ok'] is not True:
                schema_errors.append({'id': rid, 'call_index': call_index, **result})
    # The observer checks SDK origin and logs only filenames of environment opens.
    audit_rows = []
    for path in sorted(run.glob('sdk-imports.*.jsonl')):
        try:
            audit_rows.extend(rows(path))
        except (OSError, ValueError) as error:
            issue('audit_log', error=str(error))
    imports = [r for r in audit_rows if r.get('event') == 'sdk_exec']
    opens = [r for r in audit_rows if r.get('event') == 'environment_open']
    if not any(r.get('event') == 'audit_installed' for r in audit_rows) or not imports:
        issue('missing_sdk_audit')
    for entry in imports:
        origin = entry.get('path', '')
        rel = origin.removeprefix('/data/private_test/')
        if not origin.startswith('/data/private_test/zaic_tools/') or entry.get('allowed') is not True or input_manifest.get(rel) != entry.get('sha256'):
            issue('sdk_origin_or_hash', entry=entry)
    if not any(r.get('path') == '/data/private_test/zaic_tools/executor.py' for r in imports):
        issue('sdk_executor_not_observed')
    actual_opens = collections.Counter(r.get('path') for r in opens)
    expected_opens = collections.Counter(f'/data/private_test/private_test_environment/{rid}/state.json' for rid in expected_ids)
    if actual_opens != expected_opens or any(r.get('allowed') is not True for r in opens):
        issue('environment_access_counts', expected=dict(expected_opens), actual=dict(actual_opens))
    try:
        loading = read(diagnostic / 'loading.json')
        if loading.get('backend') != 'sm120' or loading.get('split') != 'private_test' or loading.get('seed') != 20261030 or not loading.get('all_models_load_seconds', 0) > 0:
            issue('model_loading_receipt', value=loading)
    except (OSError, ValueError, TypeError) as error:
        loading = None
        issue('model_loading_receipt', error=str(error))
    if tool_errors:
        warn('rejected_tool_calls', count=len(tool_errors))
    if schema_errors:
        warn('official_tool_schema_errors', count=len(schema_errors))
    missing_receipts = len(cases) - sum(status_counts.values())
    log = run / 'container.log'
    deadline_message = log.is_file() and 'K exceeded 30 seconds; no fabricated output or second ToolEnv' in log.read_text(encoding='utf8', errors='replace')
    # The original transport raises before writing a receipt on a hard poll
    # timeout. Report that explicit failure instead of calling it zero timeouts.
    unreceipted_timeout = int(deadline_message and missing_receipts > 0)
    def percentile(values, fraction):
        return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None
    report = {
        'structural_and_provenance_pass': not issues,
        'official_tool_schema_pass': not schema_errors,
        'status': 'BLOCKED / INVALID' if issues else 'GENERATED WITH WARNINGS' if warnings else 'READY FOR SUBMISSION',
        'expected': len(cases), 'processed': len(output), 'finished': status_counts['finished'],
        'step_limit_requests': status_counts['max_steps'], 'timeouts': status_counts['timeout'] + unreceipted_timeout,
        'unreceipted_deadline_failures': unreceipted_timeout,
        'failed_receipts': sum(n for s, n in status_counts.items() if s not in ('finished', 'max_steps')),
        'missing_receipts': missing_receipts, 'status_counts': dict(status_counts),
        'incomplete_request_ids': [r['id'] for r in per_request if r['status'] == 'not_completed'],
        'tool_calls': calls_total, 'tool_errors': tool_errors, 'official_tool_schema_errors': schema_errors,
        'issues': issues, 'warnings': warnings, 'per_request': per_request,
        'timing': {'requests_measured': len(times), 'mean_ms': sum(times) / len(times) if times else None,
                   'min_ms': min(times) if times else None, 'max_ms': max(times) if times else None,
                   'p50_ms': percentile(times, .5), 'p95_ms': percentile(times, .95),
                   'sum_dispatch_seconds': sum(dispatches)},
        'loading': loading, 'sdk_module_executions': len(imports), 'sdk_environment_opens': len(opens),
        'jsonl_sha256': sha(prediction_file) if prediction_file.is_file() else None,
        'semantic_score': None,
        'hash_provenance': 'Unchanged verified production code calls mounted SDK get_state_hash; prediction matches its receipt. No state replay or hidden-state inspection.',
    }
    return report
