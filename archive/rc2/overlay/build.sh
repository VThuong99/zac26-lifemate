#!/usr/bin/env bash
set -euo pipefail
release_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$release_root"
cp source/dockerignore.template .dockerignore
python3 source/verify_release.py
docker info >/dev/null
: "${CUDA_BASE:?Set the reviewed CUDA base reference including its sha256 digest}"
case "$CUDA_BASE" in *@sha256:*) ;; *) echo 'CUDA_BASE must be digest-pinned' >&2; exit 2;; esac
docker build --build-arg "CUDA_BASE=$CUDA_BASE" -f source/Dockerfile \
  -t lifemate-k:k48.46-20261115-rc1 .
docker image inspect lifemate-k:k48.46-20261115-rc1 > image-inspect.json
