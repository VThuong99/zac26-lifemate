"""Paired P14 formatting evaluation using the unchanged P11 trajectory harness."""

import argparse
import copy
import json
import time
from pathlib import Path

from scripts.analyze_p11_results import paired_bootstrap
from scripts.evaluate_p10 import ROOT, server, sha256, timing_summary
from scripts.evaluate_p11 import compare_to, load_transcripts, mix_input
from scripts.prepare_p14_formatting import prepare_records
from scripts.run_p10_audio import tool_env_for_split
from scripts.verify_p10_outputs import compare_predictions
from src.evaluate import score_sample
from src.llm_client import LLMClient
from src.p10_audio import run_trajectory
from src.p9_data import load_partition
from src.tool_call_matcher import fuzzy_arguments_by_tool


ARMS = ("raw", "formatting", "punctuation", "raw_repeat")


def verify_baseline(transcripts: Path, gguf: Path, binary: Path) -> tuple[dict, dict]:
    p10_path = ROOT / "results/p10_paired_validation_v2/run_config.json"
    p11_path = ROOT / "results/p11_factorial_validation_v1/run_config.json"
    p10 = json.loads(p10_path.read_text(encoding="utf-8"))
    p11 = json.loads(p11_path.read_text(encoding="utf-8"))
    expected = (
        (transcripts, p11["transcripts_sha256"]),
        (p10_path, p11["p10_manifest_sha256"]),
        (gguf, p10["gguf_sha256"]),
        (binary, p10["server_binary_sha256"]),
        (ROOT / "prompts/explicit_stopping.txt", p10["prompt_sha256"]),
        (ROOT / "train/train.jsonl", p10["dataset_sha256"]),
        (ROOT / "experiments/supervised_family_split_v2.json", p10["split_sha256"]),
    )
    for path, digest in expected:
        if sha256(path) != digest:
            raise ValueError(f"Frozen P10/P11 fingerprint mismatch: {path}")
    if p11["gguf_sha256"] != p10["gguf_sha256"] or p11["server_binary_sha256"] != p10["server_binary_sha256"]:
        raise ValueError("P10 and P11 model/backend fingerprints differ")
    if p10["sample_ids"] != p11["sample_ids"] or p11["sample_timeout"] != 30 or p11["max_steps"] != 7:
        raise ValueError("Frozen P11 sample order or evaluation settings differ")
    for group in ("frozen_p9_code_sha256", "frozen_p10_code_sha256"):
        for path, digest in p11[group].items():
            if sha256(ROOT / path) != digest:
                raise ValueError(f"Frozen integration fingerprint mismatch: {path}")
    return p10, p11


def controlled_records(records: dict[str, dict], ids: list[str], controls: Path) -> tuple[dict, set]:
    report = json.loads((controls / "report.json").read_text(encoding="utf-8"))
    if sha256(controls / "controls.jsonl") != report["controls_sha256"]:
        raise ValueError("P14 controls changed after token-diff verification")
    if sha256(ROOT / "src/p14_formatting.py") != report["formatting_source_sha256"]:
        raise ValueError("P14 formatting implementation changed after verification")
    expected, counts = prepare_records(records, ids)
    with (controls / "controls.jsonl").open(encoding="utf-8") as source:
        actual = [json.loads(line) for line in source if line.strip()]
    if actual != expected or counts["clips"] != 1011:
        raise ValueError("P14 controls do not match a fresh token-preserving transformation")
    by_key = {(row["id"], row["history_index"]): row for row in actual}
    if len(by_key) != len(actual):
        raise ValueError("Duplicate transformed clip")
    result = {arm: copy.deepcopy(records) for arm in ARMS}
    punctuation_changed = set()
    for sample_id in ids:
        for clip in records[sample_id]["transcripts"]:
            control = by_key[(sample_id, clip["history_index"])]
            for arm in ("formatting", "punctuation"):
                matching = [candidate for candidate in result[arm][sample_id]["transcripts"]
                            if candidate["history_index"] == clip["history_index"]]
                if len(matching) != 1:
                    raise ValueError("Duplicate or missing transformed transcript")
                matching[0]["text"] = control[arm]
            if control["punctuation"] != control["formatting"]:
                punctuation_changed.add(sample_id)
    return result, punctuation_changed


