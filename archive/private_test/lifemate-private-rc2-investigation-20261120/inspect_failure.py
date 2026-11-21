#!/usr/bin/env python3
"""Read-only, standard-library host audit. No Docker, GPU, SDK execution or writes.

Inspects only official input JSONL, public SDK schema source, and retained run
evidence. Never opens an environment/state file or emits prediction rows.
"""
import argparse
import collections
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
WORKSPACE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE / 'lifemate-private-rc2-host-20261120'))
import check_results as checks
import run_private_test as host


def prefix_assessment(analysis, output, cases, audit):
    """Assess an evidence fragment separately from the incomplete whole run."""
    ids = [row['id'] for row in cases[:len(output)]]
    wanted = set(ids)
    # These whole-run issues do not invalidate already completed rows. They are
    # retained in whole_run_issue_counts; this is NOT a submission acceptance.
    coverage = {'incomplete_output', 'id_coverage_or_order', 'receipt_coverage',
                'event_file_coverage', 'environment_access_counts'}
    issues = [entry for entry in analysis['issues'] if entry['kind'] not in coverage
              and ('id' not in entry or entry['id'] in wanted)]
    if [row.get('id') for row in output] != ids:
        issues.append({'kind': 'prefix_id_order'})
    opens = [e for e in audit if e.get('event') == 'environment_open']
    counts = collections.Counter(e.get('path') for e in opens)
    for rid in ids:
        path = f'/data/private_test/private_test_environment/{rid}/state.json'
        if counts[path] != 1:
            issues.append({'kind': 'prefix_environment_count', 'id': rid, 'actual': counts[path]})
    if any(e.get('allowed') is not True for e in opens):
        issues.append({'kind': 'denied_environment_access_in_run'})
    errors = [e for e in analysis['official_tool_schema_errors'] if e['id'] in wanted]
    tool_errors = [e for e in analysis['tool_errors'] if e['id'] in wanted]
    steps = [e['id'] for e in analysis['per_request'] if e['id'] in wanted and e['status'] == 'max_steps']
    return {'rows': len(output), 'first_id': ids[0] if ids else None, 'last_id': ids[-1] if ids else None,
            'structure_and_sdk_provenance_pass': not issues, 'issues': issues,
            'official_tool_schema_errors': errors, 'rejected_tool_calls': tool_errors,
            'step_limit_ids': steps, 'complete_submission': False,
            'semantic_correctness_or_score_established': False}


def select_run(explicit, results, expected):
    if explicit:
        return explicit.expanduser().resolve(strict=True)
    matches = []
    for path in sorted(results.expanduser().glob('*/REPORT.json')):
        try:
            report = checks.read(path)
            partial = path.parent / 'inference/submission.jsonl.partial'
            if report.get('mode') == 'full' and partial.is_file() and len(checks.rows(partial)) == expected:
                matches.append(path.parent.resolve())
        except (ValueError, OSError):
            continue
    host.require(len(matches) == 1,
                 'Expected one matching failed full run; use --run explicitly. Candidates: ' + repr([str(p) for p in matches]))
    return matches[0]


