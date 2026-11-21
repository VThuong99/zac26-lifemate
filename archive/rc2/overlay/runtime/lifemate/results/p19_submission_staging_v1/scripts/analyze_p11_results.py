"""Pair P11 conditions, audit cue edits and replay recorded ToolEnv calls."""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from scripts.analyze_p10_sensitive import markers
from scripts.evaluate_p10 import ROOT
from scripts.evaluate_p11 import compare_to
from scripts.run_p10_audio import tool_env_for_split
from scripts.verify_p10_outputs import compare_predictions, load_jsonl, replay_predictions
from src.p9_data import load_partition


def indexed(rows: list[dict]) -> dict[str, dict]:
    result = {row["id"]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError("Duplicate sample ID")
    return result


def marker_edits(rows: list[dict], model: str, turn: str) -> dict[str, set[str]]:
    edited = defaultdict(set)
    for row in rows:
        if turn == "latest" and row["history_index"] is not None:
            continue
        if turn == "history" and row["history_index"] is None:
            continue
        changed = Counter(token for edit in row[model]["literal"]["differences"]
                          for token in edit["reference"])
        for category, tokens in markers(row["reference"]).items():
            if any(changed[token] for token in tokens):
                edited[category].add(row["id"])
    return dict(edited)


def attribution(reference: list[dict], treatment: list[dict],
                edited: dict[str, set[str]]) -> dict:
    ref, arm = indexed(reference), indexed(treatment)
    if ref.keys() != arm.keys():
        raise ValueError("Conditions have different sample IDs")
    if any(not ids <= ref.keys() for ids in edited.values()):
        raise ValueError("ASR analysis contains an unknown sample ID")
    result = {}
    for category, selected in edited.items():
        group = [arm[sample_id]["finished_score"] - ref[sample_id]["finished_score"]
                 for sample_id in ref if sample_id in selected]
        other = [arm[sample_id]["finished_score"] - ref[sample_id]["finished_score"]
                 for sample_id in ref if sample_id not in selected]
        result[category] = {
            "samples_with_edited_marker": len(group),
            "regressed": sum(delta < 0 for delta in group),
            "improved": sum(delta > 0 for delta in group),
            "summed_f1_delta": sum(group),
            "mean_f1_delta_100": 100 * sum(group) / len(group) if group else None,
            "other_samples": len(other),
            "other_mean_f1_delta_100": 100 * sum(other) / len(other) if other else None,
        }
    return result


def paired_bootstrap(reference: list[dict], treatment: list[dict], repetitions: int = 10000) -> dict:
    if not reference or len(reference) != len(treatment) or repetitions < 1:
        raise ValueError("Bootstrap requires equally sized nonempty conditions and positive repetitions")
    if any(left["id"] != right["id"] for left, right in zip(reference, treatment, strict=True)):
        raise ValueError("Bootstrap conditions must have matching sample order")
    differences = np.array([right["finished_score"] - left["finished_score"]
                            for left, right in zip(reference, treatment, strict=True)])
    random = np.random.default_rng(20261030)
    sample_means = random.choice(differences, size=(repetitions, len(differences))).mean(axis=1) * 100
    low, high = np.percentile(sample_means, [2.5, 97.5])
    return {"lower_f1_points": float(low), "upper_f1_points": float(high),
            "repetitions": repetitions, "seed": 20261030,
            "method": "paired sample-level percentile bootstrap; not clustered by family"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--factorial", type=Path, required=True)
    parser.add_argument("--phowhisper", type=Path, required=True)
    parser.add_argument("--asr-analysis", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    scores = json.loads((args.factorial / "scores.json").read_text(encoding="utf-8"))
    pho = json.loads((args.phowhisper / "scores.json").read_text(encoding="utf-8"))["asr_asr"]
    required = ("ref_ref", "asr_ref", "ref_asr", "asr_asr", "normalized")
    if any(name not in scores for name in required):
        raise ValueError("Factorial results lack a required condition")
    ref = indexed(scores["ref_ref"])
    for arm in [scores[name] for name in required] + [pho]:
        if indexed(arm).keys() != ref.keys():
            raise ValueError("Condition sample IDs differ")
    # compare_to expects matching order, not merely matching sets.
    ordered = {name: [indexed(scores[name])[sample_id] for sample_id in ref] for name in required}
    pho = [indexed(pho)[sample_id] for sample_id in ref]
    analyses = load_jsonl(args.asr_analysis / "paired_utterances.jsonl")
    if {row["id"] for row in analyses} != ref.keys():
        raise ValueError("ASR analysis and trajectory sample IDs differ")
    report = {
        "interpretation": "Literal cue edits are overlapping heuristics and correlations, "
                          "not semantic field errors or proof that a particular edit caused a regression.",
        "paired": {
            "latest_given_reference_history": compare_to(ordered["ref_ref"], ordered["asr_ref"]),
            "latest_given_asr_history": compare_to(ordered["ref_asr"], ordered["asr_asr"]),
            "history_given_reference_latest": compare_to(ordered["ref_ref"], ordered["ref_asr"]),
            "history_given_asr_latest": compare_to(ordered["asr_ref"], ordered["asr_asr"]),
            "normalization_vs_raw_gipformer": compare_to(ordered["asr_asr"], ordered["normalized"]),
            "phowhisper_vs_gipformer": compare_to(ordered["asr_asr"], pho),
            "phowhisper_vs_reference": compare_to(ordered["ref_ref"], pho),
        },
        "gipformer_literal_marker_attribution": {
            "latest_only": attribution(ordered["ref_ref"], ordered["asr_ref"],
                                       marker_edits(analyses, "gipformer", "latest")),
            "history_only": attribution(ordered["ref_ref"], ordered["ref_asr"],
                                        marker_edits(analyses, "gipformer", "history")),
            "both": attribution(ordered["ref_ref"], ordered["asr_asr"],
                                marker_edits(analyses, "gipformer", "all")),
        },
    }
    report["paired"]["normalization_vs_raw_gipformer"]["bootstrap_95_percent"] = paired_bootstrap(
        ordered["asr_asr"], ordered["normalized"])
    report["paired"]["phowhisper_vs_gipformer"]["bootstrap_95_percent"] = paired_bootstrap(
        ordered["asr_asr"], pho)
    tool_env = tool_env_for_split(ROOT, "train")
    predictions = {
        **{name: load_jsonl(args.factorial / f"{name}_predictions.jsonl") for name in required},
        "phowhisper": load_jsonl(args.phowhisper / "asr_asr_predictions.jsonl"),
    }
    for arm in predictions.values():
        if indexed(arm).keys() != ref.keys():
            raise ValueError("Prediction sample IDs differ")
    pred_by_arm = {name: indexed(rows) for name, rows in predictions.items()}
    normalized_runs = indexed([row for row in load_jsonl(args.factorial / "trajectories.jsonl")
                               if row["condition"] == "normalized"])
    if normalized_runs.keys() != ref.keys():
        raise ValueError("Normalization trajectories have different sample IDs")
    validation = indexed(load_partition(ROOT, "validation"))
    no_audio_history = {sample_id for sample_id in ref if not any(
        turn.get("role") == "user" and "audio" in turn
        for turn in validation[sample_id]["history"]
    )}

    def control(left: str, right: str, sample_ids: set[str]) -> dict:
        left_scores, right_scores = indexed(ordered[left]), indexed(ordered[right])
        deltas = {sample_id: right_scores[sample_id]["finished_score"]
                  - left_scores[sample_id]["finished_score"] for sample_id in sample_ids}
        return {
            "samples": len(sample_ids),
            "different_predictions": sum(pred_by_arm[left][sample_id] != pred_by_arm[right][sample_id]
                                         for sample_id in sample_ids),
            "score_regressions": sum(delta < 0 for delta in deltas.values()),
            "score_improvements": sum(delta > 0 for delta in deltas.values()),
            "score_delta_points_over_all_samples": 100 * sum(deltas.values()) / len(ref),
            "score_changed_ids": sorted(sample_id for sample_id, delta in deltas.items() if delta),
        }

    normalized_changed = {sample_id for sample_id, row in normalized_runs.items()
                          if row["normalization_changes"]}
    report["input_change_controls"] = {
        "normalization_unchanged_input": control("asr_asr", "normalized", set(ref) - normalized_changed),
        "normalization_changed_input": control("asr_asr", "normalized", normalized_changed),
        "reference_latest_no_audio_history": control("ref_ref", "ref_asr", no_audio_history),
        "asr_latest_no_audio_history": control("asr_ref", "asr_asr", no_audio_history),
    }
    report["replay"] = {
        name: {"samples": len(arm), "mismatch_ids": replay_predictions(arm, tool_env)}
        for name, arm in predictions.items()
    }
    p10 = ROOT / "results/p10_paired_validation_v2"
    report["p10_reproduction"] = {
        "reference": compare_predictions(predictions["ref_ref"],
                                         load_jsonl(p10 / "reference_predictions.jsonl")),
        "gipformer": compare_predictions(predictions["asr_asr"],
                                        load_jsonl(p10 / "asr_predictions.jsonl")),
    }
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"paired": report["paired"],
                      "replay_mismatches": {name: len(row["mismatch_ids"])
                                            for name, row in report["replay"].items()},
                      "p10_prediction_mismatches": {
                          name: len(row["mismatch_ids"])
                          for name, row in report["p10_reproduction"].items()}}, ensure_ascii=False))
    if any(row["mismatch_ids"] for row in report["replay"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
