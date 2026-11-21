# Testing and evaluation

## Reproducible CPU checks

The maintained suite is `python -m unittest discover -s tests -v`. Its fixtures
are handwritten and synthetic. Tests exercise the actual extracted core and
the archived `predict.py` transport, using mocked HTTP/ASR/GPU boundaries.

| Coverage | What it establishes |
|---|---|
| Parser and HTTP transport | One strict decision, request schema, remaining timeout and surfaced failures |
| Agent/controller | Observations feed decisions; rejected or late proposals do not execute; historical effects are not replayed |
| ASR boundaries | Audio paths stay inside the split; reference text is excluded/replaced; history and current audio use the recognizer |
| Local evaluation | One-to-one call matching, exact JSON types, Unicode normalization, state gating and missing-output handling |
| RC2 transport | Split selection, reference-field rejection, prefix preservation on overflow, no clobber of completed output |
| Source/export | Import-only derivation, archive hashes, CPU-safe imports and exclusion of the restricted training report |

`python scripts/verify_archive.py` verifies 363 published copied files against
their manifest. On the original authorized workspace, optional arguments also
verify all original copies and the complete frozen tree:

```bash
python3 -B scripts/verify_archive.py \
  --originals-root .. --frozen-root ../lifemate-final-20261116-rc2
```

This reads and hashes artifacts; it does not load models or execute an SDK. The
frozen tree includes large local archives, so the optional check takes longer.
`python scripts/verify_source_layout.py` separately verifies the 15 core modules.
`python scripts/check_repository.py` checks syntax, maintained local doc links
and bounded publication rules. Ruff checks syntax, invalid control flow and
undefined names without reformatting the preserved implementations.

## Local state-gated metric

[evaluation.py](../src/lifemate/evaluation.py) scores actual predicted calls using
maximum one-to-one matching from [tool_call_matcher.py](../src/lifemate/tool_call_matcher.py).
Matching ignores call order; real execution order still determines state.
For a sample with gold calls, the local score is call F1 only when the final
state matches and at least one call matches; otherwise it is zero. The empty-gold
case has its historical special rule. A missing prediction always scores zero.

Fuzzy arguments are selected by the catalog and use lowercase NFC whitespace
tokenization with a strict threshold above 0.6. This is a local approximation;
official tokenizer/replay parity has not been established. Neither this evaluator
nor the mock state hash can independently reproduce an official leaderboard score.

Evaluate only authorized development data. Keep selection cohorts separate from
untouched evaluation. Do not infer semantic correctness from schema validity,
reviewer agreement or `ok: true` alone. Preserve actual call order, final state,
failures, coverage and timing alongside aggregate metrics.

## Historical tests and evidence

Tests under `archive/` are frozen evidence, not the default maintained suite.
Several require original sibling workspaces, protected validators/catalogs,
image metadata or historical receipts. Blanket archive discovery is not a
fresh-clone command. In particular, the archived private-workflow suite errors
when its excluded official validator and original workspace are unavailable.
The archived transport suite also retains an obsolete RC1 expectation that
Ampere always fails; current synthetic transport tests check RC2's actual backend
selection without claiming hardware qualification. These files remain unchanged.

The self-contained archived helpers can be run with
`python scripts/test_archived_helpers.py`; the runner explicitly selects only
tests that need no protected inputs. It does not fabricate the missing SDK.

Historical RTX 5090 receipts record bounded smoke and CLI/notebook parity.
Those receipts are not fresh inference, full Private coverage, or A30 validation.
The previous 153-test archival handover used the original local workspace and
must not be confused with the portable public suite. See
[validation record](VALIDATION.md), [final results](FINAL_RESULTS.md) and
[research history](EXPERIMENT_HISTORY.md) for evidence classes and limitations.
