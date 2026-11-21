# LifeMate 2026 — source archive

Source-only archival snapshot for the team's Zalo AI Challenge 2026 LifeMate work.
The competition is over for this team. **The frozen K48.46 RC2 solution achieved
19.6 on the official Private Test leaderboard (user-reported).** No portal receipt
was available for independent verification. No further training, optimization or
experiments are part of this archive.

LifeMate maps Vietnamese speech, conversation history and installed-tool context
to actual tool executions. A request must produce the ordered calls and the final
state hash from its own organizer `ToolEnv`. Local rules record a 30-second request
limit, less than 5B LLM parameters, less than 6B total parameters, at most 16,384
context tokens, and offline inference. RC2 actually uses **8,192 context tokens**,
seven decision steps and seed `20261030`. Earlier A30 requirements and the later
RTX 5090 Docker guide describe different hardware; see the qualifications below.

## Final system

Current and historical audio pass through P34 epoch-2 Gipformer RNNT ASR, with
scoped CTC/confidence and PhoWhisper corroboration. A P9/P19-adapted
**Qwen3.5-4B Q8_0** planner emits strict JSON decisions. Two dynamically routed
LoRA reviewers support write and terminal decisions. The composed agent handles
reference lookup, temporal interpretation, conditions and continuation; the
controller validates and executes calls through one split-matched `ToolEnv`.

The deployed behavior is the RC2 entrypoint and its complete imported policy
chain, not just the older top-level `src/agent.py`.
See [architecture](docs/ARCHITECTURE.md) and [final results](docs/FINAL_RESULTS.md).

## Repository map

```text
README.md
docs/
  ARCHITECTURE.md          final runtime and historical training recipes
  EXPERIMENT_HISTORY.md    evidence-based research summary
  LESSONS_LEARNED.md       evaluation and reliability lessons
  FINAL_RESULTS.md         score provenance, identities and limitations
  ARCHIVAL_HANDOVER.md     preservation inventory and GitHub handover status
  PUBLIC_RELEASE_AUDIT.md  audit findings and publication boundaries
archive/
  MANIFEST.json            exact copy list, original paths, sizes and SHA-256
  FROZEN_RC2_SHA256.json    original RC2 tree integrity baseline
  WORKSPACE_INVENTORY.json pre-archive workspace sizes and file counts
  RESEARCH_INDEX.csv      local research report/catalog/ledger fingerprints
  PUBLIC_EXCLUSIONS.json  data-bearing reports excluded from this snapshot
  rc2/                    source-only RC2 copy, recipes and release receipts
  host_validation/        original host identity/validation helper source
  private_test/           original continuation and diagnostic helper source
scripts/verify_archive.py  CPU-only archive integrity check
```

This snapshot retains 363 exact source/configuration/evidence copies. Two parity
reports containing organizer transcript text are excluded. The complete original
archive, research history and uncommitted work remain local and are not ancestors
of this publication branch. Inference code is unchanged.

## Reproduce inference

These are reference instructions for a future authorized reproduction. They were
**not executed** during archival. A Git checkout alone has no weights, native
binaries, organizer SDK/data or complete training environment.

Use the preserved original image at
`../lifemate-final-20261116-rc2/artifacts/lifemate-k-k48.46-20261116-rc2.tar.gz`.
Its SHA-256 is
`e2aaa0a3c8f54e673f7700c443846a974be09257f3e28145ca9f0fb5076232f5`.
First verify the local originals:

```bash
python3 -B scripts/verify_archive.py --originals-root .. --frozen-root ../lifemate-final-20261116-rc2
cd ../lifemate-final-20261116-rc2/artifacts
sha256sum -c lifemate-k-k48.46-20261116-rc2.tar.gz.sha256
docker load -i lifemate-k-k48.46-20261116-rc2.tar.gz
```

Verify the loaded image's configuration and rootfs identities against
[RELEASE.json](archive/rc2/artifacts/RELEASE.json) using the retained
[image identity guide](archive/host_validation/IMAGE_IDENTITY.md).
An image-store ID, OCI manifest digest and configuration digest are distinct;
a matching tag alone is insufficient. Set `RC2_IMAGE_ID` to the verified loaded
immutable ID. On a qualified GPU host with a fresh writable result directory:

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

The mounted root must contain a split directory with its matching JSONL, tool
catalog, audio and `zaic_tools`. Use `--split SPLIT` after `predict.sh` if several
splits exist. Omit `--limit` for a complete run. Output has exactly `id`,
`tool_calls`, `state_hash`, and integer millisecond `time`. A failed request aborts
the submitted batch entrypoint and leaves `.partial` plus diagnostic evidence.
The separate Private Test continuation driver changes that batch behavior;
it is not an equivalent replay of the submitted entrypoint.

RTX 5090 RC2 smoke/CLI/notebook parity receipts are preserved. Actual A30 execution
was not established. Driver/CUDA compatibility must follow the recorded host
workflow; do not silently replace the backend or enlarge context. The image is
the strongest preserved inference artifact. Rebuilding from the source-only
copy additionally requires the original base/rootfs, native and Python assets.

## Research and training reproduction

[Architecture](docs/ARCHITECTURE.md) maps each trained component to its recipe.
The [historical 65-file training restoration receipt](archive/rc2/overlay/training_code/restored/lifemate/RESTORE_RECEIPT.json)
and [training restoration record](archive/rc2/overlay/training_code/TRAINING_RESTORATION.md)
retain historical implementations and limitations. Authorized audio, reviewed
training inputs, base checkpoints and environment restoration remain necessary;
no clean-machine retraining has been demonstrated. Original checkpoints remain
in their existing locations.

Read [experiment history](docs/EXPERIMENT_HISTORY.md) and
[lessons learned](docs/LESSONS_LEARNED.md) before interpreting local scores.
Public scores 40.63 / 44.69 / 46.11 / 48.46 are historical user reports, not
independently verified portal receipts. Local approximate scores are a separate
evidence class.

## Archive checks and sharing

```bash
python3 -B scripts/verify_archive.py
```

This checks copied bytes only; it runs no model, training or ToolEnv. Additional
lightweight validation and remaining handover requirements are recorded in
[ARCHIVAL_HANDOVER.md](docs/ARCHIVAL_HANDOVER.md).

The intended destination is the existing public repository
`https://github.com/VThuong99/zac26-lifemate`. This source-only publication branch
contains no original research-history ancestors. The
[public-release audit](docs/PUBLIC_RELEASE_AUDIT.md) records the restricted
content excluded from the complete local archive. Team/company source-release
authority must be confirmed before upload; no blanket open-source license is
granted here. Never add organizer datasets, audio, weights, Docker archives,
credentials or assets with unresolved redistribution rights.
