# LifeMate K host validation

Ready for manual host execution. **No host Docker run was performed by this preparation task.** The sealed image, frozen K, model assets and original evidence remain unchanged. A confirmed legacy SDK dependency remains a compliance blocker; see [SDK_AUDIT.md](SDK_AUDIT.md). Genuine inference is still collected, with behavioral results and compliance reported separately. Run the commands below in a terminal on the host, as `duongthuong` with existing Docker access, not inside the development container and not with `sudo`.

## Host commands

The host must already have `docker`, `nvidia-smi`, `python3` (3.9+), Bash, `flock`, `timeout`, and `tee`. The Docker context must target the local Unix daemon. These scripts do not install anything or load an archive.

```bash
cd /home/duongthuong/GPU_benchmark_host/lifemate-host-validation
./run_host_validation.sh smoke
./run_host_validation.sh pilot
```

Run each command separately and inspect its result before proceeding. Smoke uses the first genuine request, `public_0002`; pilot uses the first ten requests in the frozen input order, `public_0002` through `public_0011`. The pilot analyzer requires all ten cases, their receipts, timing, runtime initialization, SDK-origin evidence and Docker success. It also flags the known packaged SDK dependency; it will not recommend a full run while that compliance finding is unresolved. You can run the pilot to collect diagnostic evidence after a successful smoke execution even if the smoke report fails only this known SDK audit. No mode launches another mode automatically.

The explicit command for all 634 requests is below. First verify all ten pilot cases and review the SDK blocker; this command is provided for a deliberate diagnostic run, not a current release recommendation:

```bash
cd /home/duongthuong/GPU_benchmark_host/lifemate-host-validation
./run_host_validation.sh full
```

Separate notebook validation starts a fresh container and kernel, loads models independently, and executes every cell of the unchanged `/code/predict_notebook.ipynb`:

```bash
cd /home/duongthuong/GPU_benchmark_host/lifemate-host-validation
./run_host_notebook.sh smoke
./run_host_notebook.sh pilot
```

The complete notebook command is below, subject to the same ten-case verification and SDK finding review:

```bash
cd /home/duongthuong/GPU_benchmark_host/lifemate-host-validation
./run_host_notebook.sh full
```

The default device is GPU 0. Append `--gpu GPU-<actual-uuid>` or `--gpu 1` to select one other device. The sealed image supports its validated capability 12.0 backend only; this is not an A30 test launcher.

Each run prints a new directory under `lifemate-host-validation/runs/`, containing both diagnostics and an automatically generated `analysis-*/report.json` and `REPORT.md`. A script exit status of zero means the selected run passed all implemented gates. On this sealed image, a nonzero audit result is expected for the known packaged SDK dependency even if Docker execution and exact parity succeed: inspect `selected_behavioral_checks_pass`, `sdk_compliance_pass`, and the separate execution/parity fields. A nonzero Docker/start/timeout exit code is preserved across `tee`; container exit, tee, and analysis failures also remain failures. Timeout budgets are 600/1,200/7,200 seconds for smoke/pilot/full. A full run does not prove correctness against gold labels or remeasure K's official score.

If preflight reports a busy GPU, wait for its owner to finish. The scripts do not stop existing workloads. They require no compute processes on the selected GPU, at most 1 GiB used, at least 12,000 MiB free and utilization at most 5%. These conservative checks and an advisory validator lock cannot reserve the GPU against other software started later. Do not run CLI and notebook simultaneously.

## Analyze shared results inside the development container

Replace the directory name below with the actual name printed by the host script. The same files are visible through the development mount:

```bash
cd /workspace/GPU_benchmark/lifemate-host-validation
python3 validation.py analyze runs/ACTUAL-RUN-DIRECTORY
```

To check CLI and notebook evidence for the same selected cohort together:

```bash
python3 validation.py analyze runs/ACTUAL-NOTEBOOK-RUN --peer runs/ACTUAL-CLI-RUN
```

Every analysis creates a new `analysis-*` directory; it never overwrites a prior report. `--peer` verifies both outputs against the same K cohort. Each workflow's own report must also pass its Docker/runtime/offline gates. For a raw saved prediction file with original-format diagnostics, use:

```bash
python3 validation.py compare \
  --mode pilot \
  --predictions /absolute/path/submission.jsonl \
  --diagnostics /absolute/path/submission.diagnostics \
  --output /absolute/path/NEW-comparison.json
```

This raw comparison establishes prediction/receipt/timing parity only; it cannot establish Docker execution or offline compliance. `--output` must not exist. On an interrupted run the analyzer examines `.jsonl.partial` and all available receipts, reports missing requests and failures, and refuses to treat the partial file as a completed submission. Early preflight failures retain logs; if `plan.json` was never created, no inference cohort was established and the analyzer will report that missing prerequisite.

## Reference authority and comparison rules

The authoritative predictions are `../lifemate/submissions/submission_K.jsonl`, SHA-256:

