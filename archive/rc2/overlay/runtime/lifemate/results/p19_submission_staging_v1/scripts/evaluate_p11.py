"""Factorial and intervention evaluation using frozen, timed ASR transcripts."""

import argparse
import copy
import json
import time
from pathlib import Path

from scripts.evaluate_p10 import ROOT, server, sha256, timing_summary
from scripts.run_p10_audio import tool_env_for_split
from src.evaluate import score_sample
from src.llm_client import LLMClient
from src.p10_audio import inference_input, run_trajectory
from src.p11_numbers import normalize_transcript
from src.p9_data import load_partition
from src.tool_call_matcher import fuzzy_arguments_by_tool

CONDITIONS = {
    "ref_ref": (False, False, False),
    "asr_ref": (True, False, False),
    "ref_asr": (False, True, False),
    "asr_asr": (True, True, False),
    "normalized": (True, True, True),
}


def load_transcripts(path: Path) -> dict[str, dict]:
    records = {}
    with path.open(encoding="utf-8") as source:
        for line in source:
            row = json.loads(line)
            if row.get("arm") != "asr":
                continue
            if row["id"] in records:
                raise ValueError(f"Duplicate ASR record: {row['id']}")
            records[row["id"]] = row
    return records


def mix_input(row: dict, record: dict, condition: str) -> tuple[dict, str, list, float, list]:
    latest_asr, history_asr, normalize = CONDITIONS[condition]
    item = inference_input(row)
    history = item["history"] if history_asr else copy.deepcopy(row["history"])
    clips = record["transcripts"]
    by_index = {}
    for clip in clips:
        index = clip["history_index"]
        if index in by_index:
            raise ValueError(f"Duplicate history index for {row['id']}: {index}")
        if not isinstance(clip["text"], str) or not clip["text"]:
            raise ValueError(f"Empty or invalid cached transcript for {row['id']}")
        if clip["seconds"] < 0:
            raise ValueError("ASR seconds must be nonnegative")
        by_index[index] = clip
    expected = {None: item["audio"]}
    expected.update({i: turn["audio"] for i, turn in enumerate(item["history"])
                     if turn.get("role") == "user" and "audio" in turn})
    if set(expected) != set(by_index) or any(
        by_index[index]["audio"] != path for index, path in expected.items()
    ):
        raise ValueError(f"ASR clip inventory does not match sample {row['id']}")

    changes = []

    def transform(text, index):
        if not normalize:
            return text
        normalized, replacements = normalize_transcript(text)
        if replacements:
            changes.append({"history_index": index, "original": text,
                            "normalized": normalized, "replacements": replacements})
        return normalized

    if latest_asr:
        text = transform(by_index[None]["text"], None)
    else:
        text = row["audio_text"]
    if history_asr:
        for index, turn in enumerate(history):
            if index in by_index:
                turn["audio_text"] = transform(by_index[index]["text"], index)
            elif turn.get("role") == "user":
                if "audio_text" in turn:
                    raise ValueError("User audio_text without audio would leak a reference transcript")
                if not isinstance(turn.get("text"), str):
                    raise ValueError("User history turn requires audio or text")
    asr_seconds = sum(clip["seconds"] for index, clip in by_index.items()
                      if (index is None and latest_asr) or (index is not None and history_asr))
    return item, text, history, asr_seconds, changes


