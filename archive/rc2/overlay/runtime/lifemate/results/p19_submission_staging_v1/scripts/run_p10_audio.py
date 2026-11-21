"""Run one audio-bearing sample through the existing agent and organizer ToolEnv."""

import argparse
import importlib
import ipaddress
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from src.llm_client import LLMClient
from src.p10_audio import GipformerASR, inference_input, run_audio

ROOT = Path(__file__).resolve().parents[1]


def check_local_endpoint(endpoint: str) -> None:
    parsed = urlsplit(endpoint)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("LLM endpoint must be a local HTTP(S) URL")
    if parsed.hostname == "localhost":
        return
    try:
        is_loopback = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError as exc:
        raise ValueError("LLM endpoint must use a loopback address") from exc
    if not is_loopback:
        raise ValueError("LLM endpoint must use a loopback address")


def tool_env_for_split(root: Path, split: str):
    if not split or Path(split).name != split or split in (".", ".."):
        raise ValueError("Invalid split name")
    split_dir = (root / split).resolve()
    sys.path.insert(0, str(split_dir))
    module = importlib.import_module("zaic_tools")
    if not Path(module.__file__).resolve().is_relative_to(split_dir):
        raise RuntimeError("A different split's zaic_tools is already loaded")
    return module.ToolEnv


def load_input(root: Path, split: str, sample_id: str) -> dict:
    with (root / split / f"{split}.jsonl").open(encoding="utf-8") as source:
        for line in source:
            if line.strip():
                row = json.loads(line)
                if row["id"] == sample_id:
                    return inference_input(row)
    raise ValueError(f"Sample not found: {sample_id}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--split", required=True)
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8080/v1/chat/completions")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--sample-timeout", type=float, default=30)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    if args.sample_timeout <= 0:
        parser.error("--sample-timeout must be positive")
    check_local_endpoint(args.endpoint)

    tool_env = tool_env_for_split(args.root, args.split)
    item = load_input(args.root, args.split, args.sample_id)
    started = time.perf_counter()
    asr = GipformerASR(args.model_dir, args.threads)
    init_seconds = time.perf_counter() - started
    client = LLMClient(endpoint=args.endpoint, timeout=args.sample_timeout, decoding_mode="strict")
    prompt = (ROOT / "prompts/explicit_stopping.txt").read_text(encoding="utf-8").strip()
    result = run_audio(item, args.root, args.split, asr, tool_env, client, prompt,
                       args.sample_timeout)
    result["timing"]["asr_initialization_seconds"] = init_seconds
    with args.output.open("x", encoding="utf-8") as output:
        output.write(json.dumps(result["prediction"], ensure_ascii=False) + "\n")
    with args.trace.open("x", encoding="utf-8") as trace:
        json.dump(result, trace, ensure_ascii=False, indent=2)
        trace.write("\n")
    print(json.dumps({"id": item["id"], "status": result["status"],
                      "error": result["error"], "timing": result["timing"]},
                     ensure_ascii=False))
    if result["status"] != "finished":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
