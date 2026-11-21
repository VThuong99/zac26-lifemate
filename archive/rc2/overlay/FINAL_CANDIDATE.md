# Final candidate rc2 — not yet host qualified

Original K48.46, weights, tokenizer, ASR, controller decisions, 30s watchdog and
state integrity checks are preserved. Two policy imports now use local pure
schema helpers, tested against the frozen helpers. No organizer SDK is packaged.
Mounted split ToolEnv selection and one-instance guard are unchanged.
The hostname DNS lookup is removed only from Icefall diagnostic metadata.
Capability 12.0 retains the original sm120 backend. Capability 8.0 selects the
existing dual-target native CUDA build; actual A30 execution is NOT VERIFIED.
Unsupported capabilities fail. The original notebook cells are unchanged.

training_code contains recovered source plus the 65-file restoration supplement.
Complete authorized training data/base restoration, immutable download URLs and
clean-machine reproduction remain missing. Company and organizer redistribution
permissions remain unresolved. This image must not be advertised as fully compliant.
Historical README/reports describe rc1; this addendum describes rc2 changes.
