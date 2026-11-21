"""Conservative transcript number rendering and separate WER normalization."""

import re
import unicodedata


_DIGITS = {
    "một": 1, "hai": 2, "ba": 3, "bốn": 4, "năm": 5,
    "sáu": 6, "bảy": 7, "tám": 8, "chín": 9,
}
_LAST_AFTER_TEN = {key: value for key, value in _DIGITS.items() if key != "năm"} | {"lăm": 5}
_LAST_AFTER_TENS = {**_LAST_AFTER_TEN, "mốt": 1, "tư": 4}
_NUMBER_TOKENS = set(_DIGITS) | {
    "không", "mười", "mươi", "trăm", "linh", "lẻ", "mốt", "tư", "lăm",
    "chục", "phẩy", "rưỡi", "nửa",
}
_SUFFIX_UNITS = {"giờ", "phút", "giây", "đồng", "nghìn", "ngàn", "triệu", "tỷ", "độ"}
_DATE_PREFIXES = {"ngày", "tháng"}
_BLOCK_BEFORE = _NUMBER_TOKENS | {"thứ", "số", "mã"}
_BLOCK_AFTER = {"phẩy", "rưỡi"}
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_PLAIN_INTEGER = re.compile(r"(?<![\w.,:/-])\d{1,9}(?![\w.,:/-])")
_SPOKEN = ("không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín")


def parse_under_1000(tokens: list[str]) -> int | None:
    """Parse only complete, unambiguous Vietnamese cardinal sequences."""
    if not tokens:
        return None
    hundred = 0
    if len(tokens) >= 2 and tokens[0] in _DIGITS and tokens[1] == "trăm":
        hundred = _DIGITS[tokens[0]] * 100
        tokens = tokens[2:]
        if not tokens:
            return hundred
        if tokens[0] in {"linh", "lẻ"}:
            return hundred + _DIGITS[tokens[1]] if len(tokens) == 2 and tokens[1] in _DIGITS else None
        # A bare digit after "trăm" can mean either units or tens.
        if len(tokens) == 1 and tokens[0] in _DIGITS:
            return None
    if len(tokens) == 1 and tokens[0] in _DIGITS:
        return hundred + _DIGITS[tokens[0]]
    if tokens[0] == "mười" and len(tokens) <= 2:
        if len(tokens) == 1:
            return hundred + 10
        if tokens[1] in _LAST_AFTER_TEN:
            return hundred + 10 + _LAST_AFTER_TEN[tokens[1]]
    if len(tokens) in (2, 3) and tokens[0] in _DIGITS and tokens[1] == "mươi":
        result = hundred + 10 * _DIGITS[tokens[0]]
        if len(tokens) == 2:
            return result
        if tokens[2] in _LAST_AFTER_TENS:
            return result + _LAST_AFTER_TENS[tokens[2]]
    return None


def normalize_transcript(text: str) -> tuple[str, list[dict]]:
    """Render explicit cardinal numbers near units, leaving ambiguity intact."""
    matches = list(_TOKEN.finditer(text))
    tokens = [unicodedata.normalize("NFC", match.group()).casefold() for match in matches]
    changes = []
    i = 0
    while i < len(tokens):
        if tokens[i] not in _NUMBER_TOKENS:
            i += 1
            continue
        start = i
        while (i + 1 < len(tokens) and tokens[i + 1] in _NUMBER_TOKENS
               and text[matches[i].end():matches[i + 1].start()].isspace()):
            i += 1
        end = i + 1
        before = tokens[start - 1] if start else None
        after = tokens[end] if end < len(tokens) else None
        suffix = after in _SUFFIX_UNITS
        if after == "phần" and end + 1 < len(tokens) and tokens[end + 1] == "trăm":
            suffix = True
        date_prefix = before in _DATE_PREFIXES
        gap_before = text[matches[start - 1].end():matches[start].start()] if start else ""
        gap_after = text[matches[end - 1].end():matches[end].start()] if end < len(tokens) else ""
        adjacent_prefix = bool(date_prefix and gap_before.isspace())
        adjacent_suffix = bool(suffix and gap_after.isspace())
        blocked_before = before in _BLOCK_BEFORE and gap_before.isspace()
        next_after_unit = tokens[end + 1] if end + 1 < len(tokens) else None
        blocked_after = adjacent_suffix and next_after_unit in _BLOCK_AFTER
        value = parse_under_1000(tokens[start:end])
        if value is not None and not blocked_before and not blocked_after and (
            adjacent_prefix or adjacent_suffix
        ):
            changes.append({"start": matches[start].start(), "end": matches[end - 1].end(),
                            "source": text[matches[start].start():matches[end - 1].end()],
                            "replacement": str(value)})
        i = end
    output = text
    for change in reversed(changes):
        output = output[:change["start"]] + change["replacement"] + output[change["end"]:]
    return output, changes


def _under_1000(value: int, full: bool = False) -> list[str]:
    hundred, rest = divmod(value, 100)
    result = []
    if hundred or full:
        result.extend([_SPOKEN[hundred], "trăm"])
        if 0 < rest < 10:
            result.append("lẻ")
    tens, unit = divmod(rest, 10)
    if tens == 1:
        result.append("mười")
    elif tens > 1:
        result.extend([_SPOKEN[tens], "mươi"])
    if unit:
        if tens > 1 and unit == 1:
            result.append("mốt")
        elif tens and unit == 5:
            result.append("lăm")
        else:
            result.append(_SPOKEN[unit])
    return result


def integer_to_spoken(value: int) -> str:
    if not 0 <= value < 1_000_000_000:
        raise ValueError("Only integers from 0 to 999999999 are supported")
    if value == 0:
        return "không"
    millions, rem = divmod(value, 1_000_000)
    thousands, units = divmod(rem, 1000)
    result = []
    if millions:
        result.extend(_under_1000(millions) + ["triệu"])
    if thousands:
        result.extend(_under_1000(thousands, full=bool(millions)) + ["nghìn"])
    if units:
        result.extend(_under_1000(units, full=bool(millions or thousands)))
    return " ".join(result)


def spoken_number_metric_text(text: str) -> str:
    """Expand standalone integer digits in both sides of ASR metrics only."""
    def replace(match):
        digits = match.group()
        if len(digits) > 1 and digits.startswith("0"):
            return digits
        return integer_to_spoken(int(digits))

    return _PLAIN_INTEGER.sub(replace, unicodedata.normalize("NFC", text))
