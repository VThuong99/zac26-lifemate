"""Local, schema-constrained HF inference client for paired P9 evaluation."""

import copy
import time

import torch
from lmformatenforcer import JsonSchemaParser
from lmformatenforcer.tokenenforcer import TokenEnforcer, TokenEnforcerTokenizerData
from transformers import StoppingCriteria, StoppingCriteriaList

from src.llm_client import DECISION_SCHEMA, InferenceMetrics, InferenceResult


def tokenizer_data(tokenizer):
    zero = tokenizer.encode("0", add_special_tokens=False)[-1]
    special = set(tokenizer.all_special_ids)
    tokens = []
    for token_id in range(len(tokenizer)):
        if token_id not in special:
            standalone = tokenizer.decode([token_id])
            after_zero = tokenizer.decode([zero, token_id])[1:]
            tokens.append((token_id, after_zero, len(after_zero) > len(standalone)))
    return TokenEnforcerTokenizerData(
        tokens, lambda ids: tokenizer.decode(ids).rstrip("\ufffd"),
        tokenizer.eos_token_id, False, len(tokenizer)
    )


def decision_schema():
    schema = copy.deepcopy(DECISION_SCHEMA)
    schema["oneOf"][1]["properties"]["arguments"]["additionalProperties"] = {
        "anyOf": [{"type": kind} for kind in
                  ("string", "number", "boolean", "null", "object", "array")]
    }
    return schema


class Deadline(StoppingCriteria):
    def __init__(self, deadline):
        self.deadline = deadline

    def __call__(self, input_ids, scores, **kwargs):
        return torch.full((input_ids.shape[0],), time.monotonic() >= self.deadline,
                          dtype=torch.bool, device=input_ids.device)


class P9Client:
    def __init__(self, model, tokenizer, token_data):
        self.model = model
        self.tokenizer = tokenizer
        self.token_data = token_data

    def generate(self, messages, timeout=None):
        started = time.monotonic()
        deadline = started + timeout if timeout is not None else float("inf")
        input_ids = self.tokenizer.apply_chat_template(
            messages, tokenize=True, return_dict=False, enable_thinking=False,
            add_generation_prompt=True,
        )
        if len(input_ids) + 256 > 8192:
            raise ValueError(f"Inference prompt exceeds context budget: {len(input_ids)}")
        enforcer = TokenEnforcer(self.token_data, JsonSchemaParser(decision_schema()))
        inputs = torch.tensor([input_ids], device="cuda")
        with torch.inference_mode():
            output = self.model.generate(
                input_ids=inputs, max_new_tokens=256, do_sample=False, use_cache=True,
                pad_token_id=self.tokenizer.eos_token_id,
                prefix_allowed_tokens_fn=lambda batch, sent:
                    enforcer.get_allowed_tokens(sent.tolist()).allowed_tokens,
                stopping_criteria=StoppingCriteriaList([Deadline(deadline)]),
            )
        elapsed = time.monotonic() - started
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Local inference exceeded {timeout} seconds")
        generated = output[0, len(input_ids):]
        content = self.tokenizer.decode(generated, skip_special_tokens=True).strip()
        return InferenceResult(
            content=content, finish_reason="stop",
            metrics=InferenceMetrics(
                wall_ms=elapsed * 1000, prompt_tokens=len(input_ids),
                output_tokens=len(generated), prompt_ms=None, decode_ms=None
            )
        )