def inspect(run, expected_rows, include_first_prompt=False):
    report = checks.read(run / 'REPORT.json')
    host.require(report.get('mode') == 'full', 'Select the failed full run')
    host.require(report.get('archive_sha256') == host.ARCHIVE_SHA and report.get('zip_sha256') == host.ZIP_SHA,
                 'Run artifact identity differs from submitted RC2 / Private Test')
    # The recorded workspace is a HOST path; no development-container mapping.
    workspace = Path(report['workspace']).resolve(strict=True)
    package, build, _, _ = host.load_verifier(workspace)
    host.require(checks.sha(WORKSPACE / 'lifemate-private-rc2-host-20261120/check_results.py')
                 == report['workflow_sha256']['check_results.py'], 'Original output validator changed')
    sealed = report.get('evidence_sha256', {})
    host.require(bool(sealed), 'Missing sealed run evidence')
    changed = []
    for rel, digest in sealed.items():
        path = (run / rel).resolve()
        host.require(path.is_relative_to(run) and 'dataset' not in path.relative_to(run).parts
                     and 'private_test_environment' not in path.parts and path.name != 'state.json',
                     'Unsafe evidence path: ' + rel)
        if not path.is_file() or checks.sha(path) != digest:
            changed.append(rel)
    host.require(not changed, 'Evidence changed since REPORT.json: ' + repr(changed))
    split = run / 'dataset/private_test'
    host.require(checks.sha(split / 'private_test.jsonl') == host.INPUT_SHA, 'Official input JSONL changed')
    host.require(checks.sha(split / 'private_test_tools_catalog.json') == host.CATALOG_SHA, 'Tool catalog changed')
    manifest = checks.read(run / 'input-manifest.json')
    for rel, digest in manifest.items():
        path = (split / rel).resolve()
        host.require(path.is_relative_to(split.resolve()) and 'private_test_environment' not in path.parts
                     and path.name != 'state.json', 'Unsafe input manifest member: ' + rel)
        host.require(checks.sha(path) == digest, 'Input/SDK/audio bytes changed: ' + rel)
    cases = checks.rows(split / 'private_test.jsonl')
    stage = run / 'inference'
    partial = stage / 'submission.jsonl.partial'
    host.require(not (stage / 'submission.jsonl').exists(), 'Expected a failed run with only .partial output')
    output = checks.rows(partial)
    host.require(len(output) == expected_rows < len(cases), 'Unexpected partial row count')
    host.require([r.get('id') for r in output] == [c['id'] for c in cases[:expected_rows]], 'Partial is not the official ordered prefix')
    host.require('inference/submission.jsonl.partial' in sealed, 'Partial output was not sealed')
    analysis = checks.analyze(stage, cases, split, manifest)
    identity = host.verify_loaded(checks.read(run / 'image-inspect.json'), package, build,
                                  checks.read(run / 'archive-identity.json'))
    plan = checks.read(run / 'plan.json')
    expected_command = ['/bin/bash', '/code/predict.sh', '--data-root', '/data', '--split',
                        'private_test', '--output', '/result/submission.jsonl']
    for name in ('container-created.json', 'container-final.json'):
        host.verify_container(checks.read(stage / name), identity, split, stage, run / 'harness',
                              expected_command, report['gpu']['uuid'], f"{plan['uid']}:{plan['gid']}",
                              cuda_compat=report.get('cuda_compat', False))
    audit = [entry for p in stage.glob('sdk-imports.*.jsonl') for entry in checks.rows(p)]
    prefix = prefix_assessment(analysis, output, cases, audit)
    prefix['sha256'] = checks.sha(partial)
    candidate = cases[expected_rows]
    receipt_path = stage / f'submission.diagnostics/{expected_rows:06d}.result.json'
    host.require(str(receipt_path.relative_to(run)) in sealed, 'Failed receipt was not sealed or is missing')
    receipt = checks.read(receipt_path)
    host.require(receipt.get('id') == candidate['id'] and receipt.get('index') == expected_rows, 'Failure receipt ID/index mismatch')
    events = receipt.get('events', [])
    requests = receipt.get('requests', [])
    error = receipt.get('error') or ''
    token_match = re.search(r'request \((\d+) tokens\).*?context size \((\d+) tokens\)', error, re.S)
    prediction = receipt.get('prediction')
    calls = [{'name': e['action']['name'], 'arguments': e['action']['arguments']}
             for e in events if e.get('type') == 'tool_result']
    events_path = receipt_path.with_name(f'{expected_rows:06d}.events.jsonl')
    event_match = events_path.is_file() and checks.exact(checks.rows(events_path), events)
    failure = {'id': candidate['id'], 'zero_based_index': expected_rows, 'ordinal': expected_rows + 1,
               'receipt_sha256': checks.sha(receipt_path), 'status': receipt.get('status'), 'error': error,
               'dispatch_seconds': receipt.get('dispatch_seconds'), 'toolenv_instances': receipt.get('toolenv_instances'),
               'reported_prompt_tokens': int(token_match[1]) if token_match else None,
               'reported_context_limit': int(token_match[2]) if token_match else None,
               'successful_llm_requests_before_failure': len(requests), 'current_request_tool_calls': len(calls),
               'events_match_receipt': event_match, 'event_types': dict(collections.Counter(e.get('type') for e in events)),
               'sdk_prediction_recorded': isinstance(prediction, dict),
               'recorded_calls_match_events': isinstance(prediction, dict) and checks.exact(prediction.get('tool_calls'), calls),
               'state_hash_recorded': isinstance(prediction, dict) and isinstance(prediction.get('state_hash'), str)
                   and bool(re.fullmatch('[0-9a-f]{64}', prediction['state_hash'])),
               'history_turns': len(candidate['history']),
               'history_user_audio_clips': sum(t.get('role') == 'user' and 'audio' in t for t in candidate['history']),
               'history_tool_results': sum(len(t.get('tool_results', [])) for t in candidate['history']),
               'asr_transcripts_recorded': len(receipt.get('transcripts', [])),
               'successful_prompt_token_counts': [r.get('prompt_tokens') for r in requests],
               'failed_http_payload_saved_by_frozen_worker': False,
               'first_planner_call_overflow': bool(token_match) and not requests and not calls}
    if requests:
        payload = json.loads(requests[-1]['request']['messages'][1]['content'])
        failure['last_successful_prompt_component_chars'] = {k: len(json.dumps(v, ensure_ascii=False)) for k, v in payload.items()}
    elif failure['first_planner_call_overflow']:
        from reconstruct_prompt import first_messages
        messages = first_messages(candidate, receipt, workspace / 'lifemate-final-20261116-rc2/overlay/runtime/lifemate', split)
        payload = json.loads(messages[1]['content'])
        failure['reconstructed_first_prompt_component_chars'] = {k: len(json.dumps(v, ensure_ascii=False)) for k, v in payload.items()}
        failure['reconstruction_note'] = 'Pure frozen prompt functions plus saved ASR/acoustic evidence; failed HTTP wire payload was not retained.'
        if include_first_prompt:
            failure['reconstructed_first_messages'] = messages
    loading = checks.read(stage / 'submission.diagnostics/loading.json')
    untouched = cases[expected_rows + 1:]
    opens = collections.Counter(e.get('path') for e in audit if e.get('event') == 'environment_open')
    return {'run': str(run), 'mode': 'READ_ONLY_CPU_AUDIT', 'gpu_inference_started': False,
            'evidence_seal_verified': True, 'input_sdk_audio_hashes_verified': True,
            'image_identity': identity, 'gpu': report.get('gpu'), 'cuda_compat': report.get('cuda_compat'),
            'actual_llama_command': loading['command'], 'prefix': prefix, 'failure': failure,
            'untouched_requests': len(untouched), 'untouched_first_id': untouched[0]['id'] if untouched else None,
            'unexpected_environment_opens_for_untouched_ids': [c['id'] for c in untouched
                if opens[f"/data/private_test/private_test_environment/{c['id']}/state.json"]],
            'failed_id_environment_opens': opens[f"/data/private_test/private_test_environment/{candidate['id']}/state.json"],
            'whole_run_issue_counts': dict(collections.Counter(e['kind'] for e in analysis['issues'])),
            'submission_status': 'INCOMPLETE / NOT VALIDATED FOR SUBMISSION',
            'limitation': 'Authentic failure receipts do not establish successful completion or organizer permission to change batch error handling.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, help='Exact failed HOST run directory; auto-select only when unique')
    parser.add_argument('--results-dir', type=Path, default=Path.home() / 'lifemate-private-rc2-results')
    parser.add_argument('--expected-rows', type=int, default=323)
    parser.add_argument('--include-first-prompt', action='store_true', help='Include reconstructed messages only if the first planner call failed')
    args = parser.parse_args()
    run = select_run(args.run, args.results_dir, args.expected_rows)
    print(json.dumps(inspect(run, args.expected_rows, args.include_first_prompt), ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
