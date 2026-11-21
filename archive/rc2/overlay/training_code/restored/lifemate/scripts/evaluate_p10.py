"""Paired, train-only audio-to-tool development evaluation."""

import argparse
import hashlib
import json
import random
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from scripts.run_p10_audio import ROOT, tool_env_for_split
from src.evaluate import score_sample
from src.llm_client import LLMClient
from src.p10_audio import GipformerASR, inference_input, run_audio, run_trajectory
from src.p10_metrics import analyze, summarize_analyses
from src.p9_data import load_partition
from src.tool_call_matcher import fuzzy_arguments_by_tool


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def server(binary: Path, model: Path, port: int, log_path: Path):
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
    command = [
        str(binary), "--model", str(model), "--host", "127.0.0.1", "--port", str(port),
        "--ctx-size", "8192", "--n-gpu-layers", "99", "--parallel", "1",
        "--threads", "8", "--batch-size", "512", "--ubatch-size", "512",
        "--flash-attn", "on", "--seed", "20261030", "--jinja",
    ]
    with log_path.open("x", encoding="utf-8") as log:
        started = time.perf_counter()
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = started + 120
            while True:
                if process.poll() is not None:
                    raise RuntimeError(f"llama-server exited {process.returncode}; see {log_path}")
                try:
                    with urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except (URLError, TimeoutError, ConnectionError):
                    pass
                if time.perf_counter() >= deadline:
                    raise TimeoutError(f"llama-server did not become ready; see {log_path}")
                time.sleep(0.1)
            yield time.perf_counter() - started, command
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def timing_summary(results: list[dict]) -> dict:
    fields = ("total_seconds", "asr_seconds", "setup_seconds", "decision_seconds",
              "tool_validation_seconds", "tool_call_seconds", "agent_seconds", "hash_seconds")
    summary = {}
    for field in fields:
        values = sorted(item["timing"].get(field, 0.0) for item in results)
        summary[field] = {
            "mean": sum(values) / len(values),
            "p95": values[max(0, (95 * len(values) + 99) // 100 - 1)],
            "max": values[-1],
        }
    return summary


def paired_summary(pairs: list[dict]) -> dict:
    def mean(arm, metric):
        return sum(pair[arm][metric] for pair in pairs) / len(pairs)

    return {
        "samples": len(pairs),
        "reference_finished_state_gated_f1_100": 100 * mean("reference", "finished_score"),
        "asr_finished_state_gated_f1_100": 100 * mean("asr", "finished_score"),
        "reference_state_matches": sum(p["reference"]["state_matches"] for p in pairs),
        "asr_state_matches": sum(p["asr"]["state_matches"] for p in pairs),
        "same_tool_calls": sum(p["same_tool_calls"] for p in pairs),
        "same_state_hash": sum(p["same_state_hash"] for p in pairs),
        "asr_score_regressed": sum(p["asr"]["finished_score"] < p["reference"]["finished_score"]
                                   for p in pairs),
        "asr_score_improved": sum(p["asr"]["finished_score"] > p["reference"]["finished_score"]
                                  for p in pairs),
        "reference_statuses": {status: sum(p["reference"]["status"] == status for p in pairs)
                               for status in sorted({p["reference"]["status"] for p in pairs})},
        "asr_statuses": {status: sum(p["asr"]["status"] == status for p in pairs)
                         for status in sorted({p["asr"]["status"] for p in pairs})},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--gguf", type=Path, required=True)
    parser.add_argument("--server-binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0, help="0 evaluates all validation samples")
    parser.add_argument("--seed", type=int, default=20261030)
    parser.add_argument("--sample-timeout", type=float, default=30)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()
    if args.limit < 0 or args.sample_timeout <= 0 or args.threads < 1:
        parser.error("limit must be nonnegative and timeout and threads must be positive")

    rows = load_partition(ROOT, "validation")
    random.Random(args.seed).shuffle(rows)
    if args.limit:
        rows = rows[:args.limit]
    if not rows:
        parser.error("No validation samples")
    args.output.mkdir(parents=True, exist_ok=False)
    tool_env = tool_env_for_split(ROOT, "train")
    prompt = (ROOT / "prompts/explicit_stopping.txt").read_text(encoding="utf-8").strip()
    prompt_path = ROOT / "prompts/explicit_stopping.txt"
    config = {
        "partition": "P9 frozen development validation", "sample_ids": [r["id"] for r in rows],
        "selection_seed": args.seed, "sample_timeout": args.sample_timeout,
        "asr_model_revision": "dd9227dcd8705c13f33bdbe59728d546ab94480f",
        "asr_decoding": "greedy_search, FP32 CPU", "asr_threads": args.threads,
        "llm_decoding": "greedy strict JSON", "max_steps": 7,
        "model_files_sha256": {name: sha256(args.model_dir / name) for name in
                               ("encoder.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt")},
        "gguf_sha256": sha256(args.gguf),
        "server_binary_sha256": sha256(args.server_binary),
        "dataset_sha256": sha256(ROOT / "train/train.jsonl"),
        "split_sha256": sha256(ROOT / "experiments/supervised_family_split_v2.json"),
        "prompt_sha256": sha256(prompt_path),
        "python": sys.version,
    }
    (args.output / "run_config.json").write_text(json.dumps(config, indent=2) + "\n")
    with server(args.server_binary, args.gguf, args.port, args.output / "server.log") as (server_init, command):
        asr_started = time.perf_counter()
        asr = GipformerASR(args.model_dir, args.threads)
        asr_init = time.perf_counter() - asr_started
        client = LLMClient(endpoint=f"http://127.0.0.1:{args.port}/v1/chat/completions",
                           timeout=args.sample_timeout, decoding_mode="strict")
        results = {"reference": [], "asr": []}
        with (args.output / "trajectories.jsonl").open("x", encoding="utf-8", buffering=1) as output:
            for index, row in enumerate(rows):
                item = inference_input(row)
                arm_order = ("reference", "asr") if index % 2 == 0 else ("asr", "reference")
                for arm in arm_order:
                    if arm == "reference":
                        result = run_trajectory(item, row["audio_text"], row["history"], ROOT,
                                                "train", tool_env, client, prompt,
                                                args.sample_timeout)
                    else:
                        result = run_audio(item, ROOT, "train", asr, tool_env, client, prompt,
                                           args.sample_timeout)
                    results[arm].append(result)
                    output.write(json.dumps({"id": row["id"], "arm": arm, **result},
                                            ensure_ascii=False) + "\n")
                    print(json.dumps({"index": index + 1, "id": row["id"], "arm": arm,
                                      "status": result["status"], "error": result["error"],
                                      "seconds": result["timing"]["total_seconds"]}), flush=True)

    # Gold tool labels and hashes are consulted only after both arms finish.
    hashes = json.loads((ROOT / "results/golden_state_hashes.json").read_text(encoding="utf-8"))
    catalog = json.loads((ROOT / "train/train_tools_catalog.json").read_text(encoding="utf-8"))
    fuzzy = fuzzy_arguments_by_tool(catalog)
    pairs, all_analyses, latest_analyses, history_analyses = [], [], [], []
    with (args.output / "asr_analysis.jsonl").open("x", encoding="utf-8") as output:
        for row, ref, audio in zip(rows, results["reference"], results["asr"], strict=True):
            scores = {}
            for arm, result in (("reference", ref), ("asr", audio)):
                prediction = result["prediction"]
                score = score_sample(row["label"]["tool_calls"], prediction["tool_calls"],
                                     prediction["state_hash"] == hashes[row["id"]], fuzzy)
                scores[arm] = {"status": result["status"], **score,
                               "finished_score": score["score"] if result["status"] == "finished" else 0.0}
            pair = {
                "id": row["id"], **scores,
                "same_tool_calls": ref["prediction"]["tool_calls"] == audio["prediction"]["tool_calls"],
                "same_state_hash": ref["prediction"]["state_hash"] == audio["prediction"]["state_hash"],
            }
            pairs.append(pair)
            for clip in audio["transcripts"]:
                idx = clip["history_index"]
                reference = row["audio_text"] if idx is None else row["history"][idx]["audio_text"]
                analysis = analyze(reference, clip["text"])
                all_analyses.append(analysis)
                (latest_analyses if idx is None else history_analyses).append(analysis)
                output.write(json.dumps({"id": row["id"], "history_index": idx,
                                         "reference": reference, "transcript": clip["text"],
                                         **analysis}, ensure_ascii=False) + "\n")
    for arm in ("reference", "asr"):
        with (args.output / f"{arm}_predictions.jsonl").open("x", encoding="utf-8") as output:
            for result in results[arm]:
                output.write(json.dumps(result["prediction"], ensure_ascii=False) + "\n")
    (args.output / "paired_samples.json").write_text(
        json.dumps(pairs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mean_total = timing_summary(results["asr"])["total_seconds"]["mean"]
    report = {
        "paired": paired_summary(pairs),
        "asr_all_turns": summarize_analyses(all_analyses),
        "asr_latest_turns": summarize_analyses(latest_analyses),
        "asr_history_turns": summarize_analyses(history_analyses),
        "reference_timing": timing_summary(results["reference"]),
        "audio_timing": timing_summary(results["asr"]),
        "initialization": {"llama_server_seconds": server_init, "asr_seconds": asr_init,
                           "cold_first_audio_total_seconds": server_init + asr_init +
                           results["asr"][0]["timing"]["total_seconds"],
                           "amortized_audio_mean_seconds": mean_total +
                           (server_init + asr_init) / len(rows)},
        "llama_server_command": command,
        "audio_finished_within_30_seconds": sum(
            r["status"] == "finished" and r["timing"]["total_seconds"] <= 30
            for r in results["asr"]),
    }
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                             encoding="utf-8")
    print(json.dumps({"paired": report["paired"], "asr_latest_turns": report["asr_latest_turns"],
                      "initialization": report["initialization"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
