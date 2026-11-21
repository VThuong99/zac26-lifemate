"""Bounded offline LoRA adaptation with original and gated real-ASR inputs."""
import argparse
import hashlib
import json
import math
import os
import random
import subprocess
import time
from pathlib import Path

import numpy as np
import torch
from transformers import AutoTokenizer, Qwen3_5ForConditionalGeneration

from scripts.train_p9 import ROOT, digest
from src.p19_format_training import selected
from src.p19_real_asr_training import real_asr_example
from src.p9_data import load_partition, planner_examples, tokenize_example
from src.p9_training import attach_lora, completion_loss

EXPECTED = 'f8d3ddf17460618aada6d8e8ec8bd1d6b735a207612e2b282773eecf4bde6045'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise RuntimeError('CUDA with BF16 support is required')
    if digest(args.model / 'model.safetensors') != EXPECTED:
        raise ValueError('Merged P9 base weights mismatch')
    args.output.mkdir(parents=True, exist_ok=False)
    seed = 20261031
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed); torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    rows = [r for r in load_partition(ROOT, 'train') if selected(r['id'])]
    if len(rows) != 374:
        raise ValueError('Unexpected fixed training selection size')
    gate_path = ROOT / 'results/p19_real_asr_training_gate_v1/transcripts.jsonl'
    gate_report = json.loads((gate_path.parent / 'report.json').read_text())
    if not gate_report['feasible'] or digest(gate_path) != gate_report['transcripts_sha256']:
        raise ValueError('ASR gate is not feasible or changed')
    gate_rows = [json.loads(line) for line in gate_path.read_text().splitlines() if line.strip()]
    if len(gate_rows) != 374 or len({r['id'] for r in gate_rows}) != 374:
        raise ValueError('Invalid gated transcript coverage')
    asr = {r['id']: r['asr_text'] for r in gate_rows if r['eligible']}
    if len(asr) != 120 or not set(asr) <= {r['id'] for r in rows}:
        raise ValueError('Unexpected eligible training IDs')
    examples = []
    example_hash = hashlib.sha256()
    max_tokens = 0
    real_count = 0
    for original in planner_examples(ROOT, rows):
        variants = [original]
        if original['id'] in asr:
            variants.append(real_asr_example(original, asr[original['id']]))
            real_count += 1
        for example in variants:
            tokenized = tokenize_example(tokenizer, example, 8192)
            max_tokens = max(max_tokens, len(tokenized['input_ids']))
            example_hash.update(json.dumps(example, ensure_ascii=False, sort_keys=True).encode() + b'\n')
            examples.append(tokenized)
    if len(examples) != 1571 or real_count != 373:
        raise ValueError('Unexpected fixed training example count')
    config = {'model': str(args.model.resolve()), 'model_sha256': EXPECTED,
              'model_metadata_sha256': {n: digest(args.model / n) for n in ('config.json', 'tokenizer.json', 'tokenizer_config.json', 'chat_template.jinja')},
              'training_ids': [r['id'] for r in rows], 'dataset_sha256': digest(ROOT / 'train/train.jsonl'),
              'split_sha256': digest(ROOT / 'experiments/supervised_family_split_v2.json'),
              'format_code_sha256': digest(ROOT / 'src/p19_format_training.py'),
              'asr_gate_report_sha256': digest(gate_path.parent / 'report.json'),
              'asr_transcripts_sha256': digest(gate_path),
              'asr_training_code_sha256': digest(ROOT / 'src/p19_real_asr_training.py'),
              'training_code_sha256': digest(Path(__file__)), 'example_sha256': example_hash.hexdigest(),
              'examples': len(examples), 'max_tokens': max_tokens, 'context_limit': 8192,
              'seed': seed, 'epochs': 1, 'dtype': 'bfloat16', 'rank': 16, 'alpha': 16,
              'dropout': 0.0, 'learning_rate': 1e-5, 'microbatch': 1, 'gradient_accumulation': 16,
              'format_mix': '1198 original decisions plus 373 gated real-ASR latest requests with formatted prior history',
              'torch_version': torch.__version__, 'cuda_version': torch.version.cuda, 'gpu': torch.cuda.get_device_name()}
    (args.output / 'config.json').write_text(json.dumps(config, indent=2) + '\n')
    (args.output / 'pip_freeze.txt').write_text(subprocess.run([os.sys.executable, '-m', 'pip', 'freeze'], capture_output=True, text=True, check=True).stdout)
    model = Qwen3_5ForConditionalGeneration.from_pretrained(args.model, dtype=torch.bfloat16, local_files_only=True, attn_implementation='sdpa').to('cuda')
    model.config.use_cache = False
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
    model, coverage = attach_lora(model)
    (args.output / 'lora_coverage.json').write_text(json.dumps(coverage, indent=2) + '\n')
    model.train()
    optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=1e-5, weight_decay=0.0)
    order = list(range(len(examples))); random.shuffle(order)
    optimizer.zero_grad(set_to_none=True)
    torch.cuda.reset_peak_memory_stats()
    started = time.monotonic(); losses = []
    with (args.output / 'training.jsonl').open('x', buffering=1) as log:
        for pos, index in enumerate(order):
            group_size = min(16, len(order) - (pos // 16) * 16)
            loss = completion_loss(model, examples[index], 'cuda')
            if not torch.isfinite(loss):
                raise RuntimeError(f'Nonfinite loss at example {pos}')
            (loss / group_size).backward(); losses.append(loss.item())
            if (pos + 1) % 16 == 0 or pos + 1 == len(order):
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
                optimizer.step(); optimizer.zero_grad(set_to_none=True)
                step = math.ceil((pos + 1) / 16)
                record = {'step': step, 'examples_seen': pos + 1, 'loss': sum(losses[-group_size:]) / group_size,
                          'elapsed_seconds': time.monotonic() - started,
                          'peak_allocated_bytes': torch.cuda.max_memory_allocated(), 'peak_reserved_bytes': torch.cuda.max_memory_reserved()}
                log.write(json.dumps(record) + '\n'); log.flush(); os.fsync(log.fileno()); print(json.dumps(record), flush=True)
                if step % 30 == 0:
                    checkpoint = args.output / f'checkpoint-{step}'
                    model.save_pretrained(checkpoint)
                    torch.save({'optimizer': optimizer.state_dict(), 'position': pos, 'random': random.getstate(),
                                'torch_rng': torch.get_rng_state(), 'cuda_rng': torch.cuda.get_rng_state()}, checkpoint / 'training_state.pt')
    model.save_pretrained(args.output / 'adapter')
    summary = {'completed': True, 'examples': len(order), 'elapsed_seconds': time.monotonic() - started,
               'peak_allocated_bytes': torch.cuda.max_memory_allocated(), 'peak_reserved_bytes': torch.cuda.max_memory_reserved(),
               'adapter_sha256': digest(args.output / 'adapter/adapter_model.safetensors'),
               'checkpoint_note': 'checkpoints retain optimizer and RNG, but this trainer does not implement resume'}
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
