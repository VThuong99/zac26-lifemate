# Training implementations

The submitted lineage used ASR fine-tuning, sequential decision-model SFT, a DPO
write reviewer and a separate terminal preference objective. This directory is
the navigation entrypoint; the original scripts remain frozen to preserve their
path-sensitive imports and provenance. None is run by package installation or CI.

## Recipes and code

| Stage | Actual implementation | Historical recipe and status |
|---|---|---|
| P34 Vietnamese ASR | [training loop](../archive/rc2/overlay/training_code/restored/lifemate/experiments/p34_gipformer_finetune/train.py), [data preparation](../archive/rc2/overlay/training_code/restored/lifemate/experiments/p34_asr_data_v1/prepare.py), [token targets](../archive/rc2/overlay/training_code/restored/lifemate/experiments/p34_tokenizer_fix_v1/prepare.py) | Gipformer, 2 FP32 epochs, AdamW 1e-5, batch 1; .75 simple RNNT + .55 pruned RNNT + .2 CTC. Conversation/transcript/PCM grouping before the train/dev split. |
| ASR selection/export | [dev evaluation](../archive/rc2/overlay/training_code/restored/lifemate/experiments/p34_gipformer_finetune/eval_dev.py), [selection](../archive/rc2/overlay/training_code/restored/lifemate/experiments/p34_gipformer_finetune/select.py), [ONNX export](../archive/rc2/overlay/training_code/restored/lifemate/experiments/p34_gipformer_finetune/export.py) | Epoch 2 selected by dev WER; strict checkpoint loading. The P34 PyTorch checkpoint is also needed by inference CTC. |
| P9 decision SFT | [entrypoint](../archive/rc2/overlay/training_code/restored/lifemate/scripts/train_p9.py), [training implementation](../archive/rc2/overlay/training_code/restored/lifemate/src/p9_training.py) | Qwen3.5-4B BF16 LoRA rank/alpha 16, LR 1e-4; merged before P19. |
| P19 real-ASR SFT | [entrypoint](../archive/rc2/overlay/training_code/restored/lifemate/scripts/train_p19_real_asr.py), [training implementation](../archive/rc2/overlay/training_code/restored/lifemate/src/p19_real_asr_training.py), [config](../archive/rc2/overlay/training_code/restored/lifemate/results/p19_real_asr_sft_train_v1/config.json) | Rank/alpha 16, LR 1e-5, one epoch, accumulation 16; original decisions plus gated authentic-ASR variants. |
| DPO write reviewer | [training](../archive/rc2/overlay/training_code/restored/lifemate/results/p20c_grounding_preferences_v1/train.py), [protocol](../archive/rc2/overlay/training_code/restored/lifemate/results/p20c_grounding_preferences_v1/protocol.json), [export](../archive/rc2/overlay/training_code/restored/lifemate/results/p20c_grounding_preferences_v1/export.py) | P19-initialized BF16 LoRA rank/alpha 16, LR 5e-6, beta .1; grammar-conditioned reviewed preferences. |
| K terminal reviewer | [training](../archive/rc2/overlay/training_code/restored/lifemate/experiments/continuous_improvement/conditional_terminal_preference_sft_v1/train.py), [preference loss](../archive/rc2/overlay/training_code/restored/lifemate/experiments/continuous_improvement/conditional_terminal_preference_sft_v1/branch_preference.py), [recipe](../archive/rc2/overlay/training_code/restored/lifemate/experiments/continuous_improvement/conditional_terminal_preference_sft_v1/recipe.json) | SFT plus reference-anchored first-divergent-token preference, rank/alpha 4, LR 4e-5, 16 optimizer steps. This is not full-sequence DPO. |
| Serving conversion | [P19 export](../archive/rc2/overlay/training_code/restored/lifemate/scripts/export_p19_checkpoint.py), [reviewer conversion](../archive/rc2/overlay/training_code/restored/lifemate/experiments/continuous_improvement/conditional_terminal_preference_sft_v1/convert.py), [Q8 identity](../archive/rc2/overlay/training_code/restored/lifemate/experiments/continuous_improvement/p19_champion_q8_v1/identity.json) | Merged decision weights to GGUF Q8_0; runtime adapters in F32 GGUF, with original routing. |

PhoWhisper uses unchanged publisher weights for corroboration. There is no claim
that this project fine-tuned PhoWhisper. Teacher, trajectory-RL and later critic
experiments are historical research; they are not deployed K components.

## Export the public source into an isolated workspace

From the repository root:

```bash
python3 scripts/export_training_source.py --output /tmp/lifemate-training-study
```

The destination must not exist and must be outside this repository. The exporter
verifies hashes before writing **64 already-public files**, preserves their
historical layout, and writes `PUBLIC_SOURCE_EXPORT.json`. The historical receipt
contains 65 source files; one transcript-bearing export-parity report is
explicitly excluded. The original receipt itself is not counted as exported
training source. No private file is fetched, no model is copied, and no script is
executed. Existing destinations are never overwritten.

This is useful for reading and editing the original training implementation in
one workspace. It does **not** make training runnable: historical absolute paths,
import-time preparation, intermediate assets and separate environments remain.
Do not execute preparation modules merely to discover their CLI.

## Requirements for a real reproduction

You need authorized organizer training audio and reviewed inputs, exact base
checkpoints, masks/preparation intermediates, the recorded training environments,
and pinned Icefall/llama.cpp checkouts. Restore these separately in an isolated
workspace; keep restricted data outside the public repository. Training scripts
must be reviewed for historical path assumptions before execution.

The [original training record](../archive/rc2/overlay/training_code/README.md)
contains hyperparameters, revisions and upstream references.
[Required private assets](../archive/rc2/overlay/training_code/required-private-assets.json)
is a known-input inventory, not a complete dependency closure.
[Restoration notes](../archive/rc2/overlay/training_code/TRAINING_RESTORATION.md)
describe unresolved environment and permission requirements. Source export,
syntax checks and local asset hashes do not establish clean-machine retraining.
