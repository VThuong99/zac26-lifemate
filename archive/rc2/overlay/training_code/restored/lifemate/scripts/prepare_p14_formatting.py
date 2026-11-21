"""Predeclare and verify token-preserving P14 ASR formatting controls."""

import argparse
import json
from pathlib import Path

from scripts.evaluate_p10 import ROOT, sha256
from scripts.evaluate_p11 import load_transcripts
from src.p14_formatting import lexical_diff, normalize_format, restore_terminal_punctuation


def prepare_records(records: dict[str, dict], ids: list[str]) -> tuple[list[dict], dict]:
    if not ids or len(ids) != len(set(ids)) or set(records) != set(ids):
        raise ValueError("Cached transcript IDs do not match the P10 validation manifest")
    rows = []
    seen = set()
    changed = {"formatting": 0, "punctuation": 0, "question_marks": 0}
    for sample_id in ids:
        record = records[sample_id]
        for clip in record["transcripts"]:
            key = (sample_id, clip["history_index"])
            if key in seen:
                raise ValueError(f"Duplicate ASR clip: {key}")
            seen.add(key)
            raw = clip["text"]
            formatted = normalize_format(raw)
            punctuated = restore_terminal_punctuation(formatted)
            b_diff, c_diff = lexical_diff(raw, formatted), lexical_diff(raw, punctuated)
            if b_diff or c_diff:
                raise ValueError(f"Lexical token modification for {key}")
            rows.append({
                "id": sample_id, "history_index": clip["history_index"], "audio": clip["audio"],
                "raw": raw, "formatting": formatted, "punctuation": punctuated,
                "formatting_lexical_diff": b_diff, "punctuation_lexical_diff": c_diff,
            })
            changed["formatting"] += formatted != raw
            changed["punctuation"] += punctuated != formatted
            changed["question_marks"] += punctuated != formatted and punctuated.endswith("?")
    return rows, {
        "samples": len(ids), "clips": len(rows),
        "changed_clips": changed,
        "formatting_lexical_differences": 0, "punctuation_lexical_differences": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcripts", type=Path,
                        default=ROOT / "results/p10_paired_validation_v2/trajectories.jsonl")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    p10 = json.loads((ROOT / "results/p10_paired_validation_v2/run_config.json").read_text())
    p11 = json.loads((ROOT / "results/p11_factorial_validation_v1/run_config.json").read_text())
    if sha256(args.transcripts) != p11["transcripts_sha256"]:
        raise ValueError("Cached ASR transcripts differ from the frozen P11 input")
    if p10["sample_ids"] != p11["sample_ids"]:
        raise ValueError("P10 and P11 sample orders differ")
    rows, counts = prepare_records(load_transcripts(args.transcripts), p10["sample_ids"])
    if counts["clips"] != 1011:
        raise ValueError("Expected the frozen 1,011-clip ASR inventory")
    args.output.mkdir(parents=True, exist_ok=False)
    with (args.output / "controls.jsonl").open("x", encoding="utf-8") as target:
        for row in rows:
            target.write(json.dumps(row, ensure_ascii=False) + "\n")
    report = {
        **counts,
        "source_sha256": sha256(args.transcripts),
        "controls_sha256": sha256(args.output / "controls.jsonl"),
        "formatting_source_sha256": sha256(ROOT / "src/p14_formatting.py"),
        "formatting": "NFC, collapse whitespace, lowercase and capitalize the first alphabetic character; "
                      "no lexical or punctuation changes.",
        "punctuation": "Add '?' for final nhỉ/hả/chăng; leave existing terminal punctuation or "
                       "other question-cue-containing text unchanged; otherwise append '.'. "
                       "No internal punctuation is restored and semantic intent is not guaranteed.",
        "token_diff": "NFC, Unicode case-folded word-token sequence compared for every clip; "
                      "all differences must be empty. Formatting also checks all non-whitespace "
                      "characters case-insensitively.",
    }
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
