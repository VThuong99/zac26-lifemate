#!/usr/bin/env bash
set -euo pipefail
mkdir -p /result/home /result/cache /result/jupyter-runtime
chmod 700 /result/home /result/cache /result/jupyter-runtime
python3 /validation/preflight.py
case "$1" in
  gpu) exit 0;;
  notebook)
    export LIFEMATE_TEST_LIMIT=10
    exec python3 /validation/run_notebook.py;;
  smoke) count=1;;
  pilot) count=10;;
  *) echo 'Unknown bounded validation stage' >&2; exit 2;;
esac
exec /bin/bash /code/predict.sh --data-root /data --split public_test --output /result/submission.jsonl --limit "$count"
