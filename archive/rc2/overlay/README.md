# Frozen LifeMate K 48.46 — release candidate

This is the isolated deployment replica of the user-reported official champion K=48.46. It preserves the Q8_0 decision weights, two F32 reviewer adapters, P34 RNNT/CTC and PhoWhisper ASR routing, prompt, schema formatter, controller, reviews, greedy decoding, seed20261030, context8192 and seven-step cap. It does not train a new model or select an E13–E19 candidate.

**Read the accompanying engineering report before submission. This candidate is not release-approved.** Native RTX5090 evidence, container-archive assembly evidence, Docker runtime evidence, A30 evidence and redistribution authority are separate. Actual A30 execution, VRAM and the30-second deadline remain unverified. Complete historical training-data restoration and publication/transfer permissions are unresolved.

## Layout

- This directory is the source repository candidate: entrypoints, notebook, frozen runtime code, training documentation, checksums and build scripts.
- `../model_artifacts/` contains the actual inference assets, including tokenizers. It is local only; no model binary belongs in normal Git history.
- `../dependencies/` contains the Python3.12 package files used by K, separately hash-inventoried. Jupyter dependencies are isolated behind the original runtime packages in import order. `manifests/python-exclusions.json` records the removal of unused upstream agent instructions and a public TLS test-key fixture; runtime library bytes are unchanged.
- `../native/` contains the original Blackwell backend, matching CUDA runtime libraries and the pinned compiler-source archive. The separately built `sm80/` candidate is quarantined outside the image after a consequential regression.
- `../evidence/` contains local test outputs and provenance. It is excluded from the source build/publication candidate.
- `../artifacts/` contains any assembled container/source archives and checksum sidecars. Consult `ARTIFACTS.json` there; an assembled archive must still be loaded and tested by Docker.

After authorized restoration of the external artifact categories, retain the sibling directory names above. A fresh clone should be named `source` inside a new release directory. `python3 verify_release.py` checks all restored bytes. Do not download a new model version or replace an unavailable trained adapter with its upstream base model. The missing training-only data is listed separately in `training_code/required-private-assets.json`.

## Prediction and timing

The default command is `bash /code/predict.sh`. The input is one mounted split beneath `/data` with its JSONL, catalog, audio and matching `zaic_tools`. Split detection does not assume public or private IDs. If a local development mount contains several splits, supply `--split`; official use with one split needs no flags. The SDK is never packaged. Hidden environment files are read only by that SDK. There is one actual ToolEnv per request, and outputs come from its real call log and final hash.

The output is UTF-8 `/result/submission.jsonl`, exactly `id`, `tool_calls`, `state_hash`, `time` (integer milliseconds). Time starts before audio IO and includes ASR, decision generation, reviews, ToolEnv and final hash collection. Cold load time is reported separately to stdout. Detailed traces are outside the output file. A genuine failure leaves `.partial` evidence and a nonzero exit instead of claiming a complete submission or fabricating a state hash. No request is retried with a second ToolEnv.

`predict_notebook.ipynb` runs the same `KRuntime` implementation and writes `/result/jupyter_submission.jsonl`. `start_jupyter.sh` starts JupyterLab on port9777 using its normal generated token; the guide's sample hardcoded credential is not embedded. Optional `LIFEMATE_TEST_LIMIT` is for local notebook smoke tests only; leave it unset for organizer execution. Likewise omit CLI `--limit` for full prediction.

## Build and validation commands

The actual pinned base is NVIDIA CUDA13.2.0 on Ubuntu24.04, index digest `sha256:f9492f2eea77fbc3d0c14fa8738f35946b42da72917bf5959d284ca39b4f209a`, AMD64 manifest `sha256:d266e59b88c295bc5fa0e4cef9064eaff84939381b09e2c3d76a5532a303e42d`. Ubuntu24.04 preserves Python3.12/native ABI compatibility; Ubuntu22.04 appears as a guide example. The original llama CUDA13.1 libraries are preserved to avoid silently changing BLAS numerics. System package versions and all native/Python/model hashes are recorded. The apt mirror is not a permanent snapshot; future rebuild availability of exact versions is not guaranteed. The exported image bytes, when produced, are independently checksummed.

```bash
export CUDA_BASE='nvidia/cuda:13.2.0-devel-ubuntu24.04@sha256:f9492f2eea77fbc3d0c14fa8738f35946b42da72917bf5959d284ca39b4f209a'
bash build.sh
mkdir -p ../validation_result
docker run --rm --gpus '"device=0"' --network none --cpus 16 --memory 64g \
  -v "$APPROVED_TEST_ROOT:/data:ro" -v "$PWD/../validation_result:/result" \
  lifemate-k:k48.46-20261115-rc1 /bin/bash /code/predict.sh
docker run --rm --gpus '"device=0"' -p 127.0.0.1:9777:9777 \
  -v "$APPROVED_TEST_ROOT:/data:ro" -v "$PWD/../validation_result:/result" \
  lifemate-k:k48.46-20261115-rc1 /bin/bash /code/start_jupyter.sh
```

These are prepared Docker commands, not claims that Docker ran in the restricted build session. Run notebook cells and compare exact trajectories/hash/status with CLI. The Jupyter UI example needs a reachable port; perform a separate `--network none` notebook execution through `docker exec`/nbclient to qualify offline timing. Never use networking to fetch inference assets.

Runtime selection chooses the unchanged original `sm_120a` backend for capability 12.0 and prints that selection. Capability 8.0 fails explicitly: the `sm_80` candidate compiled and ran on RTX 5090 via compatible code, but matched only 20/21 saved K decisions; one SMS changed 10:00 to 14:00. It is quarantined and excluded from the image. No CPU fallback or different inference engine is selected. A behavior-preserving Ampere implementation and actual target-hardware validation are still required.

See [official compliance](docs/COMPLIANCE.md), [training reproduction](training_code/README.md), [transfer commands](docs/TRANSFER.md) and the local engineering report. GitHub and GHCR publication, storage upload and competition submission are manual and require explicit authorization.
