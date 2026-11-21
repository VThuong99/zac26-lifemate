# Real inference and deployment

The CPU package/demo is immediately usable without model dependencies. Full
K48.46 RC2 inference requires separately authorized artifacts and its frozen
environment. No fresh-clone GPU inference, Docker rebuild or training was
performed for the portfolio transformation.

## Required assets

| Requirement | Why it is needed |
|---|---|
| P19-adapted Q8_0 GGUF and two F32 GGUF adapters | Decision backbone and routed reviewers |
| P34 encoder/decoder/joiner ONNX and tokens | Primary RNNT and confidence recognition |
| P34 `epoch-2.pt`, tokenizer and Icefall definitions | Runtime CTC corroboration; this is not training-only |
| Pinned PhoWhisper-medium checkpoint | Scoped independent speech corroboration |
| Preserved native llama.cpp/CUDA and Python assets | Exact serving/backend environment |
| Authorized split with matching `zaic_tools`, tool catalog and audio | One official environment per sample |
| Qualified NVIDIA host and preserved image/base assets | Historical RTX 5090 qualification; A30 unverified |

Use the [model manifest](../archive/rc2/overlay/manifests/models.json),
[native manifest](../archive/rc2/overlay/manifests/native.json) and
[recorded Python inventory](../archive/rc2/overlay/requirements.txt).
That inventory describes the release environment; a fresh pip resolver is not a
verified reconstruction, particularly for CUDA-specific builds.

## Entrypoints and configuration

- Container CLI: `/bin/bash /code/predict.sh` → `predict.py` → `KRuntime`.
- Notebook: [predict_notebook.ipynb](../archive/rc2/overlay/predict_notebook.ipynb)
  calls the same runtime and writes `jupyter_submission.jsonl`.
- Source inspection only: `python3 archive/rc2/overlay/predict.py --help`.
- [rc2-reference.toml](../configs/rc2-reference.toml) documents constants; it does
  not configure the archived program.

RC2 uses strict custom JSON, seed 20261030, temperature zero, disabled thinking
and prompt cache, seven decisions, 8,192 context tokens and a 30-second deadline.
Model loading is separate from request timing. Timing includes audio I/O,
recognition, reviews, actual calls and final hash collection.

The split root contains `<split>/<split>.jsonl`,
`<split>/<split>_tools_catalog.json`, `<split>/audio/` and
`<split>/zaic_tools/`. RC2 discovers one valid split or requires `--split`.
The mounted SDK is selected explicitly; no packaged training SDK substitutes for
it. Do not provide reference transcripts/labels or inspect hidden environment
state. The research preflight interception path is prohibited by the entrypoint.

## Preserved-image reference procedure

These are instructions for an authorized future run, not a newly verified run.
Obtain the original image from its authorized owner; it is not distributed here.
Verify its archive checksum and configuration/rootfs identities against
[RELEASE.json](../archive/rc2/artifacts/RELEASE.json) and the
[image identity guide](../archive/host_validation/IMAGE_IDENTITY.md).
A tag, image-store ID and configuration digest are different identifiers.

After loading and verifying the image, set `RC2_IMAGE_ID` to its immutable loaded
identity and `APPROVED_DATA_ROOT` to the authorized split parent:

```bash
: "${RC2_IMAGE_ID:?Set the verified immutable image ID}"
: "${APPROVED_DATA_ROOT:?Set the authorized split parent directory}"
RC2_OUTPUT=$(mktemp -d)
docker run --rm --gpus '"device=0"' --network none --cpus 16 --memory 48g \
  --memory-swap 48g --shm-size 2g --pids-limit 1024 \
  --user "$(id -u):$(id -g)" --cap-drop ALL --security-opt no-new-privileges \
  -v "$APPROVED_DATA_ROOT:/data:ro" -v "$RC2_OUTPUT:/result" \
  "$RC2_IMAGE_ID" /bin/bash /code/predict.sh
```

Append `--split SPLIT` when necessary. `--limit` is only for local smoke tests.
Follow the [host validation guide](../archive/host_validation/README.md) for
driver compatibility and offline-hostname details. The
[Dockerfile](../archive/rc2/Dockerfile) overlays and flattens an existing base;
building it needs missing base/rootfs/native/model assets. The public source
subset alone is not a complete Docker build context.

## Failure contract

Output rows contain `id`, `tool_calls`, `state_hash`, and integer millisecond
`time`. Calls and hashes come from the actual environment. A failure can leave
authentic receipts and `.partial` output. The original batch raises and does not
rename that prefix to the completed result.

An 8,192-token context overflow could therefore stop later independent requests.
The final Private Test JSONL used a diagnostic continuation workaround, according
to the user's report. That driver changes failure handling, not the original
submitted batch contract. Neither larger context nor invented empty predictions
can be presented as equivalent execution. See [results](FINAL_RESULTS.md).
