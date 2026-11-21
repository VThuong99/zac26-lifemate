"""Construct real-ASR adaptations without changing training targets."""
import json
from scripts.evaluate_p15_robustness import transform
from src.p19_format_training import format_example


def real_asr_example(original, asr_text):
    example = format_example(original)
    payload = json.loads(example['messages'][1]['content'])
    payload['user_request'] = transform(asr_text, 'sentence')
    example['messages'][1]['content'] = json.dumps(payload, ensure_ascii=False)
    if example['target'] != original['target']:
        raise ValueError('training target changed')
    return example
