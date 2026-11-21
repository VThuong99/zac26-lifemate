# Source-only publication handover

Prepared November 21, 2026 for `https://github.com/VThuong99/zac26-lifemate`.
The user explicitly selected this existing public repository. Its visibility is
unchanged. GitHub CLI authenticated as `VThuong99` and confirmed write access.
On November 21, 2026, the user confirmed authority to publicly release the reviewed
team/company source snapshot at `0cb8a6b8a732045c53a583bcadd07839a82c49da`.
The follow-up publication commit records that authorization in documentation and
manifest metadata; the reviewed source files remain unchanged.

## Publication contents

This section describes the initial 379-file public snapshot. The later portfolio
layout adds a traceable developer package, synthetic tests/demo and documentation
as normal descendants of public `main`. The original archive remains unchanged;
see the [current source map](SOURCE_MAP.md) and [validation record](VALIDATION.md).

The [README](../README.md) maps the source tree. The exact 363 copied files are
listed in [MANIFEST.json](../archive/MANIFEST.json). They preserve final inference,
recovered training implementations/recipes, Docker definitions, host validation,
continuation diagnostics and third-party notices. Copied files remain byte-identical
to their local originals. New documentation summarizes architecture, experiments,
lessons and final results without copying per-case datasets.

[PUBLIC_EXCLUSIONS.json](../archive/PUBLIC_EXCLUSIONS.json) records the two omitted
parity reports that contain organizer transcript text. All original organizer
packages, datasets, raw audio, checkpoints, model/native binaries, Docker archives,
per-case research outputs and original Git ancestors remain outside this branch.
The complete local archive and research history are preserved on local `main`.
No frozen RC2 file, original checkpoint, result or existing user change was altered.

## Git boundary

`public-archive-20261121` is a separate local publication branch with a root commit
that has no research-history parent. Creating it does not rewrite `main` or the
P27 branch and does not create another GitHub repository. The target repository
had no refs at inspection. This reviewed branch is authorized for publication to
its `main`; never push `--all`, `--mirror` or
research tags/branches. The full local history contains restricted organizer
content and must not be uploaded.

## Validation and reproducibility

The retained executable source is unchanged from the local archive, whose
applicable CPU suites passed 153 tests. One stale inherited RC1 Ampere test was
excluded and documented. The original 552-entry frozen RC2 tree and image/source
archive hashes were verified. Historical test evidence is recorded in
[VALIDATION.json](../archive/VALIDATION.json); it does not mean the private fixtures
are included in this checkout or that the copied source is a standalone model.

Run `python3 -B scripts/verify_archive.py` to verify this snapshot's 363 copied
files. With access to the original workspace, `--originals-root` compares original
sources and `--frozen-root` checks the complete original RC2 tree. No model,
training, Docker execution or ToolEnv experiment is part of these integrity checks.

The historical training restoration receipt describes 65 original files; one
transcript-bearing restored parity report is intentionally omitted here, along
with its historical duplicate. Training implementation is retained, but complete
training reproduction still needs authorized data, checkpoints and environments.
Actual A30 runtime and final host continuation receipts remain unverified.

## Public-release decision

The complete local history failed the public data audit; details are in
[PUBLIC_RELEASE_AUDIT.md](PUBLIC_RELEASE_AUDIT.md). The publication snapshot excludes
those confirmed data-bearing files and every research-history ancestor. Its
379-file tree passed the secret/content/size/manifest/reference audit, including
verification that all 363 copied source/evidence files match their originals.
The user's confirmation clears team/company source-release authority for this
snapshot. Organizer data remains excluded. No blanket team-code license is invented.
