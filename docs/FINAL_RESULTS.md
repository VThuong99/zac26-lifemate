# Final results and frozen submission

**Final official Private Test score: 19.6, user-reported on November 21, 2026.**
The user identifies K48.46 RC2 as the submitted final solution. No portal receipt
or independently accessible Private Test score export was present in the
workspace. No score was recomputed during archival.

## Score provenance

| System / evaluation | Score | Evidence class |
|---|---:|---|
| P19 Public Test | 40.63 | Historical user report; no portal receipt inspected. |
| P34 Public Test | 44.69 | Historical user report; no portal receipt inspected. |
| Composed Q4 Public Test | 46.11 | Historical user report; no portal receipt inspected. |
| K Public Test | 48.46 | Historical user report; saved K output identity verified locally. |
| K48.46 RC2 Private Test | **19.6** | User report in the final archival request. |
| K local 95 / 200 cohorts | 64.72 / 70.30 | Approximate exposed-development reconstructions; not official scores. |
| P34 local 95 / 200 cohorts | 58.29 / 56.30 | Same historical reconstruction comparison; not independent generalization. |

The Public progression is recorded in the original
`experiments/continuous_improvement/research_review/COMPREHENSIVE_RESEARCH_REPORT.md`
and `experiments/final_autonomous_improvement/CHAMPIONS.json`, fingerprinted in
[RESEARCH_INDEX.csv](../archive/RESEARCH_INDEX.csv). None of the Public scores
qualifies as independently verified from a portal receipt. Configuration/output
mapping is based on saved records and the user's mapping. The name “K48.46” is a
release label, not a locally measured RC2 score. Public and Private scores cannot
be used to isolate a component's causal contribution.

## Frozen identity

Authoritative export metadata:
[RC2 RELEASE.json](../archive/rc2/artifacts/RELEASE.json).

| Item | Recorded value |
|---|---|
| Tag | `lifemate-k:k48.46-20261116-rc2` |
| Docker archive | `lifemate-k-k48.46-20261116-rc2.tar.gz` |
| Archive bytes | 16,805,691,094 |
| Archive SHA-256 | `e2aaa0a3c8f54e673f7700c443846a974be09257f3e28145ca9f0fb5076232f5` |
| Archive MD5 | `fecf2555ec4e1fdecc97ebca84e07fc7` |
| Recorded image-store ID / OCI manifest | `sha256:e212336277d5b37c5359599961c56b7f9331e4f63b3985902a2e7c588c114a8c` |
| Configuration digest | `sha256:00cf5905325e57fa68e7034d4e773bc81fcea8e347d41c3e3e100e47de486306` |
| Original source archive SHA-256 | `569b0fdc8ff8522cb0f81829a11616d00a14afe9740a00dee9677e7e56e5d586` |
| Final context manifest SHA-256 | `4e0787eaf9c3f2d72f7c3e89e7f83c91fb1ac605626f2be2918bcd3e8d9a7b48` |
| K Public JSONL SHA-256 | `cf3a5a654fdfb59f0e8ddb385319ed6c74b3cb8595c6072456d9f64e4e777898` |

The original image and source archives were rehashed during archival and matched
their recorded values. All RC2 files/links were inventoried in
[FROZEN_RC2_SHA256.json](../archive/FROZEN_RC2_SHA256.json). Originals remain at
`../lifemate-final-20261116-rc2/`. The checked-in source-only copy is a selected
subset, not the original complete build context or Docker archive.

## Saved validation evidence

November 16 RC2 receipts record a passed GPU preflight, exact **1/1 smoke**,
**10/10 CLI pilot** and **10/10 notebook** parity. Recorded maximum request times
were 2,582 / 2,593 / 2,574 ms respectively. These are bounded historical host
checks, not full Private Test coverage, a new benchmark or an A30 qualification.
The aggregate reports remain under [archived runs](../archive/rc2/runs/).

The earlier K Public output contains 634 ordered records, 1,544 calls, 625
`finished` and nine `max_steps`. Its local schema/event correspondence checks
passed. Warm RTX 5090 dispatch mean/p95/max were approximately 1.895 / 3.860 /
6.123 seconds, excluding initialization. Valid schema and receipt equality do
not prove correct intent or official replay equality.

Older `STATUS.json` fields such as `archive_created: false` and `submitted: false`
precede export/user-reported submission. They were preserved, not rewritten.
Use the later export receipt for archive identity and the explicit user report
for submission/score provenance. Rights and training-restoration limitations
were never resolved by a parity pass.

## Private Test interruption and continuation

The November 20 local investigation records **625 inputs**, an **8,192-token**
configured context and a **host-reported 8,209-token rejected prompt**. The next
request after the reported 323-row prefix was `private_0327`, index 323. Its static
screen estimated 7,444 base prompt tokens; that estimate excludes parts added by
actual transcription/continuation and is not the exact failed prompt.
The original host receipt/prefix audit remained unavailable in the development
container. See the preserved
[verification record](../archive/private_test/lifemate-private-rc2-investigation-20261120/LOCAL_VERIFICATION.json).

Source inspection establishes the failure mechanism: the submitted
`KRuntime.infer` raises on the recorded inference failure, and the enclosing
batch loop does not isolate that request. Successful earlier lines remain in
`.partial`; completion/rename is not reached. This is consistent with the host
report, but the complete original failure evidence was not available to verify
every detail. The 19.6 score cannot be quantitatively attributed to this failure
from the available evidence.

The separate
[continuation workflow](../archive/private_test/lifemate-private-rc2-host-20261120/README.md)
preserves the image, model, adapters, ASR, 8,192 context and 30-second deadline,
but **changes batch error handling**. It validates and reuses the 323 original
lines, uses the failed request's authentic receipt if valid, and initially leaves
301 untouched requests. It catches request failures and can process subsequent
independent requests without truncation, enlarged context, fabricated predictions
or retrying an attempted request with a new ToolEnv.

Those are documented workflow semantics, not proof that a completed continuation
artifact exists here. No final host continuation report was available. A schema
pass would establish output structure, not success on failed requests or official
eligibility. The workaround is a diagnostic continuation and must not be described
as identical to the submitted batch execution.

## Remaining limitations

Semantic errors include wrong entities, conditions, numbers, omitted goals and
unsupported consequential actions. Local scores and reviewer agreement did not
eliminate them. The configured context can overflow before the rule's 16K maximum;
the rule does not silently change the submitted 8K configuration. Full training
reproduction, authorized transfer locations, company/organizer redistribution
rights and actual A30 validation remain unresolved. See
[handover status](ARCHIVAL_HANDOVER.md).
