"""One-epoch BF16 generative LoRA training using the frozen P7 split."""

import argparse
import hashlib
import importlib.metadata
import json
import math
import random
import time
from pathlib import Path

import numpy as np
import torch
from transformers import AutoTokenizer, Qwen3_5ForConditionalGeneration

from src.p9_data import load_partition, planner_examples, tokenize_example
from src.p9_training import attach_lora, completion_loss


ROOT = Path(__file__).resolve().parents[1]
PINNED_SHARDS = {
    "model.safetensors-00001-of-00002.safetensors":
        "26a93f066e1916adb13453dae5a0c707c0fbc71299ed98779571a907b8e74c61",
    "model.safetensors-00002-of-00002.safetensors":
        "cb544bd9bfae93dc59b0f22b292f5933573854a7f9b97835c67060d7d910e188",
    "config.json": "ddc63e1c717afa86c865bb5e01313d89d72bb53b97ad4a8a03ba8510c0621670",
    "tokenizer_config.json": "316230d6a809701f4db5ea8f8fc862bc3a6f3229c937c174e674ff3ca0a64ac8",
    "chat_template.jinja": "a4aee8afcf2e0711942cf848899be66016f8d14a889ff9ede07bca099c28f715",
}


def digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixture-steps", type=int, default=0)
    parser.add_argument("--probe-longest", action="store_true")
    parser.add_argument("--seed", type=int, default=20261030)
    parser.add_argument("--max-length", type=int, default=8192)
    args = parser.parse_args()
    if args.fixture_steps < 0:
        parser.error("--fixture-steps must not be negative")
    if args.fixture_steps and args.probe_longest:
        parser.error("--fixture-steps and --probe-longest are mutually exclusive")
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise RuntimeError("CUDA with BF16 support is required")
    for name, expected in PINNED_SHARDS.items():
        if digest(args.model / name) != expected:
            raise ValueError(f"Pinned model file hash mismatch: {name}")
    args.output.mkdir(parents=True, exist_ok=False)
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    torch.use_deterministic_algorithms(True)
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    examples = []
    for example in planner_examples(ROOT, load_partition(ROOT, "train")):
        examples.append((example, tokenize_example(tokenizer, example, args.max_length)))
    if args.fixture_steps:
        candidates = [pair for pair in examples
                      if pair[0]["prefix"] > 0 and
                      json.loads(pair[0]["target"])["type"] == "call"]
        if not candidates:
            raise ValueError("No observation-conditioned call available for fixture")
        examples = [min(candidates, key=lambda pair: len(pair[1]["input_ids"]))]
    elif args.probe_longest:
        examples = [max(examples, key=lambda pair: len(pair[1]["input_ids"]))]
    model = Qwen3_5ForConditionalGeneration.from_pretrained(
        args.model, dtype=torch.bfloat16, local_files_only=True,
        attn_implementation="sdpa",
    ).to("cuda")
    model.config.use_cache = False
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model, coverage = attach_lora(model)
    model.train()
    optimizer = torch.optim.AdamW(
        (parameter for parameter in model.parameters() if parameter.requires_grad),
        lr=1e-4, weight_decay=0.0,
    )
    config = {
        "model": str(args.model.resolve()), "seed": args.seed, "dtype": "bfloat16",
        "rank": 16, "alpha": 16, "dropout": 0.0, "learning_rate": 1e-4,
        "microbatch": 1,
        "gradient_accumulation": 1 if args.fixture_steps or args.probe_longest else 16,
        "gradient_checkpointing": True,
        "max_length": args.max_length, "epochs": 1, "examples": len(examples),
        "fixture_steps": args.fixture_steps, "probe_longest": args.probe_longest,
        "coverage": coverage,
        "torch_version": torch.__version__,
        "model_revision": "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a",
        "model_sha256": PINNED_SHARDS,
        "split_sha256": digest(ROOT / "experiments/supervised_family_split_v2.json"),
        "prompt_sha256": digest(ROOT / "prompts/explicit_stopping.txt"),
        "requirements_sha256": digest(ROOT / "experiments/requirements-p9.txt"),
        "packages": {name: importlib.metadata.version(name) for name in
                     ("transformers", "peft", "accelerate", "flash-linear-attention")},
        "gpu": torch.cuda.get_device_name(), "cuda_version": torch.version.cuda,
    }
    (args.output / "config.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8"
    )
    order = list(range(len(examples)))
    if not args.fixture_steps:
        random.shuffle(order)
    else:
        order = [0] * args.fixture_steps
    accumulation = 1 if args.fixture_steps or args.probe_longest else 16
    accumulated = 0
    optimizer.zero_grad(set_to_none=True)
    torch.cuda.reset_peak_memory_stats()
    start = time.monotonic()
    losses = []
    log_path = args.output / "training.jsonl"
    with log_path.open("x", encoding="utf-8", buffering=1) as log:
        for position, index in enumerate(order):
            group_size = min(accumulation, len(order) - (position // accumulation) * accumulation)
            loss = completion_loss(model, examples[index][1], "cuda")
            if not torch.isfinite(loss):
                raise RuntimeError(f"Nonfinite loss at example {position}")
            (loss / group_size).backward()
            accumulated += 1
            losses.append(loss.item())
            if accumulated == group_size:
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)
                accumulated = 0
                step = math.ceil((position + 1) / accumulation)
                event = {"step": step, "examples_seen": position + 1,
                         "loss": sum(losses[-group_size:]) / group_size,
                         "elapsed_seconds": time.monotonic() - start,
                         "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
                         "peak_reserved_bytes": torch.cuda.max_memory_reserved()}
                print(json.dumps(event), flush=True)
                log.write(json.dumps(event) + "\n")
                if step % 50 == 0:
                    checkpoint = args.output / f"checkpoint-{step}"
                    model.save_pretrained(checkpoint)
                    torch.save({"optimizer": optimizer.state_dict(), "position": position,
                                "random": random.getstate(),
                                "torch_rng": torch.get_rng_state(),
                                "cuda_rng": torch.cuda.get_rng_state()},
                               checkpoint / "training_state.pt")
    if args.fixture_steps:
        example, tokens = examples[0]
        prefix_length = tokens["labels"].index(next(
            label for label in tokens["labels"] if label != -100
        ))
        model.eval()
        model.gradient_checkpointing_disable()
        with torch.inference_mode():
            generated = model.generate(
                input_ids=torch.tensor([tokens["input_ids"][:prefix_length]], device="cuda"),
                max_new_tokens=256, do_sample=False, use_cache=True,
                pad_token_id=tokenizer.eos_token_id,
            )
        response = tokenizer.decode(generated[0, prefix_length:], skip_special_tokens=True).strip()
        try:
            matched = json.loads(response) == json.loads(example["target"])
        except json.JSONDecodeError:
            matched = False
        fixture = {"id": example["id"], "prefix": example["prefix"],
                   "target": example["target"], "response": response,
                   "first_loss": losses[0], "last_loss": losses[-1],
                   "exact_json_match": matched}
        (args.output / "fixture.json").write_text(
            json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if not matched or losses[-1] >= losses[0]:
            raise RuntimeError("Overfitting fixture failed; see fixture.json")
    model.save_pretrained(args.output / "adapter")
    print(json.dumps({"completed": True, "examples": len(order),
                      "elapsed_seconds": time.monotonic() - start,
                      "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
                      "peak_reserved_bytes": torch.cuda.max_memory_reserved()}), flush=True)


if __name__ == "__main__":
    main()
