#!/usr/bin/env bash
set -euo pipefail
umask 0022
mkdir -p /result/home /result/cache /result/jupyter-runtime
chmod 700 /result/home /result/cache /result/jupyter-runtime
python3 /validation/preflight.py
if [[ "$1" == notebook ]]; then
  if [[ "$2" != full ]]; then export LIFEMATE_TEST_LIMIT="$3"; else unset LIFEMATE_TEST_LIMIT; fi
  exec python3 /validation/run_notebook.py
fi
args=(--data-root /data --split public_test --output /result/submission.jsonl)
if [[ "$2" != full ]]; then args+=(--limit "$3"); fi
exec /bin/bash /code/predict.sh "${args[@]}"