def paired(reference: list[dict], treatment: list[dict]) -> dict:
    if any(left["id"] != right["id"] for left, right in zip(reference, treatment, strict=True)):
        raise ValueError("Paired scores have different sample order")
    return {**compare_to(reference, treatment),
            "bootstrap_95_percent": paired_bootstrap(reference, treatment)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcripts", type=Path,
                        default=ROOT / "results/p10_paired_validation_v2/trajectories.jsonl")
    parser.add_argument("--controls", type=Path, required=True)
    parser.add_argument("--gguf", type=Path, required=True)
    parser.add_argument("--server-binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18087)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit must be nonnegative")
    p10, p11 = verify_baseline(args.transcripts, args.gguf, args.server_binary)
    all_ids = p10["sample_ids"]
    records = load_transcripts(args.transcripts)
    variants, punctuation_changed = controlled_records(records, all_ids, args.controls)
    validation = {row["id"]: row for row in load_partition(ROOT, "validation")}
    if len(validation) != len(all_ids) or set(validation) != set(all_ids):
        raise ValueError("Frozen validation IDs do not match the P10 manifest")
    ids = all_ids[:args.limit] if args.limit else all_ids
    rows = [validation[sample_id] for sample_id in ids]
    if not rows:
        raise ValueError("No validation samples")
    for row in rows:
        for arm in ARMS:
            mix_input(row, variants[arm][row["id"]], "asr_asr")
    args.output.mkdir(parents=True, exist_ok=False)
    config = {
        "sample_ids": ids, "arms": ARMS, "sample_timeout": p11["sample_timeout"],
        "max_steps": p11["max_steps"], "decoding": p11["decoding"],
        "arm_order": "Cyclic rotation by P10 sample index; all arms use one fresh ToolEnv per sample",
        "raw_repeat": "Identical raw-ASR input under the same decoding settings to measure drift",
        "cache_prompt": "Omitted, matching P11 LLMClient; prompt-cache drift remains possible",
        "transcripts_sha256": sha256(args.transcripts),
        "controls_sha256": sha256(args.controls / "controls.jsonl"),
        "controls_report_sha256": sha256(args.controls / "report.json"),
        "p10_manifest_sha256": sha256(ROOT / "results/p10_paired_validation_v2/run_config.json"),
        "p11_config_sha256": sha256(ROOT / "results/p11_factorial_validation_v1/run_config.json"),
        "gguf_sha256": sha256(args.gguf), "server_binary_sha256": sha256(args.server_binary),
        "source_sha256": {name: sha256(ROOT / name) for name in (
            "scripts/evaluate_p14_formatting.py", "scripts/prepare_p14_formatting.py",
            "src/p14_formatting.py", "scripts/evaluate_p11.py")},
        "frozen_p9_code_sha256": p11["frozen_p9_code_sha256"],
        "frozen_p10_code_sha256": p11["frozen_p10_code_sha256"],
        "transcription_timing": "Previously measured per-clip ASR time, as in P11; formatting precomputed",
        "gold_use": "Gold calls and state hashes used only for scoring after all trajectories",
    }
    (args.output / "run_config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    prompt = (ROOT / "prompts/explicit_stopping.txt").read_text(encoding="utf-8").strip()
    tool_env = tool_env_for_split(ROOT, "train")
    results = {arm: [] for arm in ARMS}
    with server(args.server_binary, args.gguf, args.port, args.output / "server.log") as (startup, command):
        client = LLMClient(endpoint=f"http://127.0.0.1:{args.port}/v1/chat/completions",
                           timeout=p11["sample_timeout"], decoding_mode="strict")
        with (args.output / "trajectories.jsonl").open("x", encoding="utf-8", buffering=1) as output:
            for index, row in enumerate(rows):
                offset = index % len(ARMS)
                order = ARMS[offset:] + ARMS[:offset]
                for arm in order:
                    started = time.perf_counter()
                    item, text, history, asr_seconds, changes = mix_input(
                        row, variants[arm][row["id"]], "asr_asr"
                    )
                    if changes:
                        raise ValueError("Unexpected P11 numeric normalization")
                    result = run_trajectory(item, text, history, ROOT, "train", tool_env, client,
                                            prompt, p11["sample_timeout"], max_steps=p11["max_steps"],
                                            started=started - asr_seconds)
                    result["timing"]["asr_seconds"] = asr_seconds
                    results[arm].append(result)
                    output.write(json.dumps({"id": row["id"], "condition": arm, **result},
                                            ensure_ascii=False) + "\n")
                print(json.dumps({"index": index + 1, "id": row["id"],
                                  "statuses": {arm: results[arm][-1]["status"] for arm in ARMS}}),
                      flush=True)

    hashes = json.loads((ROOT / "results/golden_state_hashes.json").read_text(encoding="utf-8"))
    catalog = json.loads((ROOT / "train/train_tools_catalog.json").read_text(encoding="utf-8"))
    fuzzy = fuzzy_arguments_by_tool(catalog)
    scored = {arm: [] for arm in ARMS}
    for index, row in enumerate(rows):
        for arm in ARMS:
            result = results[arm][index]
            prediction = result["prediction"]
            score = score_sample(row["label"]["tool_calls"], prediction["tool_calls"],
                                 prediction["state_hash"] == hashes[row["id"]], fuzzy)
            scored[arm].append({"id": row["id"], "status": result["status"], **score,
                                "finished_score": score["score"] if result["status"] == "finished" else 0.0})
    pairs = {
        "formatting_vs_raw": paired(scored["raw"], scored["formatting"]),
        "punctuation_vs_formatting": paired(scored["formatting"], scored["punctuation"]),
        "punctuation_vs_raw": paired(scored["raw"], scored["punctuation"]),
        "raw_repeat_vs_raw": paired(scored["raw"], scored["raw_repeat"]),
    }
    changed_indices = [i for i, sample_id in enumerate(ids) if sample_id in punctuation_changed]
    unchanged_indices = [i for i, sample_id in enumerate(ids) if sample_id not in punctuation_changed]
    by_punctuation_change = {}
    for name, indices in (("changed", changed_indices), ("unchanged", unchanged_indices)):
        if indices:
            by_punctuation_change[name] = {
                "samples": len(indices),
                **paired([scored["formatting"][i] for i in indices],
                         [scored["punctuation"][i] for i in indices]),
            }
    report = {"samples": len(rows), "server_initialization_seconds": startup,
              "server_command": command, "conditions": {}, "paired": pairs,
              "punctuation_changed_input_groups": by_punctuation_change}
    for arm in ARMS:
        scores = scored[arm]
        statuses = sorted({sample["status"] for sample in scores})
        report["conditions"][arm] = {
            "finished_state_gated_f1_100": 100 * sum(s["finished_score"] for s in scores) / len(scores),
            "state_matches": sum(s["state_matches"] for s in scores),
            "statuses": {status: sum(s["status"] == status for s in scores) for status in statuses},
            "timing": timing_summary(results[arm]),
        }
        with (args.output / f"{arm}_predictions.jsonl").open("x", encoding="utf-8") as output:
            for result in results[arm]:
                output.write(json.dumps(result["prediction"], ensure_ascii=False) + "\n")
    report["raw_repeat_prediction_comparison"] = compare_predictions(
        [result["prediction"] for result in results["raw"]],
        [result["prediction"] for result in results["raw_repeat"]]
    )
    (args.output / "scores.json").write_text(json.dumps(scored, ensure_ascii=False, indent=2) + "\n")
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"samples": len(rows), "conditions": {
        arm: {key: value for key, value in item.items() if key != "timing"}
        for arm, item in report["conditions"].items()}, "paired": pairs}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
