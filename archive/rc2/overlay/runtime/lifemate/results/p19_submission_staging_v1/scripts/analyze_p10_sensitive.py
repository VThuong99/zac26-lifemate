"""Post-inference literal-marker audit; not a semantic field-error metric."""

import argparse
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

from src.p10_metrics import words

NUMBER_WORDS = {
    "không", "một", "hai", "ba", "bốn", "tư", "năm", "sáu", "bảy", "tám",
    "chín", "mười", "mươi", "trăm", "nghìn", "ngàn", "triệu", "tỷ",
    "lẻ", "linh", "rưỡi",
}
TIME_WORDS = {"ngày", "mai", "hôm", "thứ", "tháng", "năm", "giờ", "phút", "tuần"}
AMOUNT_WORDS = {"đồng", "nghìn", "ngàn", "triệu", "tỷ", "tiền"}
NEGATION_WORDS = {"không", "đừng", "chưa", "chẳng", "chớ", "khoan", "khỏi"}
CONDITION_WORDS = {"nếu", "khi", "trừ", "thì"}


def markers(reference: str) -> dict[str, set[str]]:
    tokens = words(reference)
    token_set = set(tokens)
    numeric = {token for token in token_set if token.isdecimal() or token in NUMBER_WORDS}
    original_words = re.findall(r"[^\W_]+", unicodedata.normalize("NFC", reference))
    named = {word.casefold() for word in original_words[1:] if word[0].isupper()}
    return {
        "amount_or_number": numeric | (token_set & AMOUNT_WORDS),
        "date_or_time": (token_set & TIME_WORDS) | (numeric if token_set & TIME_WORDS else set()),
        "negation": token_set & NEGATION_WORDS,
        "conditional": token_set & CONDITION_WORDS,
        "possible_named_entity": named,
    }


def audit(rows: list[dict], regressed: set[str]) -> dict:
    report = {}
    for row in rows:
        ref_counts = Counter(words(row["reference"]))
        changed = Counter(token for edit in row["differences"] for token in edit["reference"])
        for category, tokens in markers(row["reference"]).items():
            if not tokens:
                continue
            group = report.setdefault(category, {
                "utterances": 0, "marker_occurrences": 0, "edited_marker_occurrences": 0,
                "utterances_with_edited_markers": 0, "regressed_trajectory_utterances": 0,
                "examples": [],
            })
            marker_count = sum(ref_counts[token] for token in tokens)
            edit_count = sum(min(ref_counts[token], changed[token]) for token in tokens)
            group["utterances"] += 1
            group["marker_occurrences"] += marker_count
            group["edited_marker_occurrences"] += edit_count
            group["utterances_with_edited_markers"] += bool(edit_count)
            group["regressed_trajectory_utterances"] += row["id"] in regressed
            if edit_count and len(group["examples"]) < 12:
                group["examples"].append({
                    "id": row["id"], "history_index": row["history_index"],
                    "edited_markers": sorted(token for token in tokens if changed[token]),
                    "reference": row["reference"], "transcript": row["transcript"],
                    "differences": row["differences"],
                    "paired_score_regressed": row["id"] in regressed,
                })
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with (args.run / "asr_analysis.jsonl").open(encoding="utf-8") as source:
        rows = [json.loads(line) for line in source if line.strip()]
    pairs = json.loads((args.run / "paired_samples.json").read_text(encoding="utf-8"))
    regressed = {pair["id"] for pair in pairs
                 if pair["asr"]["finished_score"] < pair["reference"]["finished_score"]}
    report = {
        "method": "Heuristic literal token edits from SequenceMatcher; not semantic field error rates. "
                  "Number spelling versus digits counts as an edit. Capitalization is an imperfect "
                  "named-entity proxy. Cue words may have unrelated meanings.",
        "all_turns": audit(rows, regressed),
        "latest_turns": audit([row for row in rows if row["history_index"] is None], regressed),
        "history_turns": audit([row for row in rows if row["history_index"] is not None], regressed),
    }
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps({key: {k: v for k, v in value.items() if k != "examples"}
                      for key, value in report["all_turns"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
