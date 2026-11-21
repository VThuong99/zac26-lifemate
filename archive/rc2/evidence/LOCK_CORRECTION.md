# rc2 monitor lock cleanup correction

Existing image verification and GPU preflight passed. GPU evidence is in `runs/20261116T142101Z-gpu-qtxYSa/`. Its report and pass receipt validate against the unchanged BUILD.json, SHA-256 `cc21548d068e44aa82d616d526285bd211af380f0f2d73fafb574776c25de981`.

Next host command, reusing both successes:

```bash
bash /home/duongthuong/GPU_benchmark_host/lifemate-final-20261116-rc2/host.sh smoke 0
```

After smoke succeeds, run `host.sh pilot 0`, `host.sh notebook 0`, then `host.sh package 0`, stopping on any failure. Alternatively, corrected `host.sh resume 0` verifies current image identity, skips authenticated successful stages, and executes remaining checks and packaging. No build or upload occurs.

The resume parent branches before acquiring the stage lock; it does not hold a nested lock. The reproducible defect is inherited descriptors: the resource monitor inherited FDs 8 and 9, and cleanup used a subshell to signal/wait for a child started by its parent shell. That subshell cannot wait for the parent's child. The stage could exit while the monitor was still handling SIGTERM, leaving both locks held long enough to reject the next stage. The original source was preserved and a CPU test reproduces the failure with real Linux flock and a controlled monitor.

The development container's process namespace exposes no current holder. This does not establish absence of host activity or identify the holder retrospectively. A lock pathname left on disk is not itself a held flock. The corrected host script retains kernel locking, waits at most 20 seconds, and reports host lock information if contention persists. No production lock was deleted, unlocked, bypassed or acquired during this investigation, and no host process was signaled.

Changes: the monitor closes FDs 8/9 before execution; cleanup signals only its recorded task child and waits in the shell that started it; resume authenticates stage receipts and skips completed stages, while corrupt receipts stop execution. Only `host.sh` and `tools/candidate.py` changed within the execution context. The original BUILD.json, GPU evidence, image source, container harness, archive packager, frozen K, rc1 and rc2 image identities remain unchanged.

`lock-before/` preserves the previous tools and context manifest. `lock-correction.json` records the exact prior context and BUILD/evidence hashes. The validator accepts the new host context only through this narrow attestation: all previous files except the two named host tools must remain identical, and the original tools' snapshots must match the previous manifest. No evidence is relabeled as if it ran under the new host tools.

Validation: 38 candidate CPU tests plus 43 original validator CPU tests passed; 236 Python files and eight shell scripts passed syntax checks. Regression coverage includes the old inherited-lock failure, corrected child reaping and lock release, refusal to bypass/unlink an actively owned test lock, GPU evidence reuse, corrupt receipt refusal, and rejection of image/harness/packager/BUILD changes. Test processes and locks are isolated CPU fixtures. Logs are `lock-correction-cpu-tests.log`, `lock-correction-original-validator-tests.log`, and `lock-correction-syntax.json`.

Actual A30 runtime, complete training reproduction, redistribution authorization and final archive export remain unresolved. Stop before external transfer or submission.
