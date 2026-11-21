"""CPU-only tests for partial-evidence classification; no model/SDK execution."""
import copy
import unittest
from inspect_failure import prefix_assessment


class PrefixAssessment(unittest.TestCase):
    def setUp(self):
        self.cases = [{'id': 'fixture_1'}, {'id': 'fixture_2'}]
        self.output = [{'id': 'fixture_1'}]
        self.audit = [{'event': 'environment_open', 'allowed': True,
                       'path': '/data/private_test/private_test_environment/fixture_1/state.json'}]
        self.analysis = {'issues': [{'kind': 'incomplete_output'}, {'kind': 'id_coverage_or_order'},
                                   {'kind': 'environment_access_counts'},
                                   {'kind': 'failed_request', 'id': 'fixture_2'}],
                         'official_tool_schema_errors': [], 'tool_errors': [],
                         'per_request': [{'id': 'fixture_1', 'status': 'finished'},
                                         {'id': 'fixture_2', 'status': 'inference_error'}]}

    def assess(self):
        return prefix_assessment(self.analysis, self.output, self.cases, self.audit)

    def test_valid_fragment_is_never_complete_submission(self):
        result = self.assess()
        self.assertTrue(result['structure_and_sdk_provenance_pass'])
        self.assertFalse(result['complete_submission'])

    def test_earlier_tool_error_is_not_hidden_by_batch_failure(self):
        self.analysis['issues'].append({'kind': 'failed_request', 'id': 'fixture_1', 'status': 'tool_error'})
        self.assertFalse(self.assess()['structure_and_sdk_provenance_pass'])

    def test_sdk_origin_failure_remains_blocking(self):
        self.analysis['issues'].append({'kind': 'sdk_origin_or_hash'})
        self.assertFalse(self.assess()['structure_and_sdk_provenance_pass'])

    def test_duplicate_environment_open_remains_blocking(self):
        self.audit.append(copy.deepcopy(self.audit[0]))
        self.assertFalse(self.assess()['structure_and_sdk_provenance_pass'])

    def test_wrong_prefix_order_remains_blocking(self):
        self.output[0]['id'] = 'fixture_2'
        self.assertFalse(self.assess()['structure_and_sdk_provenance_pass'])

    def test_unrelated_future_schema_error_not_attributed_to_prefix(self):
        self.analysis['official_tool_schema_errors'] = [{'id': 'fixture_2'}]
        self.assertEqual(self.assess()['official_tool_schema_errors'], [])


if __name__ == '__main__':
    unittest.main()
