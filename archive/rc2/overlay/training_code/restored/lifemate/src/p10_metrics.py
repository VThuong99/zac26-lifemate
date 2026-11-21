"""Transparent ASR edit metrics and heuristic task-sensitive triage."""

import difflib
import re
import unicodedata
from collections import Counter


def words(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text).casefold()
    return re.findall(r"[^\W_]+", text, flags=re.UNICODE)


def edits(reference: list[str], hypothesis: list[str]) -> dict:
    # Dynamic programming computes true Levenshtein counts, not SequenceMatcher's
    # approximate alignment. Prefer substitutions on equal-cost paths.
    table = [[(0, 0, 0)] * (len(hypothesis) + 1) for _ in range(len(reference) + 1)]
    for i in range(len(reference) + 1):
        table[i][0] = (0, i, 0)
    for j in range(len(hypothesis) + 1):
        table[0][j] = (0, 0, j)
    for i, ref in enumerate(reference, 1):
        for j, hyp in enumerate(hypothesis, 1):
            s, d, ins = table[i - 1][j - 1]
            diagonal = (s + (ref != hyp), d, ins)
            s, d, ins = table[i - 1][j]
            deletion = (s, d + 1, ins)
            s, d, ins = table[i][j - 1]
            insertion = (s, d, ins + 1)
            table[i][j] = min((diagonal, deletion, insertion), key=sum)
    s, d, ins = table[-1][-1]
    return {"substitutions": s, "deletions": d, "insertions": ins,
            "reference_units": len(reference), "errors": s + d + ins}


def sensitive_categories(reference: str) -> list[str]:
    tokens = words(reference)
    token_set = set(tokens)
    categories = []
    if any(token.isdecimal() for token in tokens) or token_set & {
        "nghìn", "ngàn", "triệu", "tỷ", "đồng", "trăm", "mươi",
    }:
        categories.append("amount_or_number")
    if token_set & {"ngày", "mai", "hôm", "thứ", "tháng", "năm", "giờ", "phút"}:
        categories.append("date_or_time")
    if token_set & {"không", "đừng", "chưa", "chẳng", "chớ"}:
        categories.append("negation")
    if token_set & {"nếu", "khi", "trừ"}:
        categories.append("conditional")
    raw_words = re.findall(r"[^\W_]+", unicodedata.normalize("NFC", reference))
    if any(word[0].isupper() for word in raw_words[1:] if word):
        categories.append("possible_named_entity")
    return categories


def analyze(reference: str, hypothesis: str) -> dict:
    ref_words, hyp_words = words(reference), words(hypothesis)
    ref_chars = list("".join(ref_words))
    hyp_chars = list("".join(hyp_words))
    differences = [
        {"reference": ref_words[i1:i2], "hypothesis": hyp_words[j1:j2], "operation": op}
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, ref_words, hyp_words, autojunk=False
        ).get_opcodes() if op != "equal"
    ]
    return {"word_edits": edits(ref_words, hyp_words),
            "character_edits": edits(ref_chars, hyp_chars),
            "categories": sensitive_categories(reference), "differences": differences}


def summarize_analyses(analyses: list[dict]) -> dict:
    word_totals = Counter()
    char_totals = Counter()
    categories = {}
    for analysis in analyses:
        word_totals.update(analysis["word_edits"])
        char_totals.update(analysis["character_edits"])
        for category in analysis["categories"]:
            group = categories.setdefault(category, {"utterances": 0, "utterances_with_edits": 0,
                                                       "word_errors": 0, "reference_words": 0})
            group["utterances"] += 1
            group["utterances_with_edits"] += bool(analysis["word_edits"]["errors"])
            group["word_errors"] += analysis["word_edits"]["errors"]
            group["reference_words"] += analysis["word_edits"]["reference_units"]
    for group in categories.values():
        group["wer"] = (group["word_errors"] / group["reference_words"]
                        if group["reference_words"] else None)
    return {
        "utterances": len(analyses), "word_edits": dict(word_totals),
        "character_edits": dict(char_totals),
        "wer": word_totals["errors"] / word_totals["reference_units"]
        if word_totals["reference_units"] else None,
        "cer": char_totals["errors"] / char_totals["reference_units"]
        if char_totals["reference_units"] else None,
        "categories": categories,
    }
