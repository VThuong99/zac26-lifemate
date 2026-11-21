"""Minimal sequential agent execution loop."""

import time

from lifemate.controller import Controller


class Agent:
    def __init__(
        self,
        planner,
        env,
        max_steps=10,
        trace_sink=None,
        sample_timeout=None,
        clock=time.monotonic,
    ):
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        if sample_timeout is not None and sample_timeout <= 0:
            raise ValueError("sample_timeout must be positive")

        self.planner = planner
        self.env = env
        self.controller = Controller(env)
        self.max_steps = max_steps
        self.trace_sink = trace_sink
        self.sample_timeout = sample_timeout
        self.clock = clock

    def run(self, text, context, prior_history=None):
        """Run planner decisions using one existing ToolEnv session."""
        if prior_history is None:
            prior_history = []
        if not isinstance(prior_history, list):
            raise TypeError("prior_history must be a list")

        # Dataset conversation turns are planner context only. Their historical
        # tool effects are already present in ToolEnv's initial state and must
        # never be re-executed in this Agent session.
        planner_history = list(prior_history)
        history = []
        started = self.clock()

        for _ in range(self.max_steps):
            remaining = None
            if self.sample_timeout is not None:
                remaining = self.sample_timeout - (self.clock() - started)
                if remaining <= 0:
                    return self._timeout(history)

            if remaining is None:
                action = self.planner.next_action(text, context, planner_history)
            else:
                action = self.planner.next_action(
                    text,
                    context,
                    planner_history,
                    timeout=remaining,
                )

            # A decision returned after the sample deadline must not create a
            # new side effect, even if it is syntactically valid.
            if self.sample_timeout is not None and self.clock() - started >= self.sample_timeout:
                return self._timeout(history)

            if not isinstance(action, dict):
                raise TypeError("Planner must return a dictionary")

            if action.get("type") == "finish":
                return {
                    "status": "finished",
                    "history": history,
                }

            if action.get("type") != "call":
                raise ValueError(f"Unknown action type: {action.get('type')}")

            result = self.controller.execute(action)

            step = {
                "action": action,
                "result": result,
            }
            history.append(step)
            planner_history.append(step)

            # Persist each completed tool observation immediately so a
            # later planner exception cannot erase the execution trace.
            if self.trace_sink is not None:
                self.trace_sink(
                    {
                        "type": "tool_result",
                        "action": action,
                        "result": result,
                    }
                )

            # Invalid or failed tool calls stop this simple agent.
            if not result.get("ok"):
                return {
                    "status": "tool_error",
                    "history": history,
                }

        return {
            "status": "max_steps",
            "history": history,
        }

    def _timeout(self, history):
        if self.trace_sink is not None:
            self.trace_sink(
                {
                    "type": "agent_timeout",
                    "sample_timeout": self.sample_timeout,
                    "executed_steps": len(history),
                }
            )
        return {"status": "timeout", "history": history}
