"""Matched P15 formatting and prompt-cache ablations using the frozen P11 harness."""

import argparse
import copy
import hashlib
import json
import time
import unicodedata
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

from scripts.evaluate_p10 import ROOT, server, sha256
from scripts.evaluate_p11 import load_transcripts, mix_input
from scripts.evaluate_p14_formatting import paired, verify_baseline
from scripts.run_p10_audio import tool_env_for_split
from src.evaluate import score_sample
from src.llm_client import LLMClient
from src.p10_audio import run_trajectory
from src.p14_formatting import lexical_diff, normalize_format
from src.p9_data import load_partition
from src.tool_call_matcher import fuzzy_arguments_by_tool


# A space perturbation is synthetic: the frozen raw ASR already has single spaces.
ARMS = {
    "raw_off": ("raw", "both", False),
    "raw_off_repeat": ("raw", "both", False),
    "lower_off": ("lower", "both", False),
    "sentence_off": ("sentence", "both", False),
    "sentence_off_repeat": ("sentence", "both", False),
    "history_off": ("sentence", "history", False),
    "latest_off": ("sentence", "latest", False),
    "raw_spaced_off": ("spaced", "both", False),
    "sentence_spaced_off": ("sentence_spaced", "both", False),
    "raw_on": ("raw", "both", True),
    "raw_on_repeat": ("raw", "both", True),
    "sentence_on": ("sentence", "both", True),
    "sentence_on_repeat": ("sentence", "both", True),
}


class CacheControlError(Exception):
    """Cache telemetry failure must abort rather than become a scored model error."""


