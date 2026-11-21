"""Merge a trained P9 adapter into its pinned BF16 base and verify inference."""

import argparse
import json
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoTokenizer, Qwen3_5ForConditionalGeneration

from src.decision_parser import parse_decision
from src.p9_data import load_partition, planner_examples
from src.p9_inference import P9Client, tokenizer_data
from scripts.train_p9 import PINNED_SHARDS, ROOT, digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for name, expected in PINNED_SHARDS.items():
        if digest(args.model / name) != expected:
            raise ValueError(f"Pinned model file hash mismatch: {name}")
    args.output.mkdir(parents=True, exist_ok=False)
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    base = Qwen3_5ForConditionalGeneration.from_pretrained(
        args.model, dtype=torch.bfloat16, local_files_only=True,
        attn_implementation="sdpa"
    ).to("cuda")
    model = PeftModel.from_pretrained(base, args.adapter).eval()
    data = tokenizer_data(tokenizer)
    rows = load_partition(ROOT, "train")
    row = next(item for item in rows if item["label"]["tool_calls"])
    examples = list(planner_examples(ROOT, [row]))
    samples = [examples[0], examples[-1]]
    adapter_decisions = []
    for sample, expected_type in zip(samples, ("call", "finish"), strict=True):
        response = P9Client(model, tokenizer, data).generate(sample["messages"]).content
        decision = parse_decision(response)
        if decision["type"] != expected_type:
            raise RuntimeError(f"Trained model failed {expected_type} smoke: {response!r}")
        adapter_decisions.append(decision)
    model = model.merge_and_unload().eval()
    merged_decisions = []
    for sample, before in zip(samples, adapter_decisions, strict=True):
        response = P9Client(model, tokenizer, data).generate(sample["messages"]).content
        after = parse_decision(response)
        if before != after:
            raise RuntimeError(f"Merged model changed the strict decision: {before!r} != {after!r}")
        merged_decisions.append(after)
    model.save_pretrained(args.output, safe_serialization=True)
    tokenizer.save_pretrained(args.output)
    exported_tokenizer = AutoTokenizer.from_pretrained(args.output, local_files_only=True)
    if (exported_tokenizer.get_vocab() != tokenizer.get_vocab()
            or exported_tokenizer.chat_template != tokenizer.chat_template
            or exported_tokenizer.all_special_ids != tokenizer.all_special_ids):
        raise RuntimeError("Exported tokenizer or chat template differs from the base")
    for candidate in (tokenizer, exported_tokenizer):
        encoded = candidate.apply_chat_template(
            samples[0]["messages"], tokenize=True, return_dict=False,
            add_generation_prompt=True, enable_thinking=False
        )
        if candidate is tokenizer:
            original_ids = encoded
        elif encoded != original_ids:
            raise RuntimeError("Exported tokenizer changed the inference prompt tokens")
    (args.output / "p9_export_verification.json").write_text(json.dumps({
        "base_revision": "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a",
        "adapter": str(args.adapter.resolve()), "sample_id": row["id"],
        "prefixes": [sample["prefix"] for sample in samples],
        "adapter_decisions": adapter_decisions, "merged_decisions": merged_decisions,
        "tokenizer_and_template_match": True,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Merged model saved and strict JSON decision matched.", flush=True)


if __name__ == "__main__":
    main()
