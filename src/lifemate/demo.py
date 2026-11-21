"""Synthetic read-then-write demonstration using the real base planner/controller.

The model responses and tool environment are mocks. No ASR, model inference,
official SDK, external service, or competition data is used.
"""

import argparse
import copy
import hashlib
import json

from lifemate.agent import Agent
from lifemate.llm_client import InferenceMetrics, InferenceResult
from lifemate.llm_planner import LLMPlanner

TOOLS = [
    {
        "name": "demo.list_lights",
        "description": "List lights in the synthetic room.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "demo.set_light",
        "description": "Set a synthetic light after observing its identifier.",
        "parameters": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "on": {"type": "boolean"}},
            "required": ["id", "on"],
        },
    },
]


class MockToolEnv:
    """An in-memory teaching fixture, not an implementation of the organizer SDK."""

    def __init__(self):
        self.lights = {"synthetic-lamp": False}
        self.calls = []

    def validate(self, name, arguments):
        valid = isinstance(arguments, dict)
        if name == "demo.list_lights":
            valid = valid and not arguments
        elif name == "demo.set_light":
            valid = (
                valid
                and set(arguments) == {"id", "on"}
                and isinstance(arguments["id"], str)
                and arguments["id"] in self.lights
                and type(arguments["on"]) is bool
            )
        else:
            valid = False
        return {"ok": True} if valid else {"ok": False, "error": "Invalid mock call"}

    def call(self, name, arguments):
        validation = self.validate(name, arguments)
        if not validation["ok"]:
            raise ValueError(validation["error"])
        self.calls.append({"name": name, "arguments": copy.deepcopy(arguments)})
        if name == "demo.list_lights":
            return {"ok": True, "lights": [{"id": key, "on": value} for key, value in self.lights.items()]}
        self.lights[arguments["id"]] = arguments["on"]
        return {"ok": True, "done": True}

    def get_tool_calls(self):
        return copy.deepcopy(self.calls)

    def get_state_hash(self):
        # This is a demonstration hash, with no claimed equivalence to ToolEnv.
        payload = json.dumps(self.lights, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()


class MockDecisionClient:
    """Emit scripted JSON while grounding the write ID in the last observation."""

    def generate(self, messages, **kwargs):
        payload = json.loads(messages[-1]["content"])
        steps = [step for step in payload["previous_steps"] if "action" in step]
        if not steps:
            decision = {"type": "call", "name": "demo.list_lights", "arguments": {}}
        elif steps[-1]["action"]["name"] == "demo.list_lights":
            light = steps[-1]["result"]["lights"][0]
            decision = {
                "type": "call", "name": "demo.set_light",
                "arguments": {"id": light["id"], "on": True},
            }
        else:
            decision = {"type": "finish"}
        return InferenceResult(
            content=json.dumps(decision),
            metrics=InferenceMetrics(0.0, None, None, None, None),
            finish_reason="stop",
        )


def run_demo(max_steps=7):
    env = MockToolEnv()
    events = []
    planner = LLMPlanner(TOOLS, client=MockDecisionClient(), trace_sink=events.append)
    result = Agent(planner, env, max_steps=max_steps, trace_sink=events.append).run(
        "Bật đèn trong phòng mô phỏng.", {"source": "handwritten synthetic example"}
    )
    return {
        "mode": "mock",
        "asr_executed": False,
        "llm_inference_executed": False,
        "official_sdk_executed": False,
        "status": result["status"],
        "tool_calls": env.get_tool_calls(),
        "mock_state_hash": env.get_state_hash(),
        "events": events,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-steps", type=int, default=7, help="Decision budget (includes finish)")
    args = parser.parse_args()
    if args.max_steps < 1:
        parser.error("--max-steps must be positive")
    print(json.dumps(run_demo(args.max_steps), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
