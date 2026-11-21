#!/usr/bin/env python3
"""One-time evidence extraction; reads saved K records, never executes inference."""
import collections
import json
from pathlib import Path
from validation import HERE, sha, read_json, read_rows, write_json, exact

WORKSPACE = HERE.parent
SOURCE = WORKSPACE / 'lifemate'
RELEASE = WORKSPACE / 'lifemate-release-k-20261115'
PINNED_K = 'cf3a5a654fdfb59f0e8ddb385319ed6c74b3cb8595c6072456d9f64e4e777898'
PINNED_INPUT = '6274f4ff32ab03c33350029a0672a67884209b7d97f66e80181e446dd955f604'

def main():
    destination = HERE / 'reference'
    if any(destination.iterdir()):
        raise RuntimeError('Reference directory is nonempty; refusing to overwrite evidence')
    baseline = SOURCE / 'submissions/submission_K.jsonl'
    inputs = SOURCE / 'public_test/public_test.jsonl'
    assert sha(baseline) == PINNED_K and sha(inputs) == PINNED_INPUT
    rows = read_rows(baseline)
    assert len(rows) == 634 and [r['id'] for r in rows] == [r['id'] for r in read_rows(inputs)]
    provenance = {str(p.relative_to(WORKSPACE)): sha(p) for p in [baseline, inputs]}
    extracted = []
    for index, row in enumerate(rows):
        p = SOURCE / f"submissions/challenger_public_run/K/results/{index:04d}-{row['id']}.json"
        record = read_json(p)
        assert record['index'] == index and record['id'] == row['id'] and exact(record['prediction'], row)
        emitted = [{'name': e['action']['name'], 'arguments': e['action']['arguments']}
                   for e in record['events'] if e.get('type') == 'tool_result']
        assert exact(emitted, row['tool_calls'])
        provenance[str(p.relative_to(WORKSPACE))] = sha(p)
        extracted.append({**row, 'status': record['status'], 'error': record['error']})
    validations = {}
    for output, diagnostics in [('public_replay/submission', 'public_replay/submission'), ('notebook_full/jupyter_submission', 'notebook_full/jupyter_submission')]:
        p = RELEASE / ('evidence/' + output + '.jsonl')
        actual = read_rows(p)
        assert len(actual) == len(rows)
        for index, (ref, a) in enumerate(zip(extracted, actual)):
            assert exact({k: a[k] for k in ('id', 'tool_calls', 'state_hash')}, rows[index])
            r = read_json(RELEASE / f'evidence/{diagnostics}.diagnostics/{index:06d}.result.json')
            assert r['status'] == ref['status'] and r['error'] == ref['error']
        validations[output] = {'records': len(actual), 'sha256': sha(p), 'exact_original_trajectories_and_statuses': True}
    with (destination / 'frozen_k.jsonl').open('x') as f:
        for row in extracted: f.write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')
    audio = SOURCE / 'submissions/challenger_public_run/audio_sha256.json'
    with (destination / 'audio_sha256.json').open('xb') as f: f.write(audio.read_bytes())
    provenance[str(audio.relative_to(WORKSPACE))] = sha(audio)
    split = SOURCE / 'public_test'
    input_files = [split / 'public_test.jsonl', split / 'public_test_tools_catalog.json', *sorted((split / 'zaic_tools').rglob('*.py'))]
    manifest = {
        'authority': 'Original frozen K predictions and original per-request result receipts; native release replays only corroborate.',
        'baseline': str(baseline.relative_to(WORKSPACE)), 'baseline_sha256': PINNED_K,
        'original_receipts': 'lifemate/submissions/challenger_public_run/K/results/{index:04d}-{id}.json',
        'release_source_files': {str(p.relative_to(RELEASE)): sha(p) for p in [RELEASE / 'source/predict.py', RELEASE / 'source/predict_notebook.ipynb']},
        'records': len(rows), 'tool_calls': sum(len(r['tool_calls']) for r in rows),
        'status_counts': dict(collections.Counter(r['status'] for r in extracted)),
        'source_files': provenance, 'native_corroboration': validations,
        'reference_files': {n: sha(destination / n) for n in ['frozen_k.jsonl', 'audio_sha256.json']},
        'input_files': {str(p.relative_to(split)): sha(p) for p in input_files},
        'timing_equality_required': False,
        'scope': 'Local validation evidence only. Never mounted into inference containers. No ground-truth correctness claim.',
    }
    write_json(destination / 'manifest.json', manifest)
    print(json.dumps({k: manifest[k] for k in ['baseline_sha256', 'records', 'tool_calls', 'status_counts', 'native_corroboration']}, indent=2))

if __name__ == '__main__': main()