def compare_to(reference: list[dict], treatment: list[dict]) -> dict:
    if len(reference) != len(treatment):
        raise ValueError("Condition sample counts differ")
    delta = [b["finished_score"] - a["finished_score"]
             for a, b in zip(reference, treatment, strict=True)]
    return {
        "delta_f1_100": 100 * sum(delta) / len(delta),
        "regressed": sum(value < 0 for value in delta),
        "improved": sum(value > 0 for value in delta),
        "unchanged": sum(value == 0 for value in delta),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--transcripts", type=Path, required=True)
    parser.add_argument("--gguf", type=Path, required=True)
    parser.add_argument("--server-binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--conditions", nargs="+", choices=list(CONDITIONS),
                        default=["ref_ref", "asr_ref", "ref_asr", "asr_asr"])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--port", type=int, default=18083)
    parser.add_argument("--sample-timeout", type=float, default=30)
    args = parser.parse_args()
    if len(set(args.conditions)) != len(args.conditions) or args.limit < 0 or args.sample_timeout <= 0:
        parser.error("Conditions must be unique, limit nonnegative and timeout positive")
    manifest_path = ROOT / "results/p10_paired_validation_v2/run_config.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    row_by_id = {row["id"]: row for row in load_partition(ROOT, "validation")}
    ids = manifest["sample_ids"]
    if len(ids) != len(set(ids)) or set(ids) != set(row_by_id):
        raise ValueError("P10 IDs do not exactly match the frozen validation split")
    if args.limit:
        ids = ids[:args.limit]
    rows = [row_by_id[sample_id] for sample_id in ids]
    transcripts = load_transcripts(args.transcripts)
    if any(sample_id not in transcripts for sample_id in ids):
        raise ValueError("ASR transcripts are missing frozen validation samples")
    if not args.limit and set(transcripts) != set(ids):
        raise ValueError("ASR transcripts have unexpected validation IDs")
    prompt_path = ROOT / "prompts/explicit_stopping.txt"
    gguf_sha, binary_sha = sha256(args.gguf), sha256(args.server_binary)
    if (gguf_sha != manifest["gguf_sha256"] or binary_sha != manifest["server_binary_sha256"]
            or sha256(prompt_path) != manifest["prompt_sha256"]
            or sha256(ROOT / "train/train.jsonl") != manifest["dataset_sha256"]
            or sha256(ROOT / "experiments/supervised_family_split_v2.json") != manifest["split_sha256"]):
        raise ValueError("Model, server, prompt, dataset or split does not match frozen P10")
    p9_config = json.loads((ROOT / "results/p9_llamacpp_q4_validation_v1/run_config.json").read_text())
    code_hashes = p9_config["configuration"]["code_sha256"]
    frozen_code = (
        "src/agent.py", "src/controller.py", "src/llm_planner.py", "src/llm_client.py",
        "src/decision_parser.py", "src/tool_catalog.py", "src/tool_schema_formatter.py",
        "src/evaluate.py", "src/tool_call_matcher.py",
    )
    if any(sha256(ROOT / name) != code_hashes[name] for name in frozen_code):
        raise ValueError("A frozen P9 Agent, Controller, planner or evaluator file changed")
    p10_hashes = json.loads((ROOT / "results/p10_reproducibility_manifest_v1.json").read_text())["files_sha256"]
    frozen_p10_code = ("src/p10_audio.py", "src/p10_metrics.py", "scripts/evaluate_p10.py",
                       "scripts/run_p10_audio.py")
    if any(sha256(ROOT / name) != p10_hashes[name] for name in frozen_p10_code):
        raise ValueError("A frozen P10 integration or scoring file changed")
    args.output.mkdir(parents=True, exist_ok=False)
    prompt = prompt_path.read_text(encoding="utf-8").strip()
    config = {
        "sample_ids": ids, "conditions": args.conditions, "sample_timeout": args.sample_timeout,
        "max_steps": 7, "decoding": "P9 greedy strict JSON",
        "transcripts_sha256": sha256(args.transcripts), "p10_manifest_sha256": sha256(manifest_path),
        "gguf_sha256": gguf_sha, "server_binary_sha256": binary_sha,
        "frozen_p9_code_sha256": {name: code_hashes[name] for name in frozen_code},
        "frozen_p10_code_sha256": {name: p10_hashes[name] for name in frozen_p10_code},
        "transcription_timing": "sum of previously measured per-clip ASR seconds",
        "source_sha256": {name: sha256(ROOT / name) for name in
                          ("scripts/evaluate_p11.py", "src/p11_numbers.py", "src/p10_audio.py")},
    }
    (args.output / "run_config.json").write_text(json.dumps(config, indent=2) + "\n")
    tool_env = tool_env_for_split(ROOT, "train")
    results = {condition: [] for condition in args.conditions}
    with server(args.server_binary, args.gguf, args.port, args.output / "server.log") as (startup, command):
        client = LLMClient(endpoint=f"http://127.0.0.1:{args.port}/v1/chat/completions",
                           timeout=args.sample_timeout, decoding_mode="strict")
        with (args.output / "trajectories.jsonl").open("x", encoding="utf-8", buffering=1) as output:
            for index, row in enumerate(rows):
                offset = index % len(args.conditions)
                order = args.conditions[offset:] + args.conditions[:offset]
                for condition in order:
                    started = time.perf_counter()
                    item, text, history, asr_seconds, changes = mix_input(
                        row, transcripts[row["id"]], condition)
                    result = run_trajectory(item, text, history, ROOT, "train", tool_env, client,
                                            prompt, args.sample_timeout,
                                            started=started - asr_seconds)
                    result["timing"]["asr_seconds"] = asr_seconds
                    result["normalization_changes"] = changes
                    results[condition].append(result)
                    output.write(json.dumps({"id": row["id"], "condition": condition, **result},
                                            ensure_ascii=False) + "\n")
                print(json.dumps({"index": index + 1, "id": row["id"],
                                  "statuses": {c: results[c][-1]["status"] for c in args.conditions}}),
                      flush=True)

    hashes = json.loads((ROOT / "results/golden_state_hashes.json").read_text(encoding="utf-8"))
    catalog = json.loads((ROOT / "train/train_tools_catalog.json").read_text(encoding="utf-8"))
    fuzzy = fuzzy_arguments_by_tool(catalog)
    scored = {condition: [] for condition in args.conditions}
    for row_index, row in enumerate(rows):
        for condition in args.conditions:
            result = results[condition][row_index]
            prediction = result["prediction"]
            score = score_sample(row["label"]["tool_calls"], prediction["tool_calls"],
                                 prediction["state_hash"] == hashes[row["id"]], fuzzy)
            scored[condition].append({
                "id": row["id"], "status": result["status"], **score,
                "finished_score": score["score"] if result["status"] == "finished" else 0.0,
            })
    report = {"samples": len(rows), "server_initialization_seconds": startup,
              "server_command": command, "conditions": {}}
    for condition in args.conditions:
        scores = scored[condition]
        statuses = sorted({sample["status"] for sample in scores})
        report["conditions"][condition] = {
            "finished_state_gated_f1_100": 100 * sum(s["finished_score"] for s in scores) / len(scores),
            "state_matches": sum(s["state_matches"] for s in scores),
            "statuses": {status: sum(s["status"] == status for s in scores) for status in statuses},
            "timing": timing_summary(results[condition]),
            "normalization_changed_samples": sum(bool(r["normalization_changes"])
                                                  for r in results[condition]),
        }
        if "ref_ref" in scored:
            report["conditions"][condition]["vs_ref_ref"] = compare_to(scored["ref_ref"], scores)
        with (args.output / f"{condition}_predictions.jsonl").open("x", encoding="utf-8") as out:
            for result in results[condition]:
                out.write(json.dumps(result["prediction"], ensure_ascii=False) + "\n")
    if all(name in scored for name in ("ref_ref", "asr_ref", "ref_asr", "asr_asr")):
        report["interaction_f1_100"] = 100 * sum(
            scored["asr_asr"][i]["finished_score"] - scored["asr_ref"][i]["finished_score"]
            - scored["ref_asr"][i]["finished_score"] + scored["ref_ref"][i]["finished_score"]
            for i in range(len(rows))
        ) / len(rows)
    (args.output / "scores.json").write_text(json.dumps(scored, ensure_ascii=False, indent=2) + "\n")
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"samples": len(rows), "conditions": {
        name: {key: value for key, value in data.items() if key != "timing"}
        for name, data in report["conditions"].items()},
        "interaction_f1_100": report.get("interaction_f1_100")}), flush=True)


if __name__ == "__main__":
    main()
