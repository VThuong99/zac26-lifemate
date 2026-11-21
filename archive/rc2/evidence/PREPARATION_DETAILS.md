# LifeMate — final submission actions, 16 November 2026

**Next action on the host (no report review required):**

```bash
bash /home/duongthuong/GPU_benchmark_host/lifemate-final-20261116-rc2/host.sh build
```

This builds a separate image offline from the already imported, verified rc1, checks its files/configuration, then performs a short GPU availability test. It does not run inference, upload, submit, overwrite rc1, or stop another user's processes. If the GPU is busy, the completed build is retained; retry the `gpu` step below when idle. Do not rerun `build` over an existing candidate.

**1. Deadline and best candidate.** The deadline is **16 November 2026, 23:59 GMT+7 = 16:59 UTC**, confirmed by the [official live timeline](https://challenge.zalo.ai/) and the retained Rule, “Submission Guidance.” At 20:35 GMT+7, approximately 3 h 24 min remained. Package as soon as the bounded checks pass. Reserve **22:00–23:59** for export, transfer, and manual submission; the scripts refuse tests whose allotted time would cross 22:00. Start transfer earlier on a slow uplink: 17 GB takes roughly 114 minutes at 20 Mbit/s, before overhead. No 634-request run is scheduled.

Preferred candidate: **`lifemate-k:k48.46-20261116-rc2`**, prepared under `lifemate-final-20261116-rc2/`. **Source/build handoff only until the host command succeeds; no rc2 Docker image/archive has been produced in the development container.** K = 48.46 is the protected original score, not a newly measured rc2 score.

The Rule explicitly names “1 NVIDIA A30 GPU”; Docker Guide p4 names “1 × NVIDIA GeForce RTX 5090 (32 GB).” The conflict remains unresolved. The candidate retains the original `sm120` backend on capability 12.0 and selects the existing dual-target native backend on capability 8.0. Other capabilities fail. The dual library has 146 native sm_80 and 146 sm_120a code objects; its earlier native RTX 5090 run matched K 634/634. **This does not establish A30 execution.** The old rejected sm80-only backend is not used. CUDA base/runtime requirements are preserved; an A30 host also needs a compatible NVIDIA driver.

**2. Exact SDK determination and correction.** Guide p6 says: **“zaic_tools của split, KHÔNG dùng bản đóng trong image”** (use the split SDK, do not use the version packaged in the image). This is a use restriction; the supplied documents do not establish a separate ban on mere unused file presence. The Rule says app data is accessed “only through the organisers' zaic_tools, with exactly one ToolEnv per sample,” and: **“At inference only validate, call, get_tool_calls and get_state_hash may be used; get_state, states, Executor, Simulator or cloning the env are not allowed (get_state is for train only).”** It also prohibits reading, copying or parsing files under `<split>_environment/` directly and requires every actual call in the submission.

The successful rc1 host smoke recorded **104 packaged module executions** (52 in each of two processes), **44 mounted SDK module executions**, and one ToolEnv for `public_0002`. Mounted modules resolve under `/data/public_test/zaic_tools/`, including `__init__.py` and `executor.py`. Packaged modules resolve under `/code/runtime/lifemate/train/zaic_tools/`. The two direct consumers import `format_ok`/`schema_error`; importing their package also executes its initializer and imports executor/app modules. **This is not evidence that a bundled ToolEnv/Executor instance was used.** The unchanged worker factory imports the mounted `zaic_tools`, checks its origin, and returns its ToolEnv. The existing constructor counter recorded one instance. Original import logs alone cannot prove every file access; the new host harness records and rejects environment-file opens outside the mounted SDK.

No official text separately addresses independent schema-formatting helpers. rc2 removes the ambiguity: two imports now use a new state-free local proposal checker, with no SDK import or environment access. All actual validation/execution still goes through the mounted ToolEnv. The checker preserves the old error strings, ordering, date/time edge cases and proposal acceptance semantics. No policy branch, prompt, state-integrity check or actual-call logging was relaxed. The final Dockerfile flattens the resulting filesystem into one new layer, so the removed SDK is not retained in an inherited archive layer.

Other changes: Icefall's diagnostic `"IP address"` lookup becomes `None`, avoiding hostname DNS; the existing dual backend is added for Ampere; the recovered 65-file training source supplement is included. Models, tokenizer, ASR settings, original Blackwell binaries, notebook cells, watchdog, and frozen controller are unchanged. The original validator and its SDK findings remain unchanged.

**3. Run these host commands one at a time.** Results stay under `lifemate-final-20261116-rc2/runs/`. Each successful stage prints a report; do not proceed after a failure. Comparisons use the original K reference on the host, never mounted into inference. No special hostname flags are used. GPU occupancy checks and the shared validation lock protect unrelated workloads.

```bash
# Only if build completed but its GPU check was blocked by a busy GPU:
bash /home/duongthuong/GPU_benchmark_host/lifemate-final-20261116-rc2/host.sh gpu

# Actual offline GPU inference, public_0002, exact calls/hash/status and <30s:
bash /home/duongthuong/GPU_benchmark_host/lifemate-final-20261116-rc2/host.sh smoke

# Ten requests, same exact comparison and actual-call/ToolEnv-count checks:
bash /home/duongthuong/GPU_benchmark_host/lifemate-final-20261116-rc2/host.sh pilot

# Fresh notebook kernel, unchanged cells, same ten requests and K comparison:
bash /home/duongthuong/GPU_benchmark_host/lifemate-final-20261116-rc2/host.sh notebook

# After the preceding gates pass: export locally, verify, checksum. No upload:
bash /home/duongthuong/GPU_benchmark_host/lifemate-final-20261116-rc2/host.sh package
```

Append a GPU index/UUID as the second argument if device 0 is not the intended idle GPU. Do not kill other users' workloads. The scripts reuse authenticated rc1 load evidence and check the image/configuration/filesystem identities rather than rehashing its unchanged 17 GB archive. The new export is streamed once: Docker-save structure, configuration, blob digests, uncompressed layer DiffIDs, SHA-256, MD5 and successful stream completion are checked. Partial exports are never marked complete or overwritten.

Expected outputs in `lifemate-final-20261116-rc2/artifacts/`:

- `lifemate-k-k48.46-20261116-rc2.tar.gz`, `.sha256`, `.md5`;
- `lifemate-k-source-20261116-rc2.tar.gz` (supplementary inference/training source; weights and backend binaries are in Docker);
- `RELEASE.json` with exact image/config/layer/archive identities, source checksum and bounded validation evidence. These are generated by the host, not asserted in advance.

**4. Mandatory blockers and human approvals.** Full compliance is **not established**. Guide p15 requires **“Cung cấp đầy đủ Training Code & Data”**, says BTC will reproduce training using `training_code/`, permits immutable external download URLs with internet during reproduction, and says training-only base models must stay out of Docker (only inference weights belong inside). Source restoration is included, but complete authorized training inputs/audio/preparation dependencies, immutable restore URLs, the historical environment and clean-machine reproduction remain incomplete. See `overlay/training_code/README.md` and `TRAINING_ASSET_STATUS.json`. Do not describe the recovered source as a completed reproduction.

Before any external transfer, obtain explicit written company authorization for the exact image/checkpoints/source/training assets, the destination account and the required **“Anyone with the link”** exposure. Confirm model/dependency and organizer-data permissions. The package README prohibits redistribution of the organizer dataset; do not upload that dataset publicly to fill the training gap. Resolve an authorized organizer-accessible restoration method. No authorization has been provided here. Local build/export does not imply transfer permission. The team owner must manually review and submit the final artifact; nothing uploads or submits automatically.

**5. Exact official transfer/submission sequence, after permissions and mandatory requirements are satisfied.** Guide pp4–18 requires `/code/predict.sh` to read mounted `/data` and write `/result/submission.jsonl`; `predict_notebook.ipynb` must run all cells, write `/result/jupyter_submission.jsonl` with integer millisecond `time`, and produce the same scored result. JupyterLab is required. The image contains the models and dependencies; inference is offline. The provided notebook and CLI retain these interfaces.

Guide pp14/18/19 requires a `docker save` gzip archive, its **MD5**, Google Drive sharing as **“Anyone with the link”**, then the link/checksum in the organizer's solution form. The retained Rule permits at most **two solution submissions**, evaluating only the last.

After `package` succeeds:

1. Read `artifacts/RELEASE.json`; use its final filename, byte count and MD5. Inspect the saved smoke/pilot/notebook reports and disclose remaining unverified A30/full-regression status. Do not upload a `.partial` file.
2. With the written approvals above, manually upload that exact `.tar.gz` to the approved Drive account. Keep the file immutable. Set the required link access; check the link while signed out. Verify the uploaded/downloaded artifact's size and checksums when transfer tooling permits, rather than assuming an upload completed.
3. If time and an authorized second host permit, verify the received archive's `.sha256`/`.md5`, `docker load -i` it, and exercise `/bin/bash /code/predict.sh` with the test parent mounted read-only at `/data` and an empty writable `/result`, `--gpus '"device=0"' --network none`. rc2 needs no hostname mapping. Do not rerun GPU tests on an occupied device.
4. Open the [LifeMate portal](https://challenge.zalo.ai/portal/lifemate), select **Solution Submission**, provide the final Drive link and MD5 plus the requested team/source/training details, and submit manually before **23:59 GMT+7**. Confirm the portal accepted the intended final link/checksum and save its confirmation. This is different from uploading a public-test JSONL. Do not assume the optional Test Solution feature is still open.

**6. Evidence and remaining risks.** Local checks: **17 candidate CPU tests + 43 unchanged validator tests passed**; 12,003 actual-catalog schema comparisons plus format/boundary cases; 234 Python syntax checks and eight shell syntax checks. ToolEnv tests used only author-created synthetic state. The original frozen K hash remains `cf3a5a654fdfb59f0e8ddb385319ed6c74b3cb8595c6072456d9f64e4e777898`. Original rc1 archives/image were not changed. Candidate change inventory and original import evidence: `lifemate-final-20261116-rc2/evidence/preparation.json` and `sdk-import-evidence.json`; test logs are alongside them.

Not yet verified: rc2 Docker build, real offline startup without hostname flags, smoke/pilot/notebook parity, A30 ASR/LLM initialization and memory/timing/behavior, full rc2 634-case parity, final exported archive/load, complete training reproduction, redistribution authorization and actual submission. CPU equivalence tests reduce schema risk; they do not certify runtime or official compliance. A30 may behave differently despite native sm_80 coverage. Consequential call/state differences must be reviewed honestly; compilation is not an A30 qualification.

The latest locally supplied Rule and Guide were read. The live public timeline confirms the deadline; the interactive LifeMate portal did not expose readable rule/guide content to the automated read, so a newer hardware clarification could not be verified. Local source identities: Rule SHA-256 `ea40d983e2546bedd38d0b841be82195cf0722b3838ba4eef4c1cf915b8c73ad`; Guide SHA-256 `9824a989dede28c1e6fe10a28033548a0a3325759ec5b2a5bd2d38ab71638364`.

**7. Emergency fallback.** Stop optional work and package the bounded-test-passing rc2 immediately; no full run is required by this handoff. The preserved rc1 is a recovery/control artifact with proven RTX 5090 execution, but it still has the packaged-SDK dependency, needs hostname handling and explicitly refuses A30. It is **not a cleared compliant fallback**. If rc2 fails, retain the failure evidence and original image; do not hide it by changing expected K outputs or disabling checks. If mandatory training/rights requirements cannot be resolved, there is no fully cleared submission to claim. A deadline does not authorize bypassing the rules or unauthorized transfer.
