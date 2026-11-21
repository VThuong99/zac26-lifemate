"""CPU-only validation of genuine RC2 receipts; never constructs ToolEnv."""
import collections
import json
import math
from pathlib import Path
import re

from check_results import exact, read, rows


def require(ok, message):
    if not ok:
        raise ValueError(message)


def check_loading(loading):
    prefix = '/code/runtime/lifemate/experiments/continuous_improvement/'
    command = loading.get('command', [])
    require(len(command) > 6 and str(command[6]).isdigit() and 0 < int(command[6]) < 65536,
            'Invalid original llama-server port')
    expected = ['/code/native/sm120/bin/llama-server', '--model', prefix + 'p19_champion_q8_v1/p19_q8.gguf',
                '--host', '127.0.0.1', '--port', command[6], '--ctx-size', '8192', '--n-gpu-layers', '99',
                '--parallel', '1', '--threads', '8', '--batch-size', '512', '--ubatch-size', '512',
                '--flash-attn', 'on', '--seed', '20261030', '--jinja', '--lora-scaled',
                prefix + 'dpo_finish_overlay_v1/adapter_f32.gguf:0,' +
                prefix + 'conditional_terminal_preference_sft_v1/K/adapter_f32.gguf:0']
    require(command == expected, 'Server command differs from submitted 8192-token RC2')
    require(loading.get('backend') == 'sm120' and loading.get('split') == 'private_test'
            and loading.get('seed') == 20261030 and loading.get('all_models_load_seconds', 0) > 0,
            'Invalid original model-loading receipt')


def validate_receipt(receipt, case, index, events, schema_validate, catalog, saved_row=None):
    rid = case['id']
    require(receipt.get('id') == rid and type(receipt.get('index')) is int and receipt['index'] == index,
            f'{rid}: receipt ID/index mismatch')
    require(type(receipt.get('toolenv_instances')) is int and receipt['toolenv_instances'] == 1,
            f'{rid}: exactly one ToolEnv is required')
    seconds = receipt.get('dispatch_seconds')
    require(type(seconds) in (int, float) and math.isfinite(seconds) and 0 <= seconds < 30,
            f'{rid}: missing or exceeded 30-second runtime')
    status = receipt.get('status')
    require(status in ('finished', 'max_steps', 'tool_error', 'inference_error',
                       'calendar_effect_unverified', 'binding_effect_unverified'),
            f'{rid}: unusable receipt status {status!r}')
    require(status != 'inference_error' or isinstance(receipt.get('error'), str) and bool(receipt['error']),
            f'{rid}: inference failure is missing its error evidence')
    require(status not in ('finished', 'max_steps') or not receipt.get('error'),
            f'{rid}: success status contradicts recorded error')
    prediction = receipt.get('prediction')
    require(isinstance(prediction, dict) and set(prediction) == {'id', 'tool_calls', 'state_hash'}
            and prediction['id'] == rid, f'{rid}: missing genuine SDK prediction')
    require(isinstance(prediction['state_hash'], str) and re.fullmatch('[0-9a-f]{64}', prediction['state_hash']),
            f'{rid}: invalid SDK hash format')
    calls = prediction['tool_calls']
    require(isinstance(calls, list) and all(isinstance(c, dict) and set(c) == {'name', 'arguments'}
            and isinstance(c['name'], str) and isinstance(c['arguments'], dict) for c in calls),
            f'{rid}: invalid SDK call structure')
    require(isinstance(events, list) and exact(events, receipt.get('events')), f'{rid}: event file differs from receipt')
    allowed = {name for app in case['context']['installed_apps'].values() for name in app.get('tools', [])}
    allowed.add('sys.ask_missing_info')
    actual, rejected = [], []
    for event in events:
        if event.get('type') != 'tool_result':
            continue
        action, result = event.get('action'), event.get('result')
        require(isinstance(action, dict) and action.get('type') == 'call' and isinstance(action.get('name'), str)
                and isinstance(action.get('arguments'), dict) and isinstance(result, dict)
                and type(result.get('ok')) is bool, f'{rid}: malformed tool event')
        call = {'name': action['name'], 'arguments': action['arguments']}
        checked = schema_validate([call], catalog, allowed)[0]
        if checked['ok']:
            # Frozen Controller executes env.call only after env.validate succeeds.
            actual.append(call)
        else:
            require(result.get('ok') is False and result.get('error') == checked['error'],
                    f'{rid}: rejected proposal lacks matching official validation evidence')
            rejected.append({'action': call, 'result': result})
    require(exact(actual, calls), f'{rid}: SDK calls differ from executed events (validation-only proposals excluded)')
    schema = schema_validate(calls, catalog, allowed)
    require(all(x['ok'] is True for x in schema), f'{rid}: official tool schema validation failed')
    row = {**prediction, 'time': int(seconds * 1000)}
    if saved_row is not None:
        require(set(saved_row) == {'id', 'tool_calls', 'state_hash', 'time'}
                and type(saved_row.get('time')) is int and exact(row, saved_row),
                f'{rid}: saved prediction differs from SDK receipt/timing')
    return row, {'id': rid, 'index': index, 'status': status, 'error': receipt.get('error'),
                 'inference_failure': status == 'inference_error',
                 'execution_failure': status not in ('finished', 'max_steps'),
                 'context_overflow': 'exceed_context_size_error' in str(receipt.get('error')),
                 'rejected_proposals': rejected, 'official_tool_schema_pass': True,
                 'dispatch_seconds': seconds}


