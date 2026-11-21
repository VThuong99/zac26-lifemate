#!/usr/bin/env bash
set -euo pipefail
: "${LLAMA_SOURCE:?Path to clean llama.cpp revision 8ca4060b7e30e76baaa5670ee1ec1b760b7f8552}"
: "${BACKEND_OUTPUT:?New isolated build directory}"
test ! -e "$BACKEND_OUTPUT"
cmake -S "$LLAMA_SOURCE" -B "$BACKEND_OUTPUT" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=80 \
  -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF
cmake --build "$BACKEND_OUTPUT" --target llama-server -j "${BUILD_JOBS:-6}"
cuobjdump --list-elf "$BACKEND_OUTPUT/bin/libggml-cuda.so"
# Rebuilds require regression testing. Preserve the original sm120 backend separately.
