# LifeMate — final submission actions

**Run this single command on the host now:**

```bash
bash /home/duongthuong/GPU_benchmark_host/lifemate-final-20261116-rc2/host.sh resume 0
```

It verifies the **already built rc2** against the preserved build evidence, reuses authenticated successful stages, then runs the remaining one-request smoke, ten-request CLI parity, ten-request notebook parity, and local archive packaging. **Image verification and GPU preflight already passed.** The successful GPU receipt and original BUILD.json are unchanged. It stops on any failure. **No Docker build, upload or submission is invoked.** It preserves rc1, frozen K, weights and existing archives.

The lock failure after GPU preflight was reproduced in CPU tests: the background monitor inherited both lock descriptors, and cleanup tried to reap it from a subshell. Cleanup now waits in the owning shell and the monitor receives neither lock descriptor. Resume itself holds no stage lock. Locks are never deleted or bypassed; acquisition waits up to 20 seconds, then fails with host lock diagnostics. See [lock correction evidence](../lifemate-final-20261116-rc2/evidence/LOCK_CORRECTION.md).

**Safe sequential fallback, using the already successful verification/GPU evidence:**

```bash
bash /home/duongthuong/GPU_benchmark_host/lifemate-final-20261116-rc2/host.sh smoke 0 &&
bash /home/duongthuong/GPU_benchmark_host/lifemate-final-20261116-rc2/host.sh pilot 0 &&
bash /home/duongthuong/GPU_benchmark_host/lifemate-final-20261116-rc2/host.sh notebook 0 &&
bash /home/duongthuong/GPU_benchmark_host/lifemate-final-20261116-rc2/host.sh package 0
```

This chain stops on failure and does not rerun verification or GPU preflight. Do not run the chain and `resume` concurrently. If a lock remains owned after the bounded wait, preserve it and wait for its owner; do not delete the lock file or kill another process.

