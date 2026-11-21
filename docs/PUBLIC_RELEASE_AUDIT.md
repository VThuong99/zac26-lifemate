# Public release audit — November 21, 2026

The user explicitly selected the existing **public** repository
`https://github.com/VThuong99/zac26-lifemate`. It is configured as `origin`.
GitHub CLI authenticated as `VThuong99` and verified public visibility and
admin/push permission. `git ls-remote --symref origin` returned no refs.
At that initial check, no content had been uploaded. No repository was created
and visibility was not changed.

## Audited scope

The initial public audit inspected local HEAD
`9f3c660e749b7a079f1242ea1d1534afa056b5e4`: 154 commits on `main`, 155 commits
across all existing branches, and 1,049 distinct reachable blobs totaling
8,573,558 bytes. All blobs were text; none exceeded 10 MiB. No matches were found
for the scanned private-key, GitHub/provider/cloud-token, literal-credential,
credential-bearing URL, JWT or HTTP authorization patterns. These bounded scans
do not establish ownership or detect every possible secret.

The tree contains 12 JSONL files with 1,782 records. Field-name screening was
followed by content verification; field names alone were not treated as proof.
For example, P38's `evidence.reference` field is a path, not a transcript.

## Confirmed restricted-content findings

The original organizer package README, retained locally at
`docs/organizer/README.md`, says the dataset is supplied to registered teams and
must not be shared or redistributed. Public GitHub hosting does not override
that notice.

| File in local Git | Confirmed finding |
|---|---|
| `experiments/p39_historical_asr/decisions.jsonl` | 52 of 172 records contain a nonempty tool name/argument pair exactly equal to the same request's training label; four have an exact `reference_target` match. |
| `experiments/p48_full_trajectory/changed_actions.jsonl` | 25 of 39 records contain exact same-request training-label calls/arguments. |
| `experiments/p49_local_teacher/changed_actions.jsonl` | 57 of 84 records contain exact same-request training-label calls/arguments. |
| `archive/rc2/overlay/training_code/historical/results/p34_gipformer_finetune_v1/export_parity.json` | Contains one complete organizer training transcript. |
| `archive/rc2/overlay/training_code/restored/lifemate/results/p34_gipformer_finetune_v1/export_parity.json` | Second copy of that transcript-bearing parity report. |
| `docs/milestones/p13_gipformer_data_gate.md` | Contains 12 distinct complete training transcripts under normalized matching. |
| `experiments/p34_asr_data_v1/REPORT.md` | Contains one complete training transcript. |
| `experiments/p34_tokenizer_fix_v1/REPORT.md` | Contains two complete training transcripts. |

Call matching compared only `train/train.jsonl` labels and the same request IDs.
Transcript matching used complete NFC/case-folded word sequences of at least
eight words. Findings are counts/hashes, not republished examples. No hidden
environment file, reserved annotation or Private Test label was opened.
These checks establish specific contamination; they are not an exhaustive claim
that every other research record is distributable.

The earlier source-only archive correctly excluded dataset files, audio and
weights, but its two small JSON parity reports retained embedded transcript text.
Both copies stay in the complete local archive for provenance. They are excluded
from the publication snapshot. No frozen original was changed or deleted.

## Publication boundary

**The existing `main` history is not approved for public push.** Removing files
in a later commit or adding ignore rules would still transmit their earlier
blobs. The full research history must remain local. No force-push or history
rewrite is part of this handover.

The separate `public-archive-20261121` branch uses a clean root commit in this same
local Git repository, with no research-history parent. Its explicit file list
contains the selected final source, notices, recipes, checksums and newly written
aggregate documentation, excluding the two parity reports and all raw research
datasets/outputs. It targets the same existing GitHub repository. This preserves
the complete local history rather than modifying it.

The source-selection manifest must reflect the excluded reports. Historical
restoration receipts still describe the original complete local package; they
must not be represented as proof of a fully self-contained public checkout.
Only the publication branch may be considered for upload, never `--all`,
`--mirror`, or tags/branches that make the research history reachable.

## Authorization and reviewed snapshot

On November 21, 2026, the user explicitly confirmed authority to publicly release
the team/company source snapshot at
`0cb8a6b8a732045c53a583bcadd07839a82c49da` to the selected public repository.
That confirmation resolves the source-release authority question in the
historical release records. Organizer data and contaminated history remain
excluded. The follow-up commit changes only documentation and manifest purpose
metadata to record this authorization.

The reviewed snapshot contains 379 files, including 363 exact source/evidence
copies. Every committed blob matched its reviewed file inventory. Checks passed
for secret patterns, complete training transcripts of at least eight words,
263 Python files, 11 shell files, 60 JSON files and 37 documentation links.
There were no binary files or files over 1 MiB. Bounded scans do not establish
ownership or guarantee detection of every possible secret or short excerpt;
source-release authority rests on the user's explicit confirmation.

Third-party Icefall/llama.cpp notices and pinned provenance are retained. No model
weights, proprietary binaries, datasets, audio or Docker archives are included.
No blanket open-source license is invented for team code. The historical
publication and training-restoration records remain evidence of their original
dates. The source-publication authorization above was supplied separately by
the user after review of the concrete snapshot.

Detailed, content-free audit records are saved locally under
`../lifemate-public-audit-20261121/`: repository metadata, history inventory,
secret findings, affected commits and confirmed-content hashes/counts.
