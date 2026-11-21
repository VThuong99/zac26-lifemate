"""Tool-call matching according to the LifeMate scoring specification."""

import unicodedata


def fuzzy_token_f1(left: str, right: str) -> float:
    """Compute token F1 after lowercase and Unicode NFC normalization."""
    from collections import Counter

    left_tokens = unicodedata.normalize("NFC", left.lower()).split()
    right_tokens = unicodedata.normalize("NFC", right.lower()).split()

    if not left_tokens and not right_tokens:
        return 1.0
    if not left_tokens or not right_tokens:
        return 0.0

    overlap = sum((Counter(left_tokens) & Counter(right_tokens)).values())
    precision = overlap / len(left_tokens)
    recall = overlap / len(right_tokens)

    return 2 * precision * recall / (precision + recall) if overlap else 0.0


def fuzzy_arguments_by_tool(catalog: dict) -> dict[str, set[str]]:
    """Extract fuzzy argument names from the official tool catalog."""
    return {
        tool["name"]: {
            name
            for name, schema in tool["parameters"].get("properties", {}).items()
            if schema.get("x-match") == "fuzzy"
        }
        for app in catalog["apps"]
        for tool in app["tools"]
    }


def strict_equal(left, right) -> bool:
    """Compare JSON values recursively without Python bool/int coercion."""
    if type(left) is not type(right):
        return False

    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            strict_equal(left[key], right[key]) for key in left
        )

    if isinstance(left, list):
        return len(left) == len(right) and all(
            strict_equal(a, b) for a, b in zip(left, right, strict=True)
        )

    return left == right


def calls_match(gold: dict, predicted: dict, fuzzy_names: set[str]) -> bool:
    """Check if two tool calls match under catalog-defined argument rules."""
    if gold["name"] != predicted["name"]:
        return False

    expected = gold["arguments"]
    actual = predicted["arguments"]

    if expected.keys() != actual.keys():
        return False

    for name, value in expected.items():
        candidate = actual[name]

        if name in fuzzy_names:
            if not isinstance(value, str) or not isinstance(candidate, str):
                return False
            if fuzzy_token_f1(value, candidate) <= 0.6:
                return False
        elif not strict_equal(value, candidate):
            return False

    return True


def count_matched_calls(
    gold_calls: list[dict],
    predicted_calls: list[dict],
    fuzzy_by_tool: dict[str, set[str]],
) -> int:
    """Count maximum one-to-one matches, ignoring call order."""
    matched_predictions = {}

    def augment(gold_index: int, visited: set[int]) -> bool:
        gold = gold_calls[gold_index]

        for predicted_index, predicted in enumerate(predicted_calls):
            if predicted_index in visited:
                continue

            if not calls_match(
                gold,
                predicted,
                fuzzy_by_tool.get(gold["name"], set()),
            ):
                continue

            visited.add(predicted_index)

            if predicted_index not in matched_predictions or augment(
                matched_predictions[predicted_index],
                visited,
            ):
                matched_predictions[predicted_index] = gold_index
                return True

        return False

    return sum(augment(i, set()) for i in range(len(gold_calls)))
