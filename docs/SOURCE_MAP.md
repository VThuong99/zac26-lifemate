# Implementation map

There are two deliberate surfaces: an installable development core and the exact
submitted RC2 source. Moving the full RC2 tree would break historical path-based
imports, split bridging and release manifests. The small core is copied with
import-only adaptations; the remaining runtime and training code stays in place.
This avoids pretending that a newly packaged module is the submitted binary.

## Core modules

| Purpose | Developer-facing implementation | Relationship to RC2 |
|---|---|---|
| Sequential observations and deadlines | [agent.py](../src/lifemate/agent.py) | Base class; K overrides `run` |
| Validate, then execute on caller-owned environment | [controller.py](../src/lifemate/controller.py) | Actual controller contract |
| Strict single-decision JSON parser | [decision_parser.py](../src/lifemate/decision_parser.py) | Shared decision parsing |
| llama.cpp HTTP transport and metrics | [llm_client.py](../src/lifemate/llm_client.py) | Base transport; K adds adapter/cache controls |
| Context, tools and observations to messages | [llm_planner.py](../src/lifemate/llm_planner.py) | Shared planner implementation |
| Installed-tool filtering and schema formatting | [tool_catalog.py](../src/lifemate/tool_catalog.py), [tool_schema_formatter.py](../src/lifemate/tool_schema_formatter.py) | Shared tools layer |
| Gipformer ONNX recognition and audio-to-agent orchestration | [asr.py](../src/lifemate/asr.py) | Original `p10_audio.py`; K injects P34 and its composed agent |
| Pinned PhoWhisper recognizer | [phowhisper.py](../src/lifemate/phowhisper.py) | Original `p11_phowhisper.py`; used by acoustic sidecars |
| Token-preserving transcript formatting | [text_normalization.py](../src/lifemate/text_normalization.py) | Original `p14_formatting.py` |
| Optional progress ledger | [planning_policy.py](../src/lifemate/planning_policy.py) | Base code supports this policy; presence does not imply K selected it |
| Proposal schema checks | [schema_validation.py](../src/lifemate/schema_validation.py) | Exact `k_schema_helpers.py`; no SDK state access |
| Local scoring and ASR diagnostics | [evaluation.py](../src/lifemate/evaluation.py), [tool_call_matcher.py](../src/lifemate/tool_call_matcher.py), [asr_metrics.py](../src/lifemate/asr_metrics.py) | Evaluation utilities, not inference decisions |

Every copied module has an exact path/hash in
[source_layout.json](../configs/source_layout.json). The frozen baseline is public
commit `5799264cc7fa4594b890e81600a959c9fbaf2be5`.

## Complete submitted path

Read these files in order:

1. [predict.sh](../archive/rc2/overlay/predict.sh) →
   [predict.py](../archive/rc2/overlay/predict.py): `KRuntime` chooses a GPU backend,
   launches the local server/worker, selects arm C, bridges the mounted split and
   enforces one ToolEnv construction plus the hard deadline.
2. [worker.py](../archive/rc2/overlay/runtime/lifemate/experiments/continuous_improvement/conditional_terminal_pref_flight_e2e_v1/worker.py):
   installs ASR routing, prompt composition, reviewer selection and
   `FinishSourceOrderAgent`. This imported worker function is active; the research
   `main()` in the same file is not the submitted entrypoint.
3. [overlay_server](../archive/rc2/overlay/runtime/lifemate/experiments/continuous_improvement/scoped_adapter_read_e2e_v1/run.py):
   8K llama.cpp launch, Q8 model and both adapters initially at zero scale.
   The active worker enables adapter 0 or 1 per review request.
4. [P43 bridge](../archive/rc2/overlay/runtime/lifemate/experiments/p43_safe_temporal_itn/run_e2e.py)
   → [P32 worker](../archive/rc2/overlay/runtime/lifemate/experiments/p32_oracle_text_v1/run.py):
   reused transport/orchestration. P43 replaces both recognizer branches with the
   live P34 recognizer, including the historically named `ReferenceASR` branch.
   RC2 supplies no reference map. The P32 oracle-text experiment `main()` is not run.
5. [SDK loader](../archive/rc2/overlay/runtime/lifemate/results/p19_submission_staging_v1/scripts/run_p10_audio.py):
   `tool_env_for_split` loads the mounted split's `zaic_tools`.
   [run_trajectory](../archive/rc2/overlay/runtime/lifemate/results/p19_submission_staging_v1/src/p10_audio.py)
   constructs the environment and collects its actual calls/hash.

### ASR corroboration and policies

| Component | Active source |
|---|---|
| Primary/sidecar routing | [ParentCompatibleRouter](../archive/rc2/overlay/runtime/lifemate/experiments/continuous_improvement/shared_asr_parent_router_v1/router.py) and [Router](../archive/rc2/overlay/runtime/lifemate/experiments/continuous_improvement/max_entropy_asr_e2e_v1/runtime.py) |
| Confidence, CTC and PhoWhisper loading | [Sidecars](../archive/rc2/overlay/runtime/lifemate/experiments/continuous_improvement/ctc_entropy_corroboration_v1/runtime.py) |
| Scoped digit evidence | [independent recognizer collection](../archive/rc2/overlay/runtime/lifemate/experiments/continuous_improvement/corroborated_digit_evidence_q8_v1/runtime.py), [shared CTC](../archive/rc2/overlay/runtime/lifemate/experiments/continuous_improvement/shared_asr_digit_composition_v1/shared_ctc.py) |
| Composed agent and reviewer gates | [FinishSourceOrderAgent](../archive/rc2/overlay/runtime/lifemate/experiments/continuous_improvement/finish_consistent_review_e2e_v1/agent.py), [terminal selection](../archive/rc2/overlay/runtime/lifemate/experiments/continuous_improvement/finish_consistent_review_e2e_v1/policy.py) |
| Temporal and observation composition | [temporal_chat_wallet](../archive/rc2/overlay/runtime/lifemate/experiments/continuous_improvement/temporal_chat_wallet_v1/compose.py), [weekday anchors](../archive/rc2/overlay/runtime/lifemate/experiments/continuous_improvement/weekday_temporal_scope_v3/anchor.py) |

The composed agent imports further domain guards and reference policies. Follow
its imports for that closure. Not every sibling experiment is active. In
particular, RC2 rejects `LIFEMATE_PREFLIGHT_FILE`; the research preflight safety
interceptor cannot be claimed as submitted behavior. Training/teacher/RL studies
and post-submission continuation tools are separate from the inference path.

## Training, deployment and diagnostics

- [Training map](../training/README.md): P34 ASR, P9/P19 SFT, DPO write reviewer,
  terminal preference training and conversion.
- [Dockerfile](../archive/rc2/Dockerfile), [preflight](../archive/rc2/container/preflight.py),
  [notebook](../archive/rc2/overlay/predict_notebook.ipynb): frozen deployment.
- [Runtime reference](../configs/rc2-reference.toml): human-readable settings;
  the frozen runtime does not load this new TOML file.
- [Host validation](../archive/host_validation/README.md) and
  [Private continuation](../archive/private_test/lifemate-private-rc2-host-20261120/README.md):
  operational/diagnostic utilities with distinct execution semantics.
- [Experiment history](EXPERIMENT_HISTORY.md): attempted, retained and rejected
  approaches; historical metrics are not fresh benchmarks.
