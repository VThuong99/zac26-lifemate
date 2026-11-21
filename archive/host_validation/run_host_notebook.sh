#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
[[ $# -ge 1 ]] || { echo 'Usage: run_host_notebook.sh smoke|pilot|full [--gpu INDEX_OR_UUID]' >&2; exit 2; }
MODE=$1; shift
exec "$HERE/run_host_validation.sh" "$MODE" --workflow notebook "$@"
