# Frozen RC2 Private Test: manual host workflow

## Continuation after the Private Test context overflow

Use `continue_private_test.py` for the authorized workaround. It retains the submitted image, original weights, ASR, controller, SDK, 30-second request deadline and **8192-token context**. The mounted batch driver imports the original `/code/predict.py` and calls `KRuntime.infer` directly. The NVIDIA Docker entrypoint is preserved; the inference command changes to `python3 /validation/continue_inference.py`. It catches per-request transport failures after the original worker saves its receipt and continues with the next independent request. There is no prompt truncation, retry, extra ToolEnv, or context-size override.

The 323 original JSONL lines are copied byte for byte after validation. The saved `private_0327` failure receipt supplies its actual SDK calls, final observed hash and original elapsed time if valid. This leaves **301 new requests** for the initial continuation. Failure status stays in separate reports and is never represented as successful completion. Earlier `tool_error` rows are preserved. The recovery validator distinguishes proposals rejected by `env.validate` from actual `env.call` executions using the unchanged official schema checker and frozen controller semantics.

Run this on the RTX 5090 **host**. It reads the host workspace mapping from the existing run report; no `/workspace/...` path is assumed to exist on the host. Ensure this updated host-runner folder, including `continue_private_test.py`, `recovery_checks.py` and `container/continue_inference.py`, is available there.

```bash
RC2_RUN=/home/duongthuong/lifemate-private-rc2-results/20261120T133830Z-full-0q1t9859
RC2_WORKSPACE="$(python3 -B -c 'import json,sys; print(json.load(open(sys.argv[1]))["workspace"])' "$RC2_RUN/REPORT.json")"
python3 -B "$RC2_WORKSPACE/lifemate-private-rc2-host-20261120/continue_private_test.py" \
  --resume-from "$RC2_RUN" \
  --output-dir "$HOME/lifemate-private-rc2-results" \
  --gpu 0 \
  --cuda-compat
```

The command automatically discovers sealed continuation runs associated with this original full run. Repeating the same command reuses validated receipts and processes only untouched requests. It refuses overlapping attempts, changed evidence, active/restarted source containers, and unsealed runs. An attempted request with no usable receipt remains explicitly unresolved and is never retried or filled with an invented prediction. Another context overflow with a valid receipt is recorded and does not stop the batch. A dead worker stops that invocation; repeating the host command can process untouched requests while retaining unresolved failures.

Each invocation writes a fresh `*-continue-*` directory under the output directory. The existing frozen runner, its validator and prior reports stay unchanged. Mounts remain:

- New run's `dataset/private_test` → `/data/private_test`, read-only, full official dataset.
- New run's `inference` → `/result`, writable by the invoking host UID/GID.
- New run's `harness` → `/validation`, read-only; includes the selected original indices and the continuation driver.

Image/archive identity, original source manifests, SDK origins, one environment open per attempted request, GPU computation, 48 GiB container memory limit, runtime deadlines and input hashes remain checked. Both preflight and inference receive the explicit CUDA compatibility override. The server command and its startup log must confirm 8192 tokens. The final validator calls the official `zaic_tools/validate.py::schema_validate` against the catalog and installed tools from the official input. It does not run the SDK CLI `--validate`, which constructs extra ToolEnv sessions and accesses their hidden allowed-tools state. JSONL fields, types, exact IDs/order, uniqueness, receipt equality and hash provenance are checked separately. Hash verification establishes equality with actual SDK receipts; it does not independently replay private state or establish semantic correctness.

Only complete, validated coverage publishes:

```text
~/lifemate-private-rc2-results/private_test_k48_46_final.jsonl
~/lifemate-private-rc2-results/private_test_k48_46_final.jsonl.sha256
```

Publication never overwrites different existing bytes. Each run's `REPORT.json`, `validation.json`, `failures.json` and `row-provenance.json` report request counts, inference failures, context overflows, other execution failures, official schema results, source receipts, output path and SHA256. Stop after execution and paste the terminal summary and `REPORT.json` for verification. Nothing is uploaded.

