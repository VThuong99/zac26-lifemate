"""Synthetic checks of local metrics; no claim of official evaluator parity."""

import json
from pathlib import Path
import tempfile
import unittest

from lifemate.evaluation import evaluate_f1, score_sample
from lifemate.schema_validation import format_ok, schema_error
from lifemate.tool_call_matcher import count_matched_calls, fuzzy_token_f1, strict_equal


class EvaluationTests(unittest.TestCase):
    call = {"name": "demo.set", "arguments": {"on": True}}

    def test_correct_calls_with_wrong_state_score_zero(self):
        result = score_sample([self.call], [self.call], False, {})
        self.assertEqual(result["f1"], 1.0)
        self.assertEqual(result["score"], 0.0)

    def test_duplicate_predictions_cannot_reuse_one_gold_match(self):
        result = score_sample([self.call], [self.call, self.call], True, {})
        self.assertEqual(result["matched_calls"], 1)
        self.assertAlmostEqual(result["score"], 2 / 3)

    def test_matching_ignores_order_but_preserves_multiplicity(self):
        other = {"name": "demo.read", "arguments": {}}
        self.assertEqual(count_matched_calls([self.call, other], [other, self.call], {}), 2)
        self.assertEqual(count_matched_calls([self.call, self.call], [self.call], {}), 1)

    def test_json_types_are_not_coerced(self):
        self.assertFalse(strict_equal(True, 1))
        self.assertFalse(strict_equal(1, 1.0))
        self.assertFalse(strict_equal({"v": [True]}, {"v": [1]}))

    def test_fuzzy_matching_normalizes_vietnamese_unicode(self):
        self.assertEqual(fuzzy_token_f1("ĐÈN sa\u0301ng", "đèn sáng"), 1.0)
        self.assertEqual(fuzzy_token_f1("a a b", "a b b"), 2 / 3)

    def test_no_gold_special_case_and_missing_prediction(self):
        self.assertEqual(score_sample([], [], False, {})["score"], 1.0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "gold.jsonl").write_text(json.dumps({"id": "synthetic", "label": {"tool_calls": []}}) + "\n")
            (root / "pred.jsonl").write_text("")
            (root / "hashes.json").write_text('{"synthetic":"mock-hash"}')
            (root / "catalog.json").write_text('{"apps":[]}')
            result = evaluate_f1(root / "gold.jsonl", root / "pred.jsonl", root / "hashes.json", root / "catalog.json")
            self.assertEqual(result["missing_predictions"], 1)
            self.assertEqual(result["score_100"], 0)


class SchemaTests(unittest.TestCase):
    def test_numeric_bool_and_nonfinite_rejected(self):
        catalog = [{"name": "demo.value", "parameters": {"properties": {"value": {"type": "number"}}}}]
        for value in (True, float("inf"), float("nan")):
            with self.subTest(value=value):
                self.assertIsNotNone(schema_error("demo.value", {"value": value}, catalog))

    def test_calendar_date_and_hour_boundaries(self):
        self.assertTrue(format_ok("2024-02-29", "date"))
        self.assertFalse(format_ok("2023-02-29", "date"))
        self.assertTrue(format_ok("23:59", "time"))
        self.assertFalse(format_ok("24:00", "time"))

    def test_required_and_installed_tool_checks(self):
        catalog = [{"name": "demo.value", "parameters": {"required": ["value"]}}]
        self.assertIsNotNone(schema_error("demo.value", {}, catalog))
        self.assertIsNotNone(schema_error("demo.value", {"value": 1}, catalog, allowed=set()))
        self.assertIsNone(schema_error("demo.value", {"value": 1}, catalog, allowed={"demo.value"}))
