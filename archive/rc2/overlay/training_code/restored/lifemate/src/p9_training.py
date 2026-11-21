"""LoRA coverage and completion-only loss for the P9 experiment."""

import re

import torch
import torch.nn.functional as F
from peft import LoraConfig, get_peft_model


def attach_lora(model):
    names = []
    kinds = model.config.text_config.layer_types
    expected = []
    for index, kind in enumerate(kinds):
        prefix = f"model.language_model.layers.{index}."
        attention = (
            ["linear_attn.in_proj_qkv", "linear_attn.in_proj_z",
             "linear_attn.in_proj_b", "linear_attn.in_proj_a", "linear_attn.out_proj"]
            if kind == "linear_attention"
            else ["self_attn.q_proj", "self_attn.k_proj", "self_attn.v_proj",
                  "self_attn.o_proj"]
        )
        expected.extend(prefix + name for name in attention + [
            "mlp.gate_proj", "mlp.up_proj", "mlp.down_proj"
        ])
    modules = dict(model.named_modules())
    for name in expected:
        if not isinstance(modules.get(name), torch.nn.Linear):
            raise ValueError(f"Missing expected language linear layer: {name}")
        names.append(name)
    config = LoraConfig(
        r=16, lora_alpha=16, lora_dropout=0.0, bias="none",
        target_modules=names,
    )
    model = get_peft_model(model, config)
    trainable = [name for name, parameter in model.named_parameters()
                 if parameter.requires_grad]
    if not trainable or any("lora_" not in name for name in trainable):
        raise ValueError("Unexpected trainable parameters")
    for name in expected:
        if not any(f".{name}.lora_A." in parameter for parameter in trainable):
            raise ValueError(f"LoRA not attached to {name}")
    if any(re.search(r"\.visual\.", name) for name in trainable):
        raise ValueError("Vision parameters must remain frozen")
    return model, {"layers": len(kinds), "target_modules": len(expected),
                   "trainable_parameters": sum(p.numel() for p in model.parameters()
                                               if p.requires_grad),
                   "targets": expected}


def completion_loss(model, example, device):
    labels = example["labels"]
    first = next((i for i, label in enumerate(labels) if label != -100), None)
    if first is None or first == 0 or any(label == -100 for label in labels[first:]):
        raise ValueError("Labels must mask a nonempty prompt and supervise the suffix")
    ids = torch.tensor([example["input_ids"]], dtype=torch.long, device=device)
    target = torch.tensor(labels[first:], dtype=torch.long, device=device)
    outputs = model(input_ids=ids, use_cache=False, logits_to_keep=len(target) + 1)
    logits = outputs.logits[0, :-1, :].float()
    if logits.shape[0] != target.numel():
        raise ValueError("Completion logits do not align with target")
    return F.cross_entropy(logits, target)