**Classification: complete diagnostic artifact; official submission eligibility is not established.** The documented rules require frozen-solution reproducibility and score execution failures as zero. The Docker guide requires the submitted CLI/notebook to complete. The unchanged submitted entry paths still abort on this error; this host continuation changes batch error handling and exports authentic failure receipts. A schema pass does not establish competition eligibility. No 16384-token fallback is enabled or silently selected; it would be a separate non-equivalent runtime configuration, and the documented 16K maximum alone does not authorize a post-submission configuration change.

## Original smoke/full workflow

Run `smoke` on the RTX 5090 host first. It processes the first **three official requests**, validates the results, and stops. Paste its terminal summary back for review. It does **not** start the full run or create the final submission file.

This directory contains orchestration, validation and a read-only SDK observer. All ASR, planning, adapters, controller decisions, tool execution and final hashes come from the original Docker image. No inference code is replaced, patched or rebuilt. No Docker command has been executed from the development container during preparation.

## Host paths

The previous RC2 host scripts record this mapping:

| Development container | Expected host location |
| --- | --- |
| `/workspace/GPU_benchmark` | `/home/duongthuong/GPU_benchmark_host` |

The host location is **not confirmed from this container**. Check it on the host. If your workspace is elsewhere, change the `cd` below to the actual host directory. The runner resolves `--workspace` on the host, checks the required files and checks Docker's actual mount inspection before starting a container. It accepts only a local Unix Docker endpoint.

These paths must exist under the host workspace:

```text
lifemate-private-rc2-host-20261120/
  run_private_test.py
  check_results.py
  container/preflight.py
  container/sitecustomize.py
lifemate-final-20261116-rc2/             # original, complete RC2 workspace
  BUILD.json
  CONTEXT_SHA256.json
  artifacts/RELEASE.json
  artifacts/lifemate-k-k48.46-20261116-rc2.tar.gz
  tools/                              # existing RC2 verification tools
  overlay/                            # original source-context evidence
  runs/                               # original validation reports
lifemate-host-validation/              # original identity/validation helpers
lifemate/docs/organizer/private_test.zip
lifemate/docs/organizer/Docker_Guide_ZAC2026_LifeMate.pdf
```

Do not copy `/workspace/...` into a host bind mount on the assumption it exists there. If this shared host mapping is unavailable, copy the complete workflow directory and the above original release/dataset/evidence directories to a host workspace, preserving their bytes. The runner verifies pinned checksums and refuses changed or incomplete release evidence.

## Run only the smoke stage now

Use the ordinary host user with existing Docker access, **without `sudo`**, in a host terminal. Requirements: Python 3.10+, Docker with NVIDIA GPU support, `nvidia-smi`, one idle RTX 5090, at least 16 logical CPUs and approximately 64 GB host RAM. No dependencies are installed. Leave unrelated GPU workloads running and wait for their owner if the GPU is busy.

```bash
cd /home/duongthuong/GPU_benchmark_host
pwd -P
ls -ld lifemate-final-20261116-rc2 lifemate-private-rc2-host-20261120
ls -l lifemate/docs/organizer/private_test.zip
python3 -B lifemate-private-rc2-host-20261120/run_private_test.py smoke \
  --workspace "$(pwd -P)" \
  --output-dir "$HOME/lifemate-private-rc2-results" \
  --gpu 0
```

If the checks say the host paths are missing, stop and correct the host workspace location. Do not run the script inside the development container; it rejects that before contacting Docker.

The terminal prints `HOST OUTPUT DIRECTORY: ...`, `EVIDENCE: ...`, then the final status, report path, request counts, timing and `SMOKE_RUN=...`. **Stop there and paste the terminal output for review.** If it fails, also paste the error and relevant log named by the script. Each invocation writes a new directory under `--output-dir`; previous evidence remains intact.