def transform(text: str, mode: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Transcript must be a nonempty string")
    if mode == "raw":
        result = text
    elif mode == "lower":
        result = text.lower()
    elif mode == "sentence":
        result = normalize_format(text)
    elif mode == "spaced":
        result = text.replace(" ", "  ")
    elif mode == "sentence_spaced":
        result = normalize_format(text).replace(" ", "  ")
    else:
        raise ValueError(f"Unknown formatting mode: {mode}")
    if (unicodedata.normalize("NFC", "".join(text.split()).casefold())
            != unicodedata.normalize("NFC", "".join(result.split()).casefold())
            or lexical_diff(text, result)):
        raise ValueError("Formatting changed non-whitespace, non-case content")
    return result


def variants_for(records: dict, ids: list[str]) -> tuple[dict, dict]:
    if set(records) != set(ids) or len(ids) != len(set(ids)):
        raise ValueError("Cached transcript IDs do not match frozen validation IDs")
    variants = {arm: copy.deepcopy(records) for arm in ARMS}
    changed = {arm: {"latest": 0, "history": 0} for arm in ARMS}
    inventory = {"clips": 0, "not_uppercase": 0, "noncanonical_whitespace": 0, "non_nfc": 0}
    for sample_id in ids:
        seen = set()
        for clip in records[sample_id]["transcripts"]:
            index = clip["history_index"]
            if index in seen:
                raise ValueError(f"Duplicate clip index for {sample_id}: {index}")
            seen.add(index)
            raw = clip["text"]
            inventory["clips"] += 1
            inventory["not_uppercase"] += raw != raw.upper()
            inventory["noncanonical_whitespace"] += raw != " ".join(raw.split())
            inventory["non_nfc"] += raw != unicodedata.normalize("NFC", raw)
            for arm, (mode, scope, _) in ARMS.items():
                enabled = scope == "both" or (scope == "latest") == (index is None)
                formatted = transform(raw, mode) if enabled else raw
                target = next(c for c in variants[arm][sample_id]["transcripts"]
                              if c["history_index"] == index)
                target["text"] = formatted
                changed[arm]["latest" if index is None else "history"] += formatted != raw
    return variants, {"inventory": inventory, "changed_clips": changed}


class ControlledClient(LLMClient):
    """Keep the P9 client unchanged while adding and recording cache controls."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cache_prompt = False
        self.requests = []

    def generate(self, *args, **kwargs):
        wire = {}

        def controlled_urlopen(request, timeout):
            payload = json.loads(request.data)
            payload["cache_prompt"] = self.cache_prompt
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            wire["request"] = payload
            wire["wire_sha256"] = hashlib.sha256(encoded).hexdigest()
            modified = Request(request.full_url, data=encoded,
                               headers={"Content-Type": "application/json"}, method="POST")
            return urlopen(modified, timeout=timeout)

        with patch("src.llm_client.urlopen", controlled_urlopen):
            result = super().generate(*args, **kwargs)
        response = result.raw_response
        if not isinstance(response, dict) or not isinstance(response.get("timings"), dict):
            raise CacheControlError("Server response lacks cache timing telemetry")
        cached = response["timings"].get("cache_n")
        if not isinstance(cached, int) or cached < 0:
            raise CacheControlError("Server response lacks a valid cache token count")
        if not self.cache_prompt and cached != 0:
            raise CacheControlError(f"Uncached request reused {cached} prompt tokens")
        self.requests.append({**wire, "cache_n": cached,
                              "prompt_tokens": result.metrics.prompt_tokens,
                              "response": result.content})
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gguf", type=Path, required=True)
    parser.add_argument("--server-binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18088)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", type=Path,
                        help="Copy completed trajectories from an interrupted P15 run")
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit must be nonnegative")
    transcripts = ROOT / "results/p10_paired_validation_v2/trajectories.jsonl"
    p10, p11 = verify_baseline(transcripts, args.gguf, args.server_binary)
    all_ids = p10["sample_ids"]
    variants, controls = variants_for(load_transcripts(transcripts), all_ids)
    if controls["inventory"] != {"clips": 1011, "not_uppercase": 0,
                                 "noncanonical_whitespace": 0, "non_nfc": 0}:
        raise ValueError("Frozen ASR inventory differs from the predeclared P15 design")
    validation = {row["id"]: row for row in load_partition(ROOT, "validation")}
    if set(validation) != set(all_ids) or len(validation) != len(all_ids):
        raise ValueError("Validation IDs differ from the frozen manifest")
    ids = all_ids[:args.limit] if args.limit else all_ids
    rows = [validation[sample_id] for sample_id in ids]
    if not rows:
        raise ValueError("No validation samples")
    for row in rows:
        for arm in ARMS:
            mix_input(row, variants[arm][row["id"]], "asr_asr")
    args.output.mkdir(parents=True, exist_ok=False)
    config = {
        "sample_ids": ids, "arms": ARMS, "controls": controls,
        "order": "Cyclic rotation across all 13 arms by frozen sample index",
        "decoding": p11["decoding"], "sample_timeout": p11["sample_timeout"],
        "max_steps": p11["max_steps"], "seed": 20261030,
        "cache_control": "Explicit cache_prompt on each request; fail if off reports cached tokens",
        "scope": "Only ASR audio clips; historical assistant/tool text is unchanged",
        "whitespace": "Synthetic doubling of each U+0020; raw ASR already has canonical whitespace",
        "gold_use": "No references or labels in preprocessing; labels/state hashes used for post-run scoring",
        "transcripts_sha256": sha256(transcripts), "model_sha256": sha256(args.gguf),
        "server_sha256": sha256(args.server_binary), "script_sha256": sha256(Path(__file__)),
        "p14_config_sha256": sha256(ROOT / "results/p14_format_validation_v1/run_config.json"),
        "frozen_p9_code_sha256": p11["frozen_p9_code_sha256"],
        "frozen_p10_code_sha256": p11["frozen_p10_code_sha256"],
    }
    if args.resume:
        previous = json.loads((args.resume / "run_config.json").read_text(encoding="utf-8"))
        for key in ("sample_ids", "arms", "controls", "decoding", "sample_timeout", "max_steps",
                    "seed", "transcripts_sha256", "model_sha256", "server_sha256",
                    "frozen_p9_code_sha256", "frozen_p10_code_sha256"):
            if previous[key] != config[key] and not (key == "arms" and previous[key] ==
                                                       {name: list(value) for name, value in ARMS.items()}):
                raise ValueError(f"Interrupted run does not match current configuration: {key}")
        config["resumed_from"] = {
            "directory": str(args.resume),
            "configuration_sha256": sha256(args.resume / "run_config.json"),
            "trajectories_sha256": sha256(args.resume / "trajectories.jsonl"),
            "note": "The server is restarted. Completed trajectories are copied unchanged; "
                    "missing arms resume in cyclic order. Cache history after restart differs.",
        }
    (args.output / "run_config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    prompt = (ROOT / "prompts/explicit_stopping.txt").read_text(encoding="utf-8").strip()
    tool_env = tool_env_for_split(ROOT, "train")
    results = {arm: {} for arm in ARMS}
    arm_names = tuple(ARMS)
    with server(args.server_binary, args.gguf, args.port, args.output / "server.log") as (startup, command):
        client = ControlledClient(endpoint=f"http://127.0.0.1:{args.port}/v1/chat/completions",
                                  timeout=p11["sample_timeout"], decoding_mode="strict")
        with (args.output / "trajectories.jsonl").open("x", encoding="utf-8", buffering=1) as output:
            if args.resume:
                with (args.resume / "trajectories.jsonl").open(encoding="utf-8") as previous:
                    for line in previous:
                        saved = json.loads(line)
                        sample_id, arm = saved.pop("id"), saved.pop("condition")
                        if sample_id not in ids or arm not in ARMS or sample_id in results[arm]:
                            raise ValueError(f"Unexpected or duplicate resumed trajectory: {sample_id}:{arm}")
                        if any(request["request"]["cache_prompt"] is not ARMS[arm][2]
                               or (not ARMS[arm][2] and request["cache_n"] != 0)
                               for request in saved["requests"]):
                            raise ValueError(f"Invalid cached request in resumed trajectory: {sample_id}:{arm}")
                        results[arm][sample_id] = saved
                        output.write(line)
                print(json.dumps({"resumed_trajectories": sum(len(values) for values in results.values())}),
                      flush=True)
            for index, row in enumerate(rows):
                offset = index % len(arm_names)
                for arm in arm_names[offset:] + arm_names[:offset]:
                    if row["id"] in results[arm]:
                        continue
                    started = time.perf_counter()
                    item, text, history, asr_seconds, changes = mix_input(
                        row, variants[arm][row["id"]], "asr_asr"
                    )
                    if changes:
                        raise ValueError("Unexpected lexical normalization")
                    client.cache_prompt = ARMS[arm][2]
                    client.requests = []
                    result = run_trajectory(item, text, history, ROOT, "train", tool_env, client,
                                            prompt, p11["sample_timeout"], max_steps=p11["max_steps"],
                                            started=started - asr_seconds)
                    result["timing"]["asr_seconds"] = asr_seconds
                    result["requests"] = client.requests
                    if (result["status"] == "inference_error"
                            and not result["error"].startswith("ValueError: Invalid planner decision:")):
                        raise RuntimeError(f"Inference error for {row['id']}:{arm}: {result['error']}")
                    if result["status"] == "inference_error":
                        print(json.dumps({"model_inference_error": row["id"], "arm": arm,
                                          "error": result["error"]}, ensure_ascii=False), flush=True)
                    if not client.requests and result["status"] != "timeout":
                        raise RuntimeError(f"No recorded request for {row['id']}:{arm}")
                    results[arm][row["id"]] = result
                    output.write(json.dumps({"id": row["id"], "condition": arm, **result},
                                            ensure_ascii=False) + "\n")
                print(json.dumps({"completed": index + 1, "total": len(rows), "id": row["id"]}),
                      flush=True)

    results = {arm: [by_id[sample_id] for sample_id in ids] for arm, by_id in results.items()}
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
        "sentence_vs_raw_off": ("raw_off", "sentence_off"),
        "lower_vs_raw_off": ("raw_off", "lower_off"),
        "sentence_vs_lower_off": ("lower_off", "sentence_off"),
        "history_vs_raw_off": ("raw_off", "history_off"),
        "latest_vs_raw_off": ("raw_off", "latest_off"),
        "both_vs_history_off": ("history_off", "sentence_off"),
        "both_vs_latest_off": ("latest_off", "sentence_off"),
        "raw_synthetic_spacing": ("raw_off", "raw_spaced_off"),
        "sentence_synthetic_spacing": ("sentence_off", "sentence_spaced_off"),
        "sentence_vs_raw_on": ("raw_on", "sentence_on"),
        "raw_cache_on_vs_off": ("raw_off", "raw_on"),
        "sentence_cache_on_vs_off": ("sentence_off", "sentence_on"),
        "raw_repeat_off": ("raw_off", "raw_off_repeat"),
        "sentence_repeat_off": ("sentence_off", "sentence_off_repeat"),
        "raw_repeat_on": ("raw_on", "raw_on_repeat"),
        "sentence_repeat_on": ("sentence_on", "sentence_on_repeat"),
    }
    report = {"samples": len(rows), "server_initialization_seconds": startup, "server_command": command,
              "conditions": {}, "paired": {}}
    for arm in ARMS:
        scores = scored[arm]
        requests = [r for result in results[arm] for r in result["requests"]]
        report["conditions"][arm] = {
            "finished_state_gated_f1_100": 100 * sum(s["finished_score"] for s in scores) / len(scores),
            "state_matches": sum(s["state_matches"] for s in scores),
            "statuses": {status: sum(s["status"] == status for s in scores)
                         for status in sorted({s["status"] for s in scores})},
            "requests": len(requests), "requests_with_cache_reuse": sum(r["cache_n"] > 0 for r in requests),
        }
    for name, (left, right) in pairs.items():
        comparison = paired(scored[left], scored[right])
        comparison["tool_call_changes"] = sum(
            a["prediction"]["tool_calls"] != b["prediction"]["tool_calls"]
            for a, b in zip(results[left], results[right], strict=True)
        )
        comparison["prediction_changes"] = sum(
            a["prediction"] != b["prediction"]
            for a, b in zip(results[left], results[right], strict=True)
        )
        comparison["state_matches_lost"] = sum(
            a["state_matches"] and not b["state_matches"]
            for a, b in zip(scored[left], scored[right], strict=True)
        )
        comparison["state_matches_gained"] = sum(
            not a["state_matches"] and b["state_matches"]
            for a, b in zip(scored[left], scored[right], strict=True)
        )
        report["paired"][name] = comparison
    (args.output / "scores.json").write_text(json.dumps(scored, ensure_ascii=False, indent=2) + "\n")
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["conditions"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
