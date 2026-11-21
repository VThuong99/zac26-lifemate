"""Optional, compact decision guidance derived from completed tool steps."""

GROUNDED_PROGRESS_POLICY = (
    "Treat each requested task as a separate binding of operation, "
    "recipient/target, amount, and required evidence; never mix bindings "
    "between task clauses. Choose a tool whose documented operation matches "
    "the user's verb: a phone top-up is not a person-to-person transfer, a "
    "bill payment is not a transfer, and a bill amount does not authorize "
    "paying that bill. Use IDs, phone numbers, bill IDs, and amounts only "
    "from the user or the observation that established that same task "
    "binding. The progress_ledger summarizes completed calls while "
    "previous_steps contains the complete observations. Do not repeat an "
    "identical action after an empty_result or tool_error; choose another "
    "supported evidence source or sys.ask_missing_info. Treat ok:true with "
    "done:false anywhere in an observation as incomplete, not business "
    "success. Do not finish while any requested action is unexecuted or "
    "incomplete; do not send a notification before its requested "
    "state-changing action has completed."
)


def build_progress_ledger(history: list[dict]) -> list[dict]:
    """Summarize execution progress without removing raw observations."""
    ledger = []

    for index, step in enumerate(history):
        action = step.get("action") if isinstance(step, dict) else None
        result = step.get("result") if isinstance(step, dict) else None

        if not isinstance(action, dict) or not isinstance(result, dict):
            raise TypeError("Progress ledger requires action/result object steps")

        ledger.append(
            {
                "step": index,
                "action": {
                    "name": action.get("name"),
                    "arguments": action.get("arguments"),
                },
                "outcome": _outcome(result),
            }
        )

    return ledger


def _outcome(result: dict) -> str:
    if result.get("ok") is not True:
        return "tool_error"
    if _contains_done_false(result):
        return "incomplete"
    if _contains_empty_list(result):
        return "empty_result"
    return "completed"


def _contains_done_false(value) -> bool:
    if isinstance(value, dict):
        if value.get("done") is False:
            return True
        return any(_contains_done_false(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_done_false(child) for child in value)
    return False


def _contains_empty_list(result: dict) -> bool:
    return any(isinstance(value, list) and not value for value in result.values())