The output directory defaults to `~/lifemate-private-rc2-results` and is created if needed. All extracted inputs, run logs, caches, helper copies, lock files and the final JSONL live there. The workspace is only read; write access to `lifemate/results/` or `lifemate-host-validation/` is unnecessary. No existing directory ownership or permissions are changed. Containers use the actual invoking host UID/GID, so `duongthuong` can write the mounted output without sudo. Use the same output directory for concurrent invocations to share the workflow/GPU advisory locks; the GPU idle checks remain in place.

## Full run, only after smoke review

This is a separate, later command. Do not run it as part of the initial smoke test. Replace the example path with the exact `SMOKE_RUN` printed by a successful smoke invocation:

```bash
cd /home/duongthuong/GPU_benchmark_host
python3 -B lifemate-private-rc2-host-20261120/run_private_test.py full \
  --workspace "$(pwd -P)" \
  --output-dir "$HOME/lifemate-private-rc2-results" \
  --gpu 0 \
  --smoke-run /absolute/host/path/to/the/successful/smoke-run
```

The full command rechecks the archive, loaded image, input bytes and runtime. It verifies that the prior smoke evidence and workflow files are unchanged and that the GPU UUID and driver match. It then processes all **625 requests in official JSONL order**, with no limit, retries, policy changes or smoke-output reuse.

On structurally valid completion, the exact output bytes are published without overwriting anything to:

```text
<OUTPUT_DIR>/private_test_k48_46_rc2.jsonl
```

With the default output directory for host user `duongthuong`, the final host path is:

```text
/home/duongthuong/lifemate-private-rc2-results/private_test_k48_46_rc2.jsonl
```

The host home directory is not assumed to be mounted into the development container. Nothing is copied back into the unwritable workspace. Paste the terminal report here for review.

Publication uses an atomic, exclusive hard link to the staged JSONL on the same filesystem; both paths are retained. Nothing is uploaded or submitted. If the final path already exists, the script stops without changing it.

## Identity and execution protocol

- Submitted tag: `lifemate-k:k48.46-20261116-rc2`.
- Recorded image store ID / manifest digest: `sha256:e212336277d5b37c5359599961c56b7f9331e4f63b3985902a2e7c588c114a8c`.
- Configuration digest: `sha256:00cf5905325e57fa68e7034d4e773bc81fcea8e347d41c3e3e100e47de486306`.
- Original archive SHA256: `e2aaa0a3c8f54e673f7700c443846a974be09257f3e28145ca9f0fb5076232f5`.
- Pinned release metadata and source context are checked before importing the existing RC2 archive verifier. The complete compressed archive, member/blob hashes, expanded layer DiffIDs, manifest and configuration are verified. The loaded image must match the configuration, root filesystem, OS, architecture and authenticated identity. A matching tag alone cannot pass.
- If the exact image and submitted tag are absent, the script loads only the verified original archive. It requires 64 GiB free on the Docker storage filesystem for this branch. It never builds, retags, commits, prunes or pulls an image. If only the submitted tag resolves, a mismatched image fails closed. Every run uses the verified immutable ID, never the tag.
- Original `ENTRYPOINT`: `/opt/nvidia/nvidia_entrypoint.sh`; preserved for all containers. Inference command: `/bin/bash /code/predict.sh --data-root /data --split private_test --output /result/submission.jsonl`. Only smoke adds `--limit 3`.
- Each run extracts the checksum-verified ZIP into its own directory, validating member CRCs. Hidden environment files are only passed through extraction as opaque bytes. After extraction only the organizer SDK reads their contents.
- `<OUTPUT_DIR>/<run>/dataset/private_test` → `/data/private_test`, read-only; `<OUTPUT_DIR>/<run>/inference` → `/result`, writable; `<OUTPUT_DIR>/<run>/harness` → `/validation`, read-only. Preflight has its own `<run>/preflight` mount at `/result`. The original inference command still writes `/result/submission.jsonl`; no source or weights are mounted over `/code`.
- `--network none`, one GPU selected by UUID, 16 CPU quota, 48 GiB RAM, no swap beyond that RAM, 2 GiB shared memory, 1,024-process limit, invoking UID/GID, all Linux capabilities dropped, no new privileges. No hostname/network workaround is added.
- The frozen image's `/code/verify_release.py --image` verifies its own model, adapter, binary and source manifests. CUDA allocation and the Private Test SDK's 207 tool implementations are checked before inference, without constructing `ToolEnv`.
- The original seven-step limit, 30-second request deadline, seed 20261030, temperature 0, 8192-token context, routing and adapters remain unchanged. The original runner writes and flushes `.partial`, then renames on completion. It has no resume option; this workflow does not introduce one.
- The observer is copied from RC2 validation with only the SDK path changed from public to private. It records SDK module origins/checksums and environment filenames, and rejects hidden-state access outside the SDK. It does not patch SDK methods, read their state or change decisions.

