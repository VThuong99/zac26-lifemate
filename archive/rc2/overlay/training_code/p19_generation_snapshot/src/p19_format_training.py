"""Train-only text formatting; never infer or substitute speech content."""
import copy
import hashlib
import json
import re
import unicodedata

from src.p14_formatting import normalize_format

SALT = 'p19-format-v1:'


def selected(sample_id):
    return int(hashlib.sha256((SALT + sample_id).encode()).hexdigest()[:8], 16) % 3 == 0


def format_written(text, latest):
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Expected nonempty written input')
    text = unicodedata.normalize('NFC', text)
    chars = []
    for index, char in enumerate(text):
        if char in ',.?!:;' and not (index > 0 and index + 1 < len(text)
                                     and text[index - 1].isdigit() and text[index + 1].isdigit()):
            chars.append(' ')
        else:
            chars.append(char)
    stripped = ' '.join(''.join(chars).split())
    result = normalize_format(stripped) if latest else stripped.upper()
    def words(value):
        return re.findall(r'\w+', unicodedata.normalize('NFC', value).casefold())
    if words(text) != words(result):
        raise ValueError('Formatting changed words or digits')
    numbers = lambda value: re.findall(r'\d+(?:[,.]+\d+)*', value)
    if numbers(text) != numbers(result):
        raise ValueError('Formatting changed a numeric expression')
    return result


def format_example(example):
    example = copy.deepcopy(example)
    payload = json.loads(example['messages'][1]['content'])
    payload['user_request'] = format_written(payload['user_request'], latest=True)
    for turn in payload['previous_steps']:
        if turn.get('role') == 'user' and 'audio' in turn:
            turn['audio_text'] = format_written(turn['audio_text'], latest=False)
    example['messages'][1]['content'] = json.dumps(payload, ensure_ascii=False)
    return example