```text
cf3a5a654fdfb59f0e8ddb385319ed6c74b3cb8595c6072456d9f64e4e777898
```

Completion/error evidence comes from the original matching files `../lifemate/submissions/challenger_public_run/K/results/{index:04d}-{id}.json`. The original `K/validation.json` attests the same prediction hash. These records contain 634 requests, 1,544 calls, 625 `finished` and nine `max_steps` cases. The nine step-limit IDs are `public_0110`, `public_0187`, `public_0267`, `public_0286`, `public_0329`, `public_0388`, `public_0391`, `public_0392`, and `public_0477`; they are retained, compared and reported rather than treated as missing or discarded failures.

`reference/frozen_k.jsonl` is a compact extraction of those original predictions and their status/error fields. `reference/manifest.json` records the original files' hashes, input/SDK hashes, extracted-file hashes and corroborating native replay identities. `prepare_reference.py` documents how it was created and refuses to overwrite an existing reference directory. The reference bundle stays outside all container mounts. It is local research evidence, not an approved transfer artifact.

The existing native CLI `../lifemate-release-k-20261115/evidence/public_replay/submission.jsonl` and native notebook `evidence/notebook_full/jupyter_submission.jsonl` each corroborate all 634 original K trajectories and statuses. They are not substituted for original K and are not Docker evidence.

The comparator checks complete ID sequence, missing/duplicate/unexpected IDs, request order, ordered calls, names, arguments, final state hashes, status/error, exactly one ToolEnv, receipt prediction identity, actual `tool_result` event order and receipt indices. JSON object key order is ignored; array order, argument values and JSON numeric representations are preserved. The report includes every differing call and hash, missing evidence, and the earliest observable action/status divergence. Internal reviewer differences before an emitted call are not claimed as the earliest model-token divergence; original full request/event records remain available for follow-up.

Timing is independently checked: integer milliseconds must be `0 <= time < 30000`, agree with the fresh receipt's measured dispatch duration, and the duration must be finite and below 30 seconds. Native and container timings are never required to match. Loading time is reported separately. Sampling can miss GPU/RAM peaks; Docker stats and selected-GPU samples are retained for inspection. RTX 5090 measurements do not establish A30 performance, a cold filesystem-cache startup, or organizer acceptance.

## Container isolation and provenance

The runner verifies the original sealed archive against the pinned authoritative `ARTIFACTS.json`: full SHA-256, MD5, size, gzip integrity, embedded configuration digest, Docker-save metadata, and streamed uncompressed layer digest. This reads the 17 GB archive on every run and may take several minutes; nothing is extracted or changed. The historical config digest `sha256:ca9030a7989aed1279c3ad850bc49d2a9950fc6b74c10bcb96811785757b8247` is kept separate from Docker's store ID.

Legacy stores may report that config digest. Containerd stores may report a manifest/index target digest instead. The verifier derives permitted target descriptors from the verified archive; it reproduces the saved host's `sha256:92212d536574ef62f6ab32edaf4c9ce926e64ffb4863e6864bd61c979d708755` without hard-coding it as an accepted ID. A matching RootFS DiffID alone never passes. Loaded OS, architecture, filesystem identity and all supported runtime configuration fields must also match. Unknown IDs, descriptor encodings or configurations fail closed with expected/actual details.

`image-identity.json`, `image-identity.log`, and `verified-image-reference.txt` record the verified provenance and actual immutable Docker reference used for creation. The created container is checked against that reference before inference, and the analyzer uses the same evidence. See [IMAGE_IDENTITY.md](IMAGE_IDENTITY.md) for the digest distinctions and supported representations. The original archive and image remain untouched.

Only `/home/duongthuong/GPU_benchmark_host/lifemate/public_test` is mounted as `/data/public_test`, read-only. The `/data` parent layout matches `discover_split()` in the sealed entrypoint. Input JSONL, tools catalog, SDK sources and selected audio hashes are checked before launch. The environment directory is checked for existence only; the harness never reads/copies/parses its contents. The organizer SDK performs its own permitted state access.

Every container uses `--network none --hostname lifemate-offline --add-host lifemate-offline:127.0.0.1`, one selected GPU, 16 CPU quota, 48 GiB RAM with swap disabled, 2 GiB shared memory, and a 1,024-process limit. The 48 GiB limit leaves host headroom below the supplied 64 GB machine budget. CPU quota does not pin sixteen physical cores. Containers run with the invoking host UID/GID, dropped capabilities and no new privileges. Result, home and cache files remain host-user writable. Cold process startup is measured; host page caches are not flushed.