The organizer Docker guide specifies RTX 5090 / Xeon Gold 6459C / 64 GB / driver 595.58.03 / CUDA 13.2; older local rules mention A30. Actual host details are recorded. The retained RC2 harness resource settings use 48 GiB RAM and a CPU quota rather than physical core pinning. Observer I/O remains inside measured inference time. Filesystem caches are not flushed.

## Results and diagnostics

Each run retains `REPORT.json`, `validation.json`, image/archive identity, dataset manifest, original CLI/notebook parity reports, exact Docker create arguments, container inspections, logs, GPU/resource samples, model-loading evidence, per-request receipts, tool events and SDK-origin audit logs. The historical 10/10 CLI and 10/10 notebook parity reports are checksum-verified; no score or new Private Test notebook parity is inferred from them.

Validation rejects missing/duplicate/out-of-order IDs, blank or malformed JSON, duplicate JSON keys, extra output fields, invalid types, bad hashes, elapsed times at or above 30 seconds, incomplete output, missing receipts/events, mismatched actual call order, mismatched prediction hashes, wrong SDK origins or multiple environment opens. It uses the original Private SDK `schema_validate` with allowed tool names from the official input context. It does not replay tools, invoke the SDK CLI `--validate`, construct another `ToolEnv`, or access `.allowed`/hidden state.

The Docker-guide schema is `id`, `tool_calls`, `state_hash`, and integer millisecond `time`. The older dataset README examples omit `time`; the frozen runner's field is retained. Debugging data stays in separate files.

- `SMOKE PASSED`: three complete, validated requests, at least one actual tool call, no warnings. The full run remains stopped for manual review.
- `READY FOR SUBMISSION`: the full run passes all implemented structure, protocol, timing and tool-schema checks without warnings. This is not a private score or a guarantee of semantic correctness, organizer replay equality, training-restoration compliance or competition eligibility.
- `GENERATED WITH WARNINGS`: the complete output is structurally valid and faithfully recorded, but includes step-limit cases or actual rejected/schema-invalid tool calls. These calls are retained exactly; they are never repaired or omitted. Counts and details are reported.
- `BLOCKED / INVALID`: runtime, coverage, structure or execution-provenance checks failed. Partial/staged results remain diagnostic artifacts and the final path is not published.

Interrupted or failed inference is not automatically retried. The script stops only its own recorded container ID when needed and retains stopped containers and all artifacts. It never stops unrelated workloads, deletes prior results, or modifies the frozen release. Review the report before deciding on another invocation.

## Preparation checks

The local tests exercise real recorded RC2 image/configuration evidence and synthetic prediction failure cases. They do not run Docker, models or `ToolEnv`. Host GPU and container execution remain to be established by your manual smoke test.

```bash
python3 -B -m unittest discover -s lifemate-private-rc2-host-20261120 -p 'test_*.py' -v
```

Tests use the original November 20 inspection evidence under `lifemate/results/private_test_k48_46_rc2_audit_20261120T114547Z`; that evidence is not required for the host runner itself.
