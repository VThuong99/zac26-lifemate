"""Behavioral contracts of the real planner/controller using synthetic tools."""

import copy
import json
import unittest

from lifemate.agent import Agent
from lifemate.controller import Controller
from lifemate.decision_parser import parse_decision
from lifemate.demo import MockToolEnv, run_demo


class ScriptedPlanner:
    def __init__(self, actions):
        self.actions = iter(actions)
        self.histories = []

    def next_action(self, text, context, history, **kwargs):
        self.histories.append(copy.deepcopy(history))
        return next(self.actions)


def call(name="demo.list_lights", **arguments):
    return {"type": "call", "name": name, "arguments": arguments}


class ParserTests(unittest.TestCase):
    def test_valid_call_and_finish(self):
        for action in (call(), {"type": "finish"}):
            self.assertEqual(parse_decision(json.dumps(action)), action)

    def test_rejects_non_json_and_multiple_decisions(self):
        for response in (None, "```json\n{}\n```", '{}{}', '[{"type":"finish"}]', 'null'):
            with self.subTest(response=response), self.assertRaises((TypeError, ValueError)):
                parse_decision(response)

    def test_rejects_extra_fields_and_wrong_types(self):
        for action in (
            {"type": "finish", "name": "unexpected"},
            {"type": "call", "name": "demo.list_lights", "arguments": []},
            {"type": "call", "name": "", "arguments": {}},
            {"type": "call", "name": "demo.list_lights"},
            {"type": "unknown"},
        ):
            with self.subTest(action=action), self.assertRaises((TypeError, ValueError)):
                parse_decision(json.dumps(action))


class ControllerTests(unittest.TestCase):
    def test_invalid_proposals_produce_no_calls(self):
        env = MockToolEnv()
        controller = Controller(env)
        for action in (None, [], {}, call("unknown"), call("demo.set_light", id="missing", on=True)):
            with self.subTest(action=action):
                self.assertFalse(controller.execute(action)["ok"])
        self.assertEqual(env.get_tool_calls(), [])

    def test_controller_keeps_the_injected_environment(self):
        env = MockToolEnv()
        controller = Controller(env)
        self.assertIs(controller.env, env)
        self.assertTrue(controller.execute(call("demo.set_light", id="synthetic-lamp", on=True))["ok"])
        self.assertTrue(env.lights["synthetic-lamp"])
        self.assertEqual(len(env.get_tool_calls()), 1)


class AgentTests(unittest.TestCase):
    def test_prior_history_is_context_and_is_not_replayed_or_modified(self):
        prior = [{"action": call("demo.set_light", id="synthetic-lamp", on=True), "result": {"ok": True}}]
        original = copy.deepcopy(prior)
        planner = ScriptedPlanner([{"type": "finish"}])
        env = MockToolEnv()
        result = Agent(planner, env).run("synthetic request", {}, prior)
        self.assertEqual(result, {"status": "finished", "history": []})
        self.assertEqual(env.get_tool_calls(), [])
        self.assertEqual(prior, original)
        self.assertEqual(planner.histories[0], original)

    def test_observations_feed_next_decision(self):
        planner = ScriptedPlanner([call(), {"type": "finish"}])
        env = MockToolEnv()
        result = Agent(planner, env).run("synthetic request", {})
        self.assertEqual(result["status"], "finished")
        self.assertEqual(planner.histories[1][0]["result"]["lights"][0]["id"], "synthetic-lamp")

    def test_step_budget_preserves_actual_calls(self):
        env = MockToolEnv()
        result = Agent(ScriptedPlanner([call(), call()]), env, max_steps=2).run("synthetic", {})
        self.assertEqual(result["status"], "max_steps")
        self.assertEqual(len(env.get_tool_calls()), 2)

    def test_invalid_call_stops_without_side_effect(self):
        env = MockToolEnv()
        result = Agent(ScriptedPlanner([call("unavailable")]), env).run("synthetic", {})
        self.assertEqual(result["status"], "tool_error")
        self.assertEqual(env.get_tool_calls(), [])

    def test_late_decision_cannot_execute_a_write(self):
        moments = iter([0, 0, 31])
        env = MockToolEnv()
        planner = ScriptedPlanner([call("demo.set_light", id="synthetic-lamp", on=True)])
        result = Agent(planner, env, sample_timeout=30, clock=lambda: next(moments)).run("synthetic", {})
        self.assertEqual(result["status"], "timeout")
        self.assertEqual(env.get_tool_calls(), [])

    def test_completed_call_trace_survives_later_planner_exception(self):
        events = []
        env = MockToolEnv()
        with self.assertRaises(StopIteration):
            Agent(ScriptedPlanner([call()]), env, trace_sink=events.append).run("synthetic", {})
        self.assertEqual(len(env.get_tool_calls()), 1)
        self.assertEqual(events[0]["type"], "tool_result")

    def test_invalid_budgets_and_history(self):
        for kwargs in ({"max_steps": 0}, {"sample_timeout": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Agent(ScriptedPlanner([]), MockToolEnv(), **kwargs)
        with self.assertRaises(TypeError):
            Agent(ScriptedPlanner([]), MockToolEnv()).run("synthetic", {}, {})


class DemoTests(unittest.TestCase):
    def test_real_core_completes_mock_read_write_finish(self):
        first, second = run_demo(), run_demo()
        self.assertEqual(first, second)
        self.assertEqual(first["mode"], "mock")
        for key in ("asr_executed", "llm_inference_executed", "official_sdk_executed"):
            self.assertFalse(first[key])
        self.assertEqual(first["status"], "finished")
        self.assertEqual([c["name"] for c in first["tool_calls"]], ["demo.list_lights", "demo.set_light"])
        self.assertNotEqual(first["mock_state_hash"], MockToolEnv().get_state_hash())

    def test_budget_limit_is_visible_in_demo(self):
        result = run_demo(max_steps=1)
        self.assertEqual(result["status"], "max_steps")
        self.assertEqual(len(result["tool_calls"]), 1)