A new result directory and diagnostics directory are used every time. Only container helpers are copied into the fresh run and mounted at `/validation`. `sitecustomize.py` records real `zaic_tools` module executions in the spawned inference worker and notebook kernel, including path and SHA-256. It records the known `/code/runtime/lifemate/train/zaic_tools` imports as a compliance finding and rejects any other unexpected SDK origin. The analyzer matches those imports against the mounted SDK manifest and requires executor import evidence. This instrumentation records imports without replacing ToolEnv methods or inference decisions. The sealed loader also checks its SDK origin. Name-based scans under `/code` and `/opt/k-python` record packaged SDK paths and reject split inputs, environment folders and common label/transcript/state files. The known legacy SDK is left available so K executes unchanged; the analyzer fails its separate SDK compliance gate. This is a targeted packaged-data check supported by image identity and existing release inventory, not a general proof of every possible information flow.

The runner records creation arguments, image/container inspect data, logs, GPU snapshots, Docker statistics, source/helper hashes, exit codes, and cleanup outcome. It stops/removes only the exact container ID it created, with a bounded stop followed by kill of that same ID if necessary. It never prunes Docker, changes the image, resets GPUs or stops unrelated containers. A forced host shutdown/SIGKILL can prevent shell traps; the recorded container ID identifies the owned container if manual cleanup is needed.

## Offline hostname issue

See [OFFLINE_HOSTNAME.md](OFFLINE_HOSTNAME.md) for the source trace, evidence limitations, isolated test and minimal unapplied patch. The existing-image workflow always retains the proven mapping. Removing it is not authorized as a conclusion of the isolated unit test; a separately identified candidate must pass independent offline CLI/notebook parity without hostname flags.

## Release audit and present status

The supplied local rules and release compliance matrix were reviewed, without querying the competition website. Original release status files predate the host testing described in the handoff.

| Dimension | Evidence available at preparation | Remaining gate |
| --- | --- | --- |
| Docker execution | User reports load, GPU/offline smoke and `public_0002` exit 0 | Inspect new host-generated logs and container states for these runs |
| Runtime initialization | Native CLI/notebook established; host ASR/LLM success user-reported | Fresh `loading.json`, preflight and container success |
| Exact K parity | Original baseline and two native runs verified, 634/634 | Host pilot 10/10, then full 634/634 |
| Timing | Native max about 6.15/6.17 seconds; host smoke 2,825 ms user-reported | Per-request host timings, resource evidence; A30 separately |
| Notebook parity | Native 634/634; no complete host notebook evidence inspected | Independent host notebook pilot and full execution |
| Offline compliance | Source DNS dependency identified; user reports mapping works | Network-none evidence for selected runs; independently verified no-flags fix |
| Mounted SDK / packaged dependency | Loader checks mounted ToolEnv origin, but 52 legacy SDK modules are bundled and appear in saved native worker imports | Actual mounted-worker imports plus resolution of legacy schema-helper dependency; see SDK_AUDIT.md |
| A30 | Original sealed backend explicitly rejects capability 8.0 | Qualified backend plus actual A30 behavior, 24 GiB memory and timing tests |
| Training reproduction | 65 restored source files; known local asset hashes verified in prior evidence | Full authorized audio/preparation/base/environment closure and clean-machine reproduction |
| Transfer permissions | Prior reports explicitly unresolved | Company/asset redistribution approval and approved destinations |

The only file under the supplied `validation_result_rtx5090` directory at inspection was `smoke1.diagnostics/llama-server.log`: it shows LLM loading and teardown but does not supply the successful prediction, ASR traceback, exit receipt, or full parity evidence. The successful smoke information in the handoff is therefore recorded as user-reported, not independently reverified here.

Local requirements additionally specify total parameters below 6B, LLM below 5B, context at most 16,384, fixed seeds/deterministic decoding, one ToolEnv per request and every actual call emitted. Existing release documentation records a conservative 5,670,135,589 total bound, a 4,659,865,088 source LLM bound, context 8,192 and seed 20261030. This workflow checks the frozen image and runtime behavior; it does not retrain or recompute the full parameter inventory. The required notebook and `/code/predict.sh` interfaces are exercised separately. The local rules specify A30/Xeon 6442Y; the supplied guide names RTX 5090/Xeon 6459C and has differing CUDA wording. Those differences remain unresolved. No online rule refresh, publication, upload or submission was performed.

The prior reports' claim that no SDK is bundled is contradicted by the source manifest, image inventory and native notebook loading receipt. This additive audit records that finding without editing the original reports.

Overall release status remains **RELEASE_BLOCKED**, even if an RTX 5090 host run passes. The report generator separates Docker execution, model initialization, exact parity, timing, notebook, offline status, A30 and remaining blockers.

## Local verification

```bash
cd /workspace/GPU_benchmark
bash -n lifemate-host-validation/run_host_validation.sh lifemate-host-validation/run_host_notebook.sh lifemate-host-validation/container/entry.sh
python3 -m unittest discover -s lifemate-host-validation/tests -v
```

These are syntax checks and CPU-only evidence/unit tests. Synthetic analyzer fixtures do not count as host validation. The runner's development-container guard was tested and rejected execution before contacting Docker. See `local_checks/` for the preparation receipts. Stop here and execute the selected host commands manually.
