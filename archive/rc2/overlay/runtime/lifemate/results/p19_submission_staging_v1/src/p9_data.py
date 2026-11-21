"""P9 teacher-forced examples using the unchanged inference planner."""

import hashlib
import json
from pathlib import Path

from src.decision_parser import parse_decision
from src.llm_planner import LLMPlanner
from src.supervised_actions import build_examples
from src.tool_catalog import load_available_tools
from src.tool_schema_formatter import compact_tools


def load_partition(root: Path, partition: str) -> list[dict]:
    dataset = root / "train" / "train.jsonl"
    manifest = json.loads(
        (root / "experiments" / "supervised_family_split_v2.json").read_text(
            encoding="utf-8"
        )
    )
    if hashlib.sha256(dataset.read_bytes()).hexdigest() != manifest["dataset_sha256"]:
        raise ValueError("Training data does not match the frozen split")
    splits = manifest["splits"]
    if partition not in ("train", "validation"):
        raise ValueError(f"Unsupported partition: {partition}")
    sets = {name: set(ids) for name, ids in splits.items()}
    if any(len(sets[name]) != len(ids) for name, ids in splits.items()):
        raise ValueError("Duplicate IDs in split")
    names = list(sets)
    if any(sets[a] & sets[b] for i, a in enumerate(names) for b in names[i + 1:]):
        raise ValueError("Split partitions overlap")
    for group in manifest["groups"]:
        if sum(bool(set(group) & ids) for ids in sets.values()) > 1:
            raise ValueError("A request family crosses split partitions")
    rows = []
    seen = set()
    with dataset.open(encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            row = json.loads(line)
            if row["id"] in seen:
                raise ValueError(f"Duplicate dataset ID: {row['id']}")
            seen.add(row["id"])
            if row["id"] in sets[partition]:
                rows.append(row)
    if seen != set().union(*sets.values()):
        raise ValueError("Frozen split IDs do not match dataset IDs")
    return rows


def planner_examples(root: Path, rows: list[dict]):
    prompt = (root / "prompts" / "explicit_stopping.txt").read_text(
        encoding="utf-8"
    ).strip()
    for row in rows:
        tools = load_available_tools(root, "train", row["context"])
        planner = LLMPlanner(tools, tool_formatter=compact_tools, system_prompt=prompt)
        for example in build_examples(row):
            messages = planner._custom_messages(
                example["text"], example["context"], example["history"]
            )
            target = json.dumps(example["target"], ensure_ascii=False, separators=(",", ":"))
            if parse_decision(target) != example["target"]:
                raise ValueError(f"Invalid target for {example['id']}")
            yield {"id": example["id"], "prefix": example["prefix"],
                   "messages": messages, "target": target}


def tokenize_example(tokenizer, example: dict, max_length: int) -> dict:
    options = {"enable_thinking": False}
    prefix_text = tokenizer.apply_chat_template(
        example["messages"], tokenize=False, add_generation_prompt=True, **options
    )
    complete_text = tokenizer.apply_chat_template(
        example["messages"] + [{"role": "assistant", "content": example["target"]}],
        tokenize=False, add_generation_prompt=False, **options
    )
    if not complete_text.startswith(prefix_text):
        raise ValueError(
            f"Chat template prefix mismatch for {example['id']}:{example['prefix']}"
        )
    prefix = tokenizer.apply_chat_template(
        example["messages"], tokenize=True, return_dict=False,
        add_generation_prompt=True, **options
    )
    completion = tokenizer.encode(complete_text[len(prefix_text):], add_special_tokens=False)
    if not completion:
        raise ValueError("Empty completion")
    complete = prefix + completion
    if len(complete) > max_length:
        raise ValueError(
            f"Example {example['id']}:{example['prefix']} has {len(complete)} "
            f"tokens, exceeding {max_length}; truncation would change the prompt"
        )
    return {"input_ids": complete, "attention_mask": [1] * len(complete),
            "labels": [-100] * len(prefix) + completion}