def raw_predictions(stage):
    paths = [p for p in (stage / 'submission.jsonl', stage / 'submission.jsonl.partial') if p.is_file()]
    require(len(paths) <= 1, 'Both partial and final stage output exist')
    result = {}
    if paths:
        for line in paths[0].read_bytes().splitlines(keepends=True):
            require(line.endswith(b'\n'), 'Truncated JSONL line; preserve evidence for review')
            from check_results import parse
            value = parse(line.decode('utf8'))
            require(isinstance(value, dict) and isinstance(value.get('id'), str), 'Malformed JSONL row')
            require(value['id'] not in result, 'Duplicate output ID')
            result[value['id']] = (value, line)
    return result


def collect_stage(stage, cases, indices, manifest, schema_validate, catalog):
    """Validate a stopped stage. Return verified rows and all attempted indices."""
    indices = set(indices)
    allowed_ids = {cases[i]['id']: i for i in indices}
    saved = raw_predictions(stage)
    require(set(saved) <= set(allowed_ids), 'Output contains an unplanned ID')
    require([allowed_ids[rid] for rid in saved] == sorted(allowed_ids[rid] for rid in saved),
            'Source JSONL order differs from official request order')
    diagnostic = stage / 'submission.diagnostics'
    receipt_paths = sorted(diagnostic.glob('*.result.json'))
    audit = [r for p in stage.glob('sdk-imports.*.jsonl') for r in rows(p)]
    imports = [r for r in audit if r.get('event') == 'sdk_exec']
    opens = [r for r in audit if r.get('event') == 'environment_open']
    if receipt_paths or opens:
        require(any(r.get('event') == 'audit_installed' for r in audit) and imports, 'Missing SDK audit')
        require(any(r.get('path') == '/data/private_test/zaic_tools/executor.py' for r in imports), 'SDK executor not observed')
        check_loading(read(diagnostic / 'loading.json'))
        require(re.search(r'\bn_ctx_slot\s*=\s*8192\b', (diagnostic / 'llama-server.log').read_text(errors='replace')),
                'Server log does not confirm an actual 8192-token slot')
    for entry in imports:
        path = entry.get('path', '')
        rel = path.removeprefix('/data/private_test/')
        require(path.startswith('/data/private_test/zaic_tools/') and entry.get('allowed') is True
                and manifest.get(rel) == entry.get('sha256'), 'SDK origin/hash mismatch')
    counts = collections.Counter()
    attempted = set()
    for entry in opens:
        path = entry.get('path', '')
        match = re.fullmatch(r'/data/private_test/private_test_environment/(private_[0-9]{4})/state.json', path)
        require(match and match[1] in allowed_ids and entry.get('allowed') is True, 'Unexpected or denied environment access')
        counts[match[1]] += 1
        require(counts[match[1]] == 1, 'Multiple ToolEnv opens for ' + match[1])
        attempted.add(allowed_ids[match[1]])
    attempts_file = stage / 'attempts.jsonl'
    if attempts_file.exists():
        recorded = rows(attempts_file)
        seen = set()
        for entry in recorded:
            index = entry.get('index')
            require(type(index) is int and index in indices and entry.get('id') == cases[index]['id'] and index not in seen,
                    'Invalid or duplicate attempt marker')
            seen.add(index)
        require(attempted <= seen, 'SDK access without an attempt marker')
        attempted.update(seen)
    for p in diagnostic.glob('*.events.jsonl'):
        require(re.fullmatch(r'[0-9]{6}\.events\.jsonl', p.name), 'Unexpected event filename')
        index = int(p.name[:6])
        require(index in indices, 'Unplanned event file')
        attempted.add(index)
    verified, blocked = {}, []
    receipt_ids = set()
    for path in receipt_paths:
        require(re.fullmatch(r'[0-9]{6}\.result\.json', path.name), 'Unexpected receipt filename')
        index = int(path.name[:6])
        require(index in indices, 'Unplanned receipt')
        rid = cases[index]['id']
        receipt_ids.add(rid)
        attempted.add(index)
        receipt = read(path)
        try:
            require(counts[rid] == 1, f'{rid}: missing SDK environment-open evidence')
            row, detail = validate_receipt(receipt, cases[index], index,
                rows(diagnostic / f'{index:06d}.events.jsonl'), schema_validate, catalog,
                saved[rid][0] if rid in saved else None)
            raw = saved[rid][1] if rid in saved else (json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf8')
            verified[index] = {'row': row, 'raw': raw, 'detail': detail, 'receipt': str(path),
                               'source': str(stage.parent), 'copied_existing_row': rid in saved}
        except (ValueError, OSError, KeyError, TypeError) as error:
            blocked.append({'id': rid, 'index': index, 'reason': str(error), 'status': receipt.get('status')})
    require(set(saved) <= receipt_ids, 'Saved output has no matching receipt')
    for index in sorted(attempted - set(verified) - {x['index'] for x in blocked}):
        blocked.append({'id': cases[index]['id'], 'index': index, 'reason': 'Attempt has no usable SDK receipt'})
    return verified, attempted, blocked


def merge_inventory(sources):
    verified, attempted, blocked = {}, set(), []
    for rows_by_index, tried, errors in sources:
        require(not (attempted & tried), 'A request was attempted in multiple source runs; refusing automatic selection')
        verified.update(rows_by_index)
        attempted.update(tried)
        blocked.extend(errors)
    return verified, attempted, blocked
