# Packaged SDK finding: prior release reports need correction

Preparation found a concrete inconsistency in the prior reports' claim that the image/source contains no competition SDK.

- `lifemate-release-k-20261115/source/runtime/lifemate/train/zaic_tools/` contains 52 Python files, including a real `ToolEnv`, `Executor`, validation helpers and app implementations. It is not a forwarding shim.
- `source/manifests/source-release.json` inventories those files.
- `evidence/image-file-inventory.json` lists 54 matching entries: the two directories and 52 files under `code/runtime/lifemate/train/zaic_tools`.
- The saved native full notebook's `jupyter_submission.diagnostics/loading.json` records all 52 legacy SDK module files in `worker_details.loaded_release_modules`.
- `schema_feedback_review_v1/policy.py` imports `format_ok` and `schema_error` from `train.zaic_tools.validate`; `scoped_adapter_read_review_v1/policy.py` imports `schema_error` from that same package. The frozen K worker's import chain reaches both helpers. Importing the package also imports its executor/app modules; that alone does not establish that its ToolEnv constructor was called.

The sealed `scripts/run_p10_audio.py::tool_env_for_split` separately imports top-level `zaic_tools` from the selected mounted split, verifies its resolved file is beneath the split and returns that package's `ToolEnv`. Existing one-instance receipts plus this loader support the intended mounted execution path. The new host harness records actual SDK module execution paths/hashes and checks the mounted executor imports as well. It does not claim that a legacy executor module import proves an extra ToolEnv instance or hidden-state access.

Consequently, mounted ToolEnv provenance and reliance on packaged schema helpers are distinct findings. The current evidence cannot support an unconditional statement that inference has no dependency on a packaged SDK. The targeted source-tree scan found no packaged environment/state/input/label/transcript paths matching its rules, but that narrower finding does not clear the SDK issue.

The validation harness leaves K unchanged. It records imports from the known legacy package and marks SDK packaging/import compliance unresolved. It rejects other unexpected SDK origins. Legacy SDK presence does not prevent the requested genuine inference from running, so CLI/notebook trajectory and timing results can still be collected. The overall analyzer returns failure for SDK compliance even when `selected_behavioral_checks_pass` is true, and it lists this as a release blocker. Inspect the separate dimensions rather than treating a nonzero result as proof that Docker inference itself failed.

A future release correction would initialize and verify the selected mounted SDK before importing controller/schema helpers in both parent and worker, replace the two legacy helper imports with the mounted package's helpers, and remove the bundled legacy SDK from a separately staged image. This is a proposal only: helper behavior may differ across SDK versions, so full 634-case CLI/notebook regression against original K, including all step-limit cases, is mandatory before acceptance. Do not edit the frozen image or silently redirect imports during this validation.

No organizer interpretation or transfer permission is inferred. The existing reports and sealed artifacts were not rewritten; this additive audit records the contradiction.
