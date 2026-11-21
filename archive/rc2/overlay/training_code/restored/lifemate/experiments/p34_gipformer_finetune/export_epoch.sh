#!/usr/bin/env bash
set -euo pipefail
EPOCH="$1"
ROOT=/workspace/GPU_benchmark/lifemate
cd "$ROOT"
OUT="$ROOT/results/p34_gipformer_finetune_v1"
DIR="$OUT/export_epoch$EPOCH"
mkdir "$DIR"
ln -s "$OUT/epoch-$EPOCH.pt" "$DIR/epoch-$EPOCH.pt"
../.venvs/lifemate-p12-gipformer/bin/python -m experiments.p34_gipformer_finetune.export --tokens "$ROOT/../models/gipformer15-68m-dd9227d-p12/tokens.txt" --use-averaged-model false --epoch "$EPOCH" --avg 1 --exp-dir "$DIR" --enable-int8-quantization 0 --use-ctc true --keep-x-lens 1 > "$OUT/export_epoch$EPOCH.log" 2>&1
for part in encoder decoder joiner; do ln -s "$part-epoch-$EPOCH-avg-1.onnx" "$DIR/$part.onnx"; done
ln -s "$ROOT/../models/gipformer15-68m-dd9227d-p12/tokens.txt" "$DIR/tokens.txt"
../.venvs/lifemate-p10/bin/python experiments/p34_gipformer_finetune/eval_dev.py --model "$DIR" --output "$OUT/dev_epoch$EPOCH" > "$OUT/dev_epoch$EPOCH.log" 2>&1
