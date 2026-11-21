# Experiment history

The final decision is to preserve K48.46 RC2 and stop. This is an evidence
summary, not a new evaluation. Original reports, journals, configurations,
checkpoints and failed runs remain in their original locations.

[RESEARCH_INDEX.csv](../archive/RESEARCH_INDEX.csv) fingerprints the historical
reports and catalogs. The original comprehensive review at
`experiments/continuous_improvement/research_review/COMPREHENSIVE_RESEARCH_REPORT.md`
reconciles 3,211 complete ledger events into a 1,585-row catalog, including aliases
and filesystem leads. That is **not** 1,585 independently completed experiments.
Later campaign records supplement this historical index.

## Main phases

| Phase | Hypothesis and measured evidence | Conclusion |
|---|---|---|
| P9 planner adaptation | On 295 development text requests, BF16 LoRA raised finished state-gated F1 from 19.77 to 65.83. | Strong local adaptation effect under that matched implementation; not live audio or official deadline performance. |
| P10–P16 audio integration | P10 reference-text versus real-ASR scores were 63.88 versus 27.22. P16 sentence-case ASR versus written proxy was 39.71 versus 60.79. | Speech/text representation mattered; written references were not verified spoken truth, so the gap is not pure recoverable ASR headroom. |
| P19 real-ASR adaptation and search | Retained decision training added gated authentic-ASR variants. Beam, prompt, longer-step, precision and wholesale PhoWhisper alternatives often regressed or failed safety gates. | Some adaptation became part of the final lineage; higher approximate F1 alone did not justify promotion. |
| P23–P26 controlled diagnostics | On 14 selected clear cases, mild audio processing changed none of 47 transcripts or 14 trajectories. Lexical repair reduced word errors from 95 to 20 but changed F1 only 33.929→35.714, versus 57.143 for full human text. | These narrow tests did not establish noise removal or lexical correction as sufficient. Robustness tests introduced new flips/consequential-write differences. |
| P34 ASR fine-tuning | Epoch-2 Gipformer selected by dev WER; paired ASR/decision evidence and export checks retained. Public progression P19 40.63→P34 44.69 is user-reported. | P34 became the final primary ASR; Public aggregates do not isolate causal contribution. |
| P38–P49 representations, precision and teachers | Controlled text-source substitution on exposed 95 changed 58.29→70.21. P47 BF16/Q4 comparison was 57.91/58.29 with uncertainty spanning no difference. P48 expression interface scored 50.00 versus 58.29, with invalid programs and consequential errors. | Text proxies, precision changes, an untrained executable interface and a larger teacher did not establish independent end-to-end improvement. |
| P31 trajectory RL | Authentic sampled paths showed reward variation; recomputed likelihood exceeded tolerance and differentiable replay exceeded memory. | Zero optimizer updates; no T1. This failed implementation gate is not evidence that all RL fails. |
| P48–P53 synthetic/augmented training | P51 paraphrase verification admitted semantic changes. P52 fresh candidate paths scored 59.36 versus P34 58.29 on exposed 95; interval −3.79 to +5.91, acceptance gate failed. | Generated supervision and successful simulator calls did not reliably preserve complete intent/effects. |
| Composed Q4 and K | Scoped temporal/reference policies, Q8 serving, acoustic corroboration and dynamic reviewers accumulated. Reported Public results: Q4 46.11, K 48.46. | K was frozen. No Public component ablation exists; local reconstructed 95/200 results are selection-exposed. |
| Subsequent SFT/preferences/critics | Some fitted or source-separated development corrections improved. Matched controls often tied; critics selected wrong alternatives, and retained paths regressed. | No independently confirmed objective-specific or broadly safe successor to K. Preserve rejected weights and cases. |
| Final autonomous / human-audio studies | `fai008` reserved synthetic success tied at 3/7; retention F1 fell 69.05→68.40. `fai021` diagnostic F1 rose 65.42→71.67 but introduced an unauthorized car booking. | Both failed their acceptance conditions; the higher diagnostic score did not override the safety rejection. |
| E13–E20 and independent-evidence closeout | E20 qualified no materially new candidate; its two SDK mechanism probes were not model evaluations. The later source review retained three narrow text contracts but zero admitted complete stateful training examples. | Scientific stop. No new optimization or experiment follows from this archive. |
| RC2 deployment and Private Test | Portable split transport, mounted SDK, identity/locking corrections and historical 10/10 CLI/notebook parity. Private Test continuation addressed batch interruption after reported context overflow. | Packaging checks established limited execution parity. Continuation differs from submitted batch semantics; final Private score is user-reported 19.6. |

## What the evidence supports

P9's matched text experiment supports an adaptation benefit in that setting.
P34, the retained policies and reviewers are part of the final successful
submission lineage; their individual contributions cannot be inferred by
subtracting user-reported Public aggregates. Some development changes produced
real improved tool effects, but many cohorts were repeatedly inspected, used for
selection, overlapped training, or reused previously audited paths.

The local reconstructed comparison is K 64.72/70.30 versus P34 58.29/56.30 on
95/200 requests; composed Q4 was 66.24/63.47. The cohort interaction and reuse
limitations matter. These are not contemporaneous independent four-arm trials,
do not reproduce full-cohort K timing and do not predict Private Test performance.

Failed tests constrain their actual recipe and cohort. They do not disprove all
denoising, precision changes, typed planning, RL, synthetic data or verification.
Likewise, a successful fitted correction is not a generalization result.

## Primary evidence map

Original-local milestone reports (not included in this publication snapshot):
`docs/milestones/p9_generative_lora.md`, `p10_vietnamese_asr.md`,
`p16_asr_decision_attribution.md`, `p17_evaluation_parity.md` and
`p19_autoresearch.md`. Their paths/hashes remain in the research index.

The following original-local records are indexed by path/hash and intentionally
remain outside new Git staging; their original contents may include restricted
examples or derived data:

- `docs/milestones/p23_asr_error_attribution.md` through `p26_decision_model_robustness.md`.
- `experiments/continuous_improvement/research_review/`: comprehensive report,
  `EXPERIMENT_CATALOG.csv`, result index, inventory audit and corrections.
- `experiments/research/experiments.jsonl` and
  `experiments/continuous_improvement/EXPERIMENTS.jsonl`: original event ledgers.
- `experiments/p31_trajectory_rl_v1/`, `p47_quantization_ablation/`,
  `p48_full_trajectory/`, `p49_local_teacher/`, `p52_external_tool_data/`.
- `experiments/final_autonomous_improvement/RESEARCH_MEMORY.md` and the
  `datasets/generalization_data_optimization_campaign_v1/` E13–E20/result trees.
- `submissions/SUBMISSION_REPORT.md` and `results/p34_public_run_v1/REPORT.md`.

The [source manifest](../archive/MANIFEST.json) identifies byte-exact retained
final implementations. [Final results](FINAL_RESULTS.md) records the evidence
boundary between historical local results, official user reports and diagnostics.
