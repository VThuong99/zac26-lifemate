import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validation import compare, references, exact


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.diag = self.root / 'diagnostics'; self.diag.mkdir()
        self.expected = [
            {'id': 'a', 'tool_calls': [{'name': 'banking.transfer', 'arguments': {'amount': 12, 'to': 'x'}}, {'name': 'sms.send', 'arguments': {'text': 'ok'}}], 'state_hash': 'hash-a', 'status': 'finished', 'error': None},
            {'id': 'b', 'tool_calls': [], 'state_hash': 'hash-b', 'status': 'max_steps', 'error': None},
        ]
        self.rows = [{k: copy.deepcopy(r[k]) for k in ('id', 'tool_calls', 'state_hash')} | {'time': 1234} for r in self.expected]
        for n, (r, pred) in enumerate(zip(self.expected, self.rows)):
            self.receipt(n, {'id': r['id'], 'index': n, 'status': r['status'], 'error': None, 'toolenv_instances': 1,
                             'prediction': {k: pred[k] for k in ('id', 'tool_calls', 'state_hash')}, 'dispatch_seconds': 1.234,
                             'events': [{'type': 'tool_result', 'action': call} for call in r['tool_calls']]})

    def tearDown(self): self.temp.cleanup()
    def receipt(self, n, row): (self.diag / f'{n:06d}.result.json').write_text(json.dumps(row))
    def run_compare(self):
        p = self.root / 'predictions.jsonl'
        p.write_text(''.join(json.dumps(r) + '\n' for r in self.rows))
        return compare(p, self.diag, self.expected)
    def kinds(self, report): return {x['kind'] for x in report['issues']}

    def test_valid_and_step_limit_is_not_dropped(self):
        r = self.run_compare(); self.assertTrue(r['parity_pass']); self.assertTrue(r['timing']['pass']); self.assertEqual(r['exact_cases'], 2)
        self.assertEqual(r['status_counts'], {'finished': 1, 'max_steps': 1})

    def test_missing_duplicate_unexpected_and_reordered(self):
        self.rows = [self.rows[1], self.rows[1], {'id': 'extra'}]
        r = self.run_compare()
        self.assertTrue({'missing_request', 'duplicate_request', 'unexpected_request', 'request_order_or_coverage'} <= self.kinds(r))
        self.assertFalse(r['parity_pass'])

    def test_call_order_and_earliest_divergence(self):
        self.rows[0]['tool_calls'].reverse()
        r = self.run_compare()
        self.assertEqual(r['first_divergence']['id'], 'a'); self.assertEqual(r['first_divergence']['call_index'], 0)
        self.assertEqual(len(r['all_action_divergences']), 2)

    def test_numeric_types_names_hashes(self):
        self.rows[0]['tool_calls'][0]['arguments']['amount'] = 12.0
        self.rows[0]['tool_calls'][1]['name'] = 'chat.send'
        self.rows[0]['state_hash'] = 'different'
        r = self.run_compare(); self.assertIn('state_hash', self.kinds(r)); self.assertEqual(len(r['all_action_divergences']), 2)
        self.assertFalse(exact(True, 1)); self.assertTrue(exact({'b': 2, 'a': 1}, {'a': 1, 'b': 2}))

    def test_missing_and_failed_receipt_not_ignored(self):
        (self.diag / '000001.result.json').unlink()
        rec = json.loads((self.diag / '000000.result.json').read_text()); rec.update(status='worker_error', error='failed')
        self.receipt(0, rec)
        r = self.run_compare(); self.assertTrue({'missing_receipt', 'failed_request', 'completion_status', 'completion_error'} <= self.kinds(r))

    def test_partial_failure_retains_all_expected_cases(self):
        self.rows = self.rows[:1]
        r = self.run_compare(); self.assertEqual(r['expected'], 2); self.assertIn('missing_request', self.kinds(r))

    def test_timing_independent_of_parity(self):
        self.rows[0]['time'] = 30000
        r = self.run_compare(); self.assertTrue(r['parity_pass']); self.assertFalse(r['timing']['pass'])
        self.rows[0]['time'] = 777
        rec = json.loads((self.diag / '000000.result.json').read_text()); rec['dispatch_seconds'] = .777
        self.receipt(0, rec)
        r = self.run_compare(); self.assertTrue(r['parity_pass']); self.assertTrue(r['timing']['pass'])

    def test_toolenv_count_and_actual_effect_log(self):
        rec = json.loads((self.diag / '000000.result.json').read_text()); rec['toolenv_instances'] = 2; rec['events'] = []
        self.receipt(0, rec)
        r = self.run_compare(); self.assertTrue({'toolenv_count', 'actual_call_log'} <= self.kinds(r))

    def test_malformed_input_is_reported(self):
        p = self.root / 'bad.jsonl'; p.write_text('{invalid}\n[]\n\n')
        r = compare(p, self.diag, self.expected); self.assertEqual(sum(x['kind'] == 'malformed_record' for x in r['issues']), 3)

    def test_nonfinite_and_duplicate_json_keys_are_malformed(self):
        p = self.root / 'bad.jsonl'; p.write_text('{"id":"a","time":NaN}\n{"id":"a","id":"b"}\n')
        r = compare(p, self.diag, self.expected)
        self.assertEqual(sum(x['kind'] == 'malformed_record' for x in r['issues']), 2)

    def test_duplicate_diagnostic_receipt(self):
        p = self.diag / '000000.result.json'; (self.diag / 'duplicate.result.json').write_text(p.read_text())
        self.assertIn('duplicate_receipt', self.kinds(self.run_compare()))

    def test_nonzero_tee_pipeline_retains_exit_code(self):
        result = subprocess.run(['bash', '-c', 'set -o pipefail; (exit 37) | tee /dev/null; r=("${PIPESTATUS[@]}"); exit "${r[0]}"'])
        self.assertEqual(result.returncode, 37)


class EvidenceTests(unittest.TestCase):
    def test_native_cli_and_notebook_against_original_frozen_k(self):
        _, refs = references()
        release = Path(__file__).resolve().parents[2] / 'lifemate-release-k-20261115/evidence'
        for folder, stem in [('public_replay', 'submission'), ('notebook_full', 'jupyter_submission')]:
            r = compare(release / folder / (stem + '.jsonl'), release / folder / (stem + '.diagnostics'), refs)
            self.assertTrue(r['parity_pass'], str(r['issues'])[:2000]); self.assertTrue(r['timing']['pass'])
            self.assertEqual(r['exact_cases'], 634)


if __name__ == '__main__': unittest.main()
