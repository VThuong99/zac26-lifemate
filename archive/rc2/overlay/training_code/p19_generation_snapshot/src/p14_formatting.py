"""Token-preserving, deterministic text-formatting interventions."""

import difflib
import unicodedata

from src.p10_metrics import words


QUESTION_ENDINGS = frozenset({"nhỉ", "hả", "chăng"})
AMBIGUOUS_QUESTION_WORDS = frozenset({
    "không", "chưa", "ai", "nào", "gì", "mấy", "sao", "thế", "ư", "à",
    "bao", "chứ", "có",
})


def lexical_diff(left: str, right: str) -> list[dict]:
    original, transformed = words(left), words(right)
    return [
        {"operation": op, "original": original[i1:i2], "transformed": transformed[j1:j2]}
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, original, transformed, autojunk=False
        ).get_opcodes() if op != "equal"
    ]


def normalize_format(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Transcript must be a nonempty string")
    collapsed = " ".join(unicodedata.normalize("NFC", text).split())
    normalized = collapsed.lower()
    for index, character in enumerate(normalized):
        if character.isalpha():
            normalized = normalized[:index] + character.upper() + normalized[index + 1:]
            break
    if unicodedata.normalize("NFC", normalized.casefold()) != unicodedata.normalize("NFC", collapsed.casefold()):
        raise ValueError("Formatting changed non-case content")
    if lexical_diff(text, normalized):
        raise ValueError("Formatting changed lexical tokens")
    return normalized


def restore_terminal_punctuation(formatted: str) -> str:
    if not isinstance(formatted, str) or not formatted.strip():
        raise ValueError("Formatted transcript must be nonempty")
    tokens = words(formatted)
    if not tokens:
        raise ValueError("Formatted transcript has no lexical tokens")
    if formatted[-1] in ".?!":
        return formatted
    if tokens[-1] in QUESTION_ENDINGS:
        suffix = "?"
    elif set(tokens) & AMBIGUOUS_QUESTION_WORDS:
        return formatted
    else:
        suffix = "."
    result = formatted + suffix
    if lexical_diff(formatted, result):
        raise ValueError("Punctuation changed lexical tokens")
    return result
