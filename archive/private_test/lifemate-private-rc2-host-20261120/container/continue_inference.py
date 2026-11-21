"""Mounted batch driver. Imports unchanged /code/predict.py; no model policy patches."""
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
from check_results import official_validator, read, rows, sha
from recovery_checks import check_loading, require, validate_receipt


def append(stream, value):
    stream.write(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    stream.flush()
    os.fsync(stream.fileno())


def run_selected(runtime, cases, indices, stage, schema_validate, catalog):
    """Continue only with a live original worker; never retry an attempted item."""
    diagnostic = stage / 'submission.diagnostics'
    complete = True
    with (stage / 'attempts.jsonl').open('x') as attempts, (stage / 'outcomes.jsonl').open('x') as outcomes, \
            (stage / 'submission.jsonl.partial').open('x', encoding='utf8') as output:
        for index in indices:
            item = cases[index]
            append(attempts, {'index': index, 'id': item['id']})
            raised = None
            returned = None
            try:
                returned = runtime.infer(item, index)
            except (RuntimeError, TimeoutError, OSError, EOFError) as error:
                raised = repr(error)
            path = diagnostic / f'{index:06d}.result.json'
            # A dead worker or absent receipt cannot supply an authentic row.
            if not path.is_file():
                append(outcomes, {'index': index, 'id': item['id'], 'usable': False, 'error': raised,
                                  'reason': 'No SDK receipt; no prediction fabricated'})
                raise RuntimeError(f'{item["id"]}: no receipt; rerun the HOST command to process only untouched requests')
            receipt = read(path)
            try:
                row, detail = validate_receipt(receipt, item, index,
                    rows(diagnostic / f'{index:06d}.events.jsonl'), schema_validate, catalog, returned)
                append(output, row)
                append(outcomes, {**detail, 'usable': True, 'transport_exception': raised})
                print(json.dumps({'id': item['id'], 'status': detail['status'],
                                  'recorded_failure': detail['execution_failure'], 'time_ms': row['time']}), flush=True)
            except (ValueError, OSError, KeyError, TypeError) as error:
                complete = False
                append(outcomes, {'index': index, 'id': item['id'], 'usable': False,
                                  'status': receipt.get('status'), 'error': str(error)})
            require(runtime.proc is not None and runtime.proc.is_alive(), 'Original worker stopped; no automatic retry')
    if complete:
        (stage / 'submission.jsonl.partial').rename(stage / 'submission.jsonl')
    return complete


def main():
    require('sitecustomize' in sys.modules, 'SDK observer missing')
    sys.path.insert(0, '/code')
    import predict
    require(Path(predict.__file__).resolve() == Path('/code/predict.py'), 'Wrong RC2 runtime import')
    plan = read('/validation/continuation-plan.json')
    split = Path('/data/private_test')
    require(sha(split / 'private_test.jsonl') == plan['input_sha256'], 'Official input changed')
    cases = predict.read_cases('/data', 'private_test')
    indices = plan['indices']
    require(indices == sorted(set(indices)) and all(type(i) is int and 0 <= i < len(cases) for i in indices), 'Invalid selected indices')
    require([cases[i]['id'] for i in indices] == plan['ids'], 'Selection ID mismatch')
    catalog = read(split / 'private_test_tools_catalog.json')
    validator = official_validator(split)
    stage = Path('/result')
    with predict.KRuntime('/data', 'private_test', stage / 'submission.diagnostics') as runtime:
        check_loading(read(stage / 'submission.diagnostics/loading.json'))
        complete = run_selected(runtime, cases, indices, stage, validator, catalog)
    return 0 if complete else 2


if __name__ == '__main__':
    raise SystemExit(main())
