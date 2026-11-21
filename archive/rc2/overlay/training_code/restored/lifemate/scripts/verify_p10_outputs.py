"""Replay P10 predictions and compare independently produced trajectories."""

import argparse
import json
from pathlib import Path

from scripts.run_p10_audio import ROOT, tool_env_for_split


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def index_by_id(rows: list[dict]) -> dict[str, dict]:
    indexed = {row["id"]: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError("Duplicate sample ID")
    return indexed


def replay_predictions(predictions: list[dict], tool_env) -> list[str]:
    mismatches = []
    for prediction in predictions:
        env = tool_env("train", prediction["id"], root=ROOT)
        for call in prediction["tool_calls"]:
            env.call(call["name"], call["arguments"])
        if (env.get_tool_calls() != prediction["tool_calls"]
                or env.get_state_hash() != prediction["state_hash"]):
            mismatches.append(prediction["id"])
    return mismatches


def compare_predictions(left: list[dict], right: list[dict]) -> dict:
    left_by_id, right_by_id = index_by_id(left), index_by_id(right)
    common = left_by_id.keys() & right_by_id.keys()
    mismatches = sorted(sample_id for sample_id in common
                        if left_by_id[sample_id] != right_by_id[sample_id])
    return {"compared": len(common), "mismatch_ids": mismatches,
            "left_only_ids": sorted(left_by_id.keys() - right_by_id.keys()),
            "right_only_ids": sorted(right_by_id.keys() - left_by_id.keys())}


def transcripts(run: Path) -> list[dict]:
    return [
        {"id": row["id"], "clips": [
            {"history_index": clip["history_index"], "text": clip["text"]}
            for clip in row["transcripts"]
        ]}
        for row in load_jsonl(run / "trajectories.jsonl") if row["arm"] == "asr"
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--p9-predictions", type=Path, required=True)
    parser.add_argument("--repeat-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    tool_env = tool_env_for_split(ROOT, "train")
    p9 = load_jsonl(args.p9_predictions)
    report = {}
    for arm in ("reference", "asr"):
        predictions = load_jsonl(args.run / f"{arm}_predictions.jsonl")
        repeated = load_jsonl(args.repeat_run / f"{arm}_predictions.jsonl")
        report[arm] = {
            "replayed": len(predictions),
            "replay_mismatch_ids": replay_predictions(predictions, tool_env),
            "repeat_prediction_comparison": compare_predictions(repeated, predictions),
        }
        if arm == "reference":
            report[arm]["p9_prediction_comparison"] = compare_predictions(predictions, p9)
    report["asr"]["repeat_transcript_comparison"] = compare_predictions(
        transcripts(args.repeat_run), transcripts(args.run))
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps({
        arm: {"replayed": report[arm]["replayed"],
              "replay_mismatches": len(report[arm]["replay_mismatch_ids"]),
              "repeat_compared": report[arm]["repeat_prediction_comparison"]["compared"],
              "repeat_mismatches": len(report[arm]["repeat_prediction_comparison"]["mismatch_ids"])}
        for arm in ("reference", "asr")
    }, ensure_ascii=False))
    if any(report[arm]["replay_mismatch_ids"] for arm in ("reference", "asr")):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
