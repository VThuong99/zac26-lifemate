# Source-only archive

Prepared November 21, 2026 as a source-only publication candidate. The original frozen RC2,
checkpoints, datasets, ledgers, host workflows and Docker archives remain at their
original workspace paths. No original file was moved, deleted or overwritten. This publication snapshot
omits two JSON parity reports containing organizer transcript text; its source
manifest therefore has 363 entries. Historical restoration receipts describe the
complete local layout and can refer to those omitted files.

- `rc2/`: selected text source, recovered training code/recipes, Docker definitions,
  dependency/model manifests, release checksums and aggregate validation receipts.
- `host_validation/`: source helpers used by the original host workflows.
- `private_test/`: continuation and investigation source/tests, without Private
  Test inputs, raw audio, prompt screens, prediction files or host run output.
- `MANIFEST.json`: exact 363 copied files with original workspace-relative path,
  byte count and SHA-256. Copies are byte-identical, including historical wording.
- `PUBLIC_EXCLUSIONS.json`: two transcript-bearing parity reports omitted from
  this snapshot, with original hashes and local preservation paths.
- `FROZEN_RC2_SHA256.json`: all original RC2 regular-file hashes and symlink targets.
- `WORKSPACE_INVENTORY.json`: original directory counts/sizes, without file contents.
- `RESEARCH_INDEX.csv`: 385 original report/catalog/ledger fingerprints for local
  navigation, not a complete copy of research data or every experiment artifact.

Excluded from the source copy: model/native binaries, Docker/source tar archives,
large `overlay/manifests/python-files.json`, Python packages, organizer SDK/data,
raw audio, individual prediction/trace outputs, caches and credentials. The full
original release and inventories preserve these where they already exist. Pinned
Icefall source and its license are retained where included in the RC2 source.

**This directory is not a complete build context or a standalone runnable model.**
Original scripts may expect their original sibling-directory layout, unbundled
assets, absolute paths or private test fixtures. Historical READMEs and status
files describe their own dates; use the new top-level documentation for final
status. Do not run archived research scripts to discover dependencies.

Check copied files with `python3 -B scripts/verify_archive.py` from the repository
root. Supply `--originals-root ..` to compare originals, and
`--frozen-root ../lifemate-final-20261116-rc2` to rehash the complete frozen tree.

Local preservation does not authorize redistribution. Source/company rights,
organizer derivatives and existing Git history still require review before any
private upload. No new license or public-release permission is asserted.
