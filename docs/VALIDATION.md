# Portfolio validation record

Validation performed on November 21, 2026, using a fresh clone of public `main`
at `5799264cc7fa4594b890e81600a959c9fbaf2be5`. The separate research checkout and
original RC2 tree were not edited. No GPU training, model inference, organizer
ToolEnv execution or leaderboard submission was performed.

## Local checks

| Check | Result and scope |
|---|---|
| Python 3.12 maintained suite | **48 tests passed**, synthetic core/integration/provenance tests |
| Self-contained archived helpers | **56 tests passed**: 30 host comparison/identity, 16 host/recovery safety, 6 failure-analysis, 4 transport |
| Ruff 0.11.13 | Maintained Python syntax/undefined-name/control-flow checks passed |
| Package installation | Editable install and isolated wheel install succeeded |
| Wheel execution | Demo completed from `/tmp`; isolated imports loaded no Torch, Transformers, Sherpa, NumPy or organizer SDK |
| Source mapping | 15 modules equal frozen sources after only declared import relocation |
| Published archive | All 363 manifest copies match SHA-256 and size |
| Original workspace integrity | All 363 original source copies and 552 frozen RC2 entries match the pre-existing manifest, including the Docker archive |
| Training export | 64 public source files verified; excluded transcript-bearing report omitted; overwrite and repository destinations rejected |
| Repository checks | 418 publication files; 290 Python, 62 JSON/notebook and 11 shell files parsed; TOML and maintained local Markdown links checked; no scanned credential patterns or prohibited payload files found |

The archived Icefall `utils.py` emits an existing Python 3.12 `SyntaxWarning`
about an escape sequence during AST parsing. It parses successfully; the frozen
upstream file is intentionally unchanged.

## Historical test limitations

A blanket run of the archived private-workflow directory reported **49 tests
run, 34 errors** (including a class-setup error). Its missing dependencies include
the excluded official validator/catalog and original-host identity/loading
receipts. These are pre-existing portability constraints, not a passing test
result. No private SDK or placeholder validation result was added to satisfy it.

The explicit archived-helper runner selects the reproducible tests from that
directory and other source-only suites. Original candidate/host-evidence tests
that require private workspace assets are not part of CI. The old transport
test expecting an unconditional Ampere rejection describes RC1, so the maintained
suite separately checks RC2 selection with a mocked GPU; this does not qualify
real A30 hardware. See [evaluation](EVALUATION.md) for full scope.

## CI and interpretation

[CPU checks](../.github/workflows/ci.yml) runs the maintained and selected archived
suites, source/integrity/publication checks, demo and wheel build on Python 3.11
and 3.12. The [GitHub Actions page](https://github.com/VThuong99/zac26-lifemate/actions/workflows/ci.yml)
is the authority for the status of a particular commit.

Passing tests establish the documented lightweight contracts. They do not prove
full K policy equivalence after a future refactor, clean-machine inference or
retraining, official evaluator parity, semantic correctness, or artifact
redistribution rights. Secret-pattern/file scans are bounded checks. All new
runtime source derives from the already authorized public snapshot; restricted
data and original research ancestors remain outside the publication history.
