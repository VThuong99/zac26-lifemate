import argparse
import json
from pathlib import Path


def load_jsonl(path: Path) -> dict:
    """Load JSONL records indexed by sample ID."""
    records = {}

    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue

            item = json.loads(line)
            sample_id = item["id"]

            if sample_id in records:
                raise ValueError(f"Duplicate sample ID: {sample_id}")

            records[sample_id] = item

    return records


def evaluate(gold_path: Path, prediction_path: Path) -> dict:
    """Measure exact tool-call agreement on labeled train data."""
    gold = load_jsonl(gold_path)
    predictions = load_jsonl(prediction_path)

    total = len(gold)
    matched = 0
    exact = 0
    missing = 0

    for sample_id, sample in gold.items():
        prediction = predictions.get(sample_id)

        if prediction is None:
            missing += 1
            continue

        matched += 1

        expected_calls = sample["label"]["tool_calls"]
        predicted_calls = prediction["tool_calls"]

        if predicted_calls == expected_calls:
            exact += 1

    return {
        "total_samples": total,
        "predicted_samples": matched,
        "missing_predictions": missing,
        "coverage": matched / total if total else 0.0,
        "exact_matches": exact,
        "exact_match_rate": exact / total if total else 0.0,
        "unexpected_predictions": len(set(predictions) - set(gold)),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--gold",
        type=Path,
        default=Path("train/train.jsonl"),
    )
    parser.add_argument(
        "--predictions",
        type=Path,
        default=Path("results/train_noop.jsonl"),
    )
    args = parser.parse_args()

    metrics = evaluate(args.gold, args.predictions)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()


def score_sample(
    gold_calls: list[dict],
    predicted_calls: list[dict],
    state_matches: bool,
    fuzzy_by_tool: dict[str, set[str]],
) -> dict:
    """Score one sample using LifeMate's state-gated tool-call F1.

    Matching uses the local implementation of the competition rules.
    Tokenization for fuzzy arguments remains an approximation until the
    organizer's tokenizer is confirmed.
    """
    from src.tool_call_matcher import count_matched_calls

    matched = count_matched_calls(
        gold_calls,
        predicted_calls,
        fuzzy_by_tool,
    )

    unmatched = len(predicted_calls) - matched

    # Official special case: no gold calls.
    if not gold_calls:
        score = 1.0 if not predicted_calls else 0.0

        return {
            "matched_calls": matched,
            "unmatched_calls": unmatched,
            "precision": None,
            "recall": None,
            "f1": None,
            "state_matches": state_matches,
            "score": score,
        }

    precision = matched / len(predicted_calls) if predicted_calls else 0.0
    recall = matched / len(gold_calls)

    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    score = f1 if state_matches and matched > 0 else 0.0

    return {
        "matched_calls": matched,
        "unmatched_calls": unmatched,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "state_matches": state_matches,
        "score": score,
    }


def evaluate_f1(
    gold_path: Path,
    prediction_path: Path,
    golden_hashes_path: Path,
    catalog_path: Path,
) -> dict:
    """Evaluate predictions using state-gated tool-call F1."""
    from src.tool_call_matcher import fuzzy_arguments_by_tool

    gold = load_jsonl(gold_path)
    predictions = load_jsonl(prediction_path)

    hashes = json.loads(golden_hashes_path.read_text(encoding="utf-8"))
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    fuzzy_by_tool = fuzzy_arguments_by_tool(catalog)

    missing_hashes = set(gold) - set(hashes)
    if missing_hashes:
        raise ValueError(f"Missing golden hashes for {len(missing_hashes)} samples")

    results = []
    missing_predictions = 0

    for sample_id, sample in gold.items():
        prediction = predictions.get(sample_id)

        if prediction is None:
            missing_predictions += 1
            predicted_calls = []
            state_matches = False
        else:
            predicted_calls = prediction["tool_calls"]
            state_matches = prediction["state_hash"] == hashes[sample_id]

        result = score_sample(
            sample["label"]["tool_calls"],
            predicted_calls,
            state_matches,
            fuzzy_by_tool,
        )

        # A missing prediction is not a valid empty-call submission.
        if prediction is None:
            result["score"] = 0.0

        results.append(
            {
                "id": sample_id,
                **result,
            }
        )

    total = len(results)
    return {
        "total_samples": total,
        "predicted_samples": total - missing_predictions,
        "missing_predictions": missing_predictions,
        "state_matches": sum(result["state_matches"] for result in results),
        "mean_tool_call_f1": (
            sum(result["f1"] if result["f1"] is not None else 0.0 for result in results)
            / total
            if total
            else 0.0
        ),
        "mean_state_gated_f1": (
            sum(result["score"] for result in results) / total if total else 0.0
        ),
        "score_100": (
            100 * sum(result["score"] for result in results) / total if total else 0.0
        ),
        "samples": results,
    }
