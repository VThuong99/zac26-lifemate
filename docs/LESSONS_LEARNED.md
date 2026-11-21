# Lessons learned

These lessons summarize recorded outcomes. They are recommendations for a future
competition, not a plan to reopen this one.

1. **Measure complete requests using each policy's actual observations.**
   Correct next actions, valid JSON and `ok: true` tool responses can coexist with
   wrong entities, missing effects or unfinished goals. Preserve actual calls,
   observations, final hash and failure status. Distinguish a blocked proposal
   from an executed mutation. P48/P52 and the final research review contain
   counterexamples to proxy-only selection.

2. **Separate spoken truth, written proxies and scorer agreement.**
   P10/P16/P38 text comparisons exposed a large gap but did not measure pure
   acoustic recoverability. P25 greatly reduced word errors without comparable
   task improvement. Human clarity/transcript labels also had unresolved scope.
   Qualify intent, entities, conditions and complete effects independently;
   agreement between two related recognizers/reviewers is insufficient.

3. **Protect evaluation independence from the beginning.**
   The 95/200 development cohorts were repeatedly used for selection; parts
   overlapped training. Separation from one recent adapter does not erase older
   exposure. Bootstrap intervals do not repair adaptive selection or leakage.
   Use prospectively reserved source families, record every exposure, and keep
   matched continued-training controls when testing a new objective.

4. **Require retention and consequential-action checks alongside score.**
   Tiny fitted SFT/preference gains often failed on other branches or entities.
   `fai021` improved diagnostic F1 while introducing an unauthorized booking.
   Preserve rejection reasons, not only the highest score. A reviewer is another
   fallible policy; citations can be true but irrelevant, stale or from an
   assistant rather than a tool observation.

5. **Budget context for the entire runtime prompt.**
   RC2 configured 8,192 tokens even though the rules allowed up to 16,384.
   A reported 8,209-token prompt interrupted Private Test execution. Static input
   screening excludes some transcript/review/observation growth and cannot prove
   safety. A future system should measure the exact serving template plus all
   additions, reserve generation headroom and test the defined overflow policy
   before freezing. Enlarging context or truncating after submission changes the
   system; neither was applied to RC2.

6. **Design request-level failure isolation before release.**
   RC2 writes authentic failure receipts but its submitted batch loop aborts on
   an inference exception. One failed request can prevent later independent
   requests from running. A future batch contract should explicitly preserve
   completed rows, record failures, continue independent requests where allowed,
   and handle a dead worker without duplicate stateful attempts. Never fabricate
   a state hash or retry a request by constructing a second ToolEnv. The later
   continuation utility demonstrates a different batch contract, not equivalence
   to the submitted entrypoint.

7. **Treat serving conversion and hardware as behavioral changes until tested.**
   Tensor/layout checks, zero-overlay checks and syntax checks are useful but do
   not establish full action parity. Precision, tokenizer/template, CUDA kernels
   and adapter routing can change decisions. RTX 5090 evidence cannot qualify
   A30 execution. Test the exact target and cold/warm resource limits early.

8. **Preserve the runnable image as well as the recipe.**
   A Dockerfile and package versions do not reproduce an unavailable base,
   mutable apt repository, host-linked library or missing training input. Record
   archive checksums, OCI manifest/configuration/rootfs identities, source seals,
   SDK origin and CLI/notebook parity separately. An image-store ID may differ
   from the configuration digest. Test offline operation with the mounted SDK,
   including incidental hostname/DNS lookups and ownership of output mounts.

9. **Make provenance and permissions part of the deliverable.**
   Untracked code was essential to K and was not represented by the old Git HEAD.
   The P34 checkpoint is needed by a runtime CTC sidecar despite its filename.
   Keep exact source/configuration/dependency manifests and an asset restoration
   map. Preserve failed approaches and stale historical reports with dates rather
   than silently rewriting their conclusions. Local availability, upstream
   licensing and permission to share company/organizer derivatives are different
   facts; a private GitHub repository does not resolve all three.

Evidence: [experiment history](EXPERIMENT_HISTORY.md),
[final results and interruption](FINAL_RESULTS.md),
[training restoration](../archive/rc2/overlay/training_code/TRAINING_RESTORATION.md),
[identity correction](../archive/rc2/evidence/IDENTITY_CORRECTION.md), and
[original publication audit](../archive/rc2/overlay/docs/PUBLICATION_AUDIT.md).
