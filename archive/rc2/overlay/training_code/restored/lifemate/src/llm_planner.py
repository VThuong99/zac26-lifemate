"""Convert LifeMate context and observations into model decisions."""

import json
from dataclasses import asdict

from src.decision_parser import parse_decision
from src.llm_client import LLMClient
from src.planning_policy import GROUNDED_PROGRESS_POLICY, build_progress_ledger

SYSTEM_PROMPT = (
    "You are a Vietnamese AI agent planner. "
    "Return exactly one JSON decision. "
    "For a tool call use keys: type, name, arguments. "
    'For completion return: {"type":"finish"}. '
    "Use only available tools. "
    "Never invent IDs. "
    "Use tool observations to ground arguments. "
    "Do not include explanations."
)

# The embedded Qwen3 template wraps every native call in this XML tag.  The
# installed llama-server's automatic parser accepts a second wrapped call even
# when parallel_tool_calls is false, so stop at the first complete call.  The
# server parses the closing tag before applying the stop sequence.
QWEN_TOOL_CALL_CLOSE = "</tool_call>"


class LLMPlanner:
    """Planner implementation using an injected inference client."""

    def __init__(
        self,
        tools,
        client=None,
        tool_formatter=None,
        system_prompt=SYSTEM_PROMPT,
        trace_sink=None,
        interface_mode="custom_json",
        planning_policy="baseline",
    ):
        if interface_mode not in ("custom_json", "native_tools"):
            raise ValueError(f"Unknown interface mode: {interface_mode}")
        if planning_policy not in ("baseline", "grounded_progress"):
            raise ValueError(f"Unknown planning policy: {planning_policy}")
        self.tools = tools
        self.client = client if client is not None else LLMClient()
        self.tool_formatter = tool_formatter
        self.system_prompt = system_prompt
        self.trace_sink = trace_sink
        self.interface_mode = interface_mode
        self.planning_policy = planning_policy
        self.decision_index = 0

    def next_action(self, text, context, history, timeout=None):

        if self.interface_mode == "custom_json":
            messages = self._custom_messages(text, context, history)
            inference = (
                self.client.generate(messages)
                if timeout is None
                else self.client.generate(messages, timeout=timeout)
            )
            normalize = lambda: parse_decision(inference.content)
        else:
            messages = self._native_messages(text, context, history)
            kwargs = {
                "tools": self._openai_tools(),
                "parallel_tool_calls": False,
                "stop": (QWEN_TOOL_CALL_CLOSE,),
            }
            if timeout is not None:
                kwargs["timeout"] = timeout
            inference = self.client.generate(messages, **kwargs)
            normalize = lambda: self._normalize_native(inference)

        # Tracing is optional and must not change normal planner behavior.
        if self.trace_sink is None:
            try:
                return normalize()
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    f"Invalid planner decision: {inference.content!r}: {exc}"
                ) from exc

        decision_index = self.decision_index
        self.decision_index += 1

        event = {
            "type": "llm_decision",
            "decision_index": decision_index,
            "raw_response": inference.content,
            "finish_reason": inference.finish_reason,
            "metrics": asdict(inference.metrics),
        }
        if self.interface_mode == "native_tools":
            event["raw_response"] = inference.raw_response

        try:
            action = normalize()
        except (ValueError, TypeError) as exc:
            event["parse_ok"] = False
            event["parse_error"] = str(exc)
            self.trace_sink(event)

            raise ValueError(
                f"Invalid planner decision: {inference.content!r}: {exc}"
            ) from exc

        event["parse_ok"] = True
        event["action"] = action
        event["normalized_decision"] = action
        self.trace_sink(event)

        return action

    def _custom_messages(self, text, context, history):
        formatted_tools = (
            self.tool_formatter(self.tools)
            if self.tool_formatter is not None
            else self.tools
        )
        user_payload = {
            "user_request": text,
            "context": context,
            "available_tools": formatted_tools,
            "previous_steps": history,
        }
        if self.planning_policy == "grounded_progress":
            user_payload["decision_policy"] = GROUNDED_PROGRESS_POLICY
            user_payload["progress_ledger"] = build_progress_ledger(history)
        return [
            {"role": "system", "content": self._system_message()},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ]

    def _native_messages(self, text, context, history):
        messages = [
            {"role": "system", "content": self._system_message()},
            {
                "role": "user",
                "content": json.dumps(
                    self._native_user_payload(text, context, history),
                    ensure_ascii=False,
                ),
            },
        ]
        for index, step in enumerate(history):
            try:
                action = step["action"]
                result = step["result"]
                name = action["name"]
                arguments = action["arguments"]
            except (KeyError, TypeError) as exc:
                raise ValueError("Invalid history step for native tools") from exc
            if action.get("type") != "call" or name not in self._tool_names():
                raise ValueError("Invalid history action for native tools")
            if not isinstance(arguments, dict) or not isinstance(result, dict):
                raise TypeError("Native tool history must contain object arguments and results")
            call_id = f"lifemate_call_{index}"
            messages.extend(
                [
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": call_id,
                                "type": "function",
                                "function": {
                                    "name": name,
                                    "arguments": json.dumps(arguments, ensure_ascii=False),
                                },
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": name,
                        "content": json.dumps(result, ensure_ascii=False),
                    },
                ]
            )
        return messages

    def _system_message(self):
        if self.planning_policy == "grounded_progress":
            return f"{self.system_prompt}\n\n{GROUNDED_PROGRESS_POLICY}"
        return self.system_prompt

    def _native_user_payload(self, text, context, history):
        payload = {"user_request": text, "context": context}
        if self.planning_policy == "grounded_progress":
            payload["decision_policy"] = GROUNDED_PROGRESS_POLICY
            payload["progress_ledger"] = build_progress_ledger(history)
        return payload

    def _openai_tools(self):
        return [{"type": "function", "function": tool} for tool in self.tools]

    def _tool_names(self):
        return {tool["name"] for tool in self.tools}

    def _normalize_native(self, inference):
        calls = inference.tool_calls
        if calls:
            if inference.finish_reason != "tool_calls":
                raise ValueError(
                    "Native tool call response has unexpected finish_reason: "
                    f"{inference.finish_reason!r}"
                )
            if len(calls) != 1:
                raise ValueError("Native response must contain exactly one tool call")
            call = calls[0]
            if not isinstance(call, dict) or call.get("type") != "function":
                raise ValueError("Native tool call must be a function")
            function = call.get("function")
            if not isinstance(function, dict):
                raise ValueError("Native tool call has no function")
            name = function.get("name")
            if not isinstance(name, str) or name not in self._tool_names():
                raise ValueError(f"Native tool {name!r} is not available")
            raw_arguments = function.get("arguments")
            if not isinstance(raw_arguments, str):
                raise TypeError("Native tool arguments must be a JSON string")
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError as exc:
                raise ValueError("Native tool arguments are not valid JSON") from exc
            if not isinstance(arguments, dict):
                raise TypeError("Native tool arguments must decode to a JSON object")
            return {"type": "call", "name": name, "arguments": arguments}

        if inference.finish_reason != "stop":
            raise ValueError(
                "Native final response has unexpected finish_reason: "
                f"{inference.finish_reason!r}"
            )
        if not isinstance(inference.content, str):
            raise TypeError("Native final response must contain text content")
        return {"type": "finish"}