The complete saved configuration comparison differs only in `ArgsEscaped`: absent/default `false` versus `true`. The [OCI specification](https://github.com/opencontainers/image-spec/blob/main/config.md#properties) defines this as a deprecated Windows command-line field. Only this field is normalized for Linux semantic comparison; malformed types, unknown fields and all other runtime/security differences still fail. The actual raw configuration digest remains pinned to `sha256:00cf5905325e57fa68e7034d4e773bc81fcea8e347d41c3e3e100e47de486306`; Docker's stored manifest/image ID remains `sha256:e212336277d5b37c5359599961c56b7f9331e4f63b3985902a2e7c588c114a8c`. Both exact RootFS DiffIDs are retained: one flattened content layer and the canonical 1024-zero-byte empty tar layer. Original build inputs and evidence are authenticated before resume. See [the correction report](../lifemate-final-20261116-rc2/evidence/IDENTITY_CORRECTION.md).

**1. Best candidate and time remaining**

Preferred: `lifemate-k:k48.46-20261116-rc2`, already built with all **42,199 release-file checks passing**. The host reported successful offline RTX 5090 execution without hostname mapping: `public_0002`, 2,808 ms, sm120, exit 0. The resume command records authenticated identity and the bounded parity/package evidence. Docker/export cannot run in this development container. The original K = 48.46 score and sealed rc1 remain protected; rc2 has no newly measured score.

Deadline: **16 November 2026, 23:59 GMT+7 (16:59 UTC)**, confirmed by the [official live timeline](https://challenge.zalo.ai/) and retained Rule. At 20:35, 3 h 24 min remained. Package immediately after the bounded checks pass. Reserve **22:00–23:59** for packaging, transfer and manual submission; scripts refuse tests whose allotted time would cross 22:00. Transfer earlier on slow connections: 17 GB takes about 114 minutes at 20 Mbit/s, before overhead. No full 634-request run is scheduled.

Hardware conflicts: Rule specifies **A30**; Guide p4 specifies **RTX 5090**. rc2 automatically selects the existing dual-target native backend for capability 8.0 and retains the original Blackwell backend for 12.0. Unsupported devices fail. The dual library previously matched K 634/634 on RTX 5090; **actual A30 execution, driver compatibility, memory, timing and behavior remain unverified**. The rejected old sm80-only build is not used.

**2. SDK determination and minimal correction**

Guide p6: **“zaic_tools của split, KHÔNG dùng bản đóng trong image”** — use the split SDK, not the packaged version. No separate prohibition of mere unused file presence was found. The Rule permits only `validate`, `call`, `get_tool_calls`, `get_state_hash` at inference, exactly one ToolEnv per sample, every actual call in the output, and no direct environment-file access.

The rc1 smoke recorded 104 legacy module executions and 44 mounted SDK executions. Two imports use bundled schema helpers; importing that package also imports executor/app modules. This does **not** establish bundled ToolEnv execution: the unchanged factory selects `/data/public_test/zaic_tools/__init__.py`, and the receipt records one ToolEnv. Original logs trace imports, not every file access.

rc2 removes all 52 packaged SDK files and replaces the two helper imports with a state-free local schema checker. Mounted ToolEnv selection, constructor count, state integrity, actual-call logging and controller decisions remain unchanged. The new host audit rejects environment-file opens outside the mounted SDK. A flattened final image prevents removed SDK files surviving in inherited layers.

It also changes only Icefall diagnostic metadata (`"IP address": None`) to avoid offline DNS, adds the existing Ampere backend, and includes the recovered 65-file training-source supplement. Weights, tokenizer, ASR settings, original Blackwell backend and notebook cells are unchanged. The original validator and its SDK findings were not modified. [Exact quotes, import evidence, changes and limitations](../lifemate-final-20261116-rc2/evidence/PREPARATION_DETAILS.md) are retained for review later.

**3. Host commands — run one at a time, proceed only after success**

```bash
# Only if build succeeded but the GPU check was blocked by another workload:
bash /home/duongthuong/GPU_benchmark_host/lifemate-final-20261116-rc2/host.sh verify

# GPU initialization preflight (after verify succeeds):
bash /home/duongthuong/GPU_benchmark_host/lifemate-final-20261116-rc2/host.sh gpu

# Actual offline inference: one request, exact K calls/hash/status and timing:
bash /home/duongthuong/GPU_benchmark_host/lifemate-final-20261116-rc2/host.sh smoke

# Ten requests, exact K comparison:
bash /home/duongthuong/GPU_benchmark_host/lifemate-final-20261116-rc2/host.sh pilot

# Unchanged notebook in a fresh kernel, same ten requests:
bash /home/duongthuong/GPU_benchmark_host/lifemate-final-20261116-rc2/host.sh notebook

# Export, verify and checksum locally; no upload:
bash /home/duongthuong/GPU_benchmark_host/lifemate-final-20261116-rc2/host.sh package
```

Append a GPU index/UUID as the second argument when needed. A busy GPU causes refusal; wait for its owner. After interruption, run the failed stage and the remaining stages individually to reuse successful evidence. Never rerun `build`. Tests use `--network none` without hostname flags and retain results in `lifemate-final-20261116-rc2/runs/`. Parity and SDK findings are reported independently. Authenticated rc1 load evidence is reused; its archive is not rehashed or reloaded. The new export is checked in one pass, including exact build configuration/manifest digests, layer DiffIDs, blob hashes, complete tar/gzip streams, SHA-256 and MD5. Existing complete or partial archives are preserved and never overwritten.

Successful export creates `artifacts/lifemate-k-k48.46-20261116-rc2.tar.gz`, `.sha256`, `.md5`, a supplementary source archive and `RELEASE.json` with exact identities and validation receipts. No final checksum is invented before export.

**4. Mandatory blockers and human approvals**

Guide p15 requires **“Cung cấp đầy đủ Training Code & Data”**. BTC reproduces training from `training_code/`; immutable external download URLs are allowed because reproduction has internet. Training-only base models must be excluded from Docker; inference weights must be included.

Recovered training source is included. **Complete authorized data/audio/preparation dependencies, immutable restore URLs, historical environment restoration and clean-machine reproduction remain incomplete.** See `overlay/training_code/README.md` and `TRAINING_ASSET_STATUS.json`. Source restoration is not completed reproduction.

**Before external transfer, obtain written company authorization** for the exact checkpoints/source/training assets, destination account and required “Anyone with the link” exposure. Confirm model/dependency and organizer-data permissions. The dataset README prohibits redistribution; do not publicly upload organizer data to fill the training gap. Resolve authorized organizer access. Local build/export grants no transfer permission. These mandatory gaps prevent a full-compliance claim even if all inference tests pass.

**5. Transfer and final submission, after mandatory requirements and permissions are satisfied**

1. Read `artifacts/RELEASE.json` and the bounded test reports. Upload only the complete named `.tar.gz`, never `.partial`; use its recorded MD5 and byte count. Disclose remaining A30/full-regression uncertainty.
2. Manually upload to the approved Google Drive account, set **“Anyone with the link”**, and check the link while signed out. Confirm upload completion and checksum/size using available transfer tooling. Keep the uploaded artifact immutable.
3. If time and an authorized second host permit, check the received SHA-256/MD5 and `docker load -i` the archive. Official execution uses `/bin/bash /code/predict.sh`, the test parent mounted read-only at `/data`, writable `/result`, GPU access and `--network none`. No hostname mapping is needed by design; the rc2 host smoke must confirm it.
4. Open the [LifeMate portal](https://challenge.zalo.ai/portal/lifemate), select **Solution Submission**, provide the final Drive link, MD5 and requested source/training details, and submit manually before **23:59 GMT+7**. Save confirmation of the exact link/checksum accepted. The Rule allows two solution submissions and evaluates only the last. This is separate from public-test JSONL submission.

The retained CLI writes `/result/submission.jsonl`; the required notebook runs all cells and writes `/result/jupyter_submission.jsonl` with millisecond `time`. Both must produce the same scored result. JupyterLab and inference models/dependencies are already in the base image and retained. Nothing uploads or submits automatically.

**6. Tests and what remains unverified**

**81 CPU tests passed:** 38 candidate tests plus 43 unchanged validator tests. Coverage includes real kernel-lock reproduction, monitor cleanup, refusal to bypass an active owner, safe stage reuse, Linux/Windows ArgsEscaped semantics, every other configuration field, malformed metadata, original build provenance, forbidden changes, exact archive digests, resume sequencing, 12,003 actual-catalog schema comparisons, mounted ToolEnv, archive integrity and independent parity/compliance reporting. Also passed: 236 Python syntax checks and eight shell syntax checks. All 33 original validator bundle files and all original rc2 image inputs remain unchanged. No Docker or GPU execution ran here.

Still pending: recorded rc2 smoke/pilot/notebook parity, actual A30 operation, full rc2 634-case parity, exported archive/load, full training reproduction, redistribution permission and submission. The successful build, corrected image verification and GPU preflight are directly evidenced; the separate successful rc2 offline inference is user-reported. CPU tests cannot certify official compliance. All evidence is in `lifemate-final-20261116-rc2/evidence/`.

The latest supplied local Rule/Guide were read; the live timeline confirmed the deadline. The interactive portal exposed no readable updated rule/guide to automated access, so newer hardware clarification remains unknown.

**7. Emergency fallback**

Package bounded-test-passing rc2 immediately; do not start optional full regression. rc1 remains a recovery/control artifact with proven RTX 5090 execution, but has the legacy SDK dependency, needs hostname handling and refuses A30. It is **not a cleared compliant fallback**. Preserve failed candidate evidence; do not change K expectations or disable checks to conceal failure. If mandatory training or transfer requirements remain unresolved, no fully cleared submission can honestly be claimed. The deadline does not authorize a rule violation or unauthorized transfer.
