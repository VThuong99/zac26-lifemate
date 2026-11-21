"""Parse a model response into one planner decision."""

import json


def parse_decision(response: str) -> dict:
    """Accept a strict JSON decision from the model."""
    try:
        action = json.loads(response)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("Model response is not valid JSON") from exc

    if not isinstance(action, dict):
        raise TypeError("Model decision must be a JSON object")

    action_type = action.get("type")

    if action_type == "finish":
        if set(action) != {"type"}:
            raise ValueError("Finish action must contain only 'type'")
        return action

    if action_type != "call":
        raise ValueError(f"Unsupported action type: {action_type}")

    if set(action) != {"type", "name", "arguments"}:
        raise ValueError("Call action has missing or extra fields")

    if not isinstance(action["name"], str) or not action["name"]:
        raise TypeError("Tool name must be a non-empty string")

    if not isinstance(action["arguments"], dict):
        raise TypeError("Tool arguments must be a JSON object")

    return action
