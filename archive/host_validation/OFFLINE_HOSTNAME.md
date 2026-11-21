# Offline hostname dependency

The source identifies a concrete failure path during CTC-sidecar initialization:

1. `source/runtime/lifemate/experiments/continuous_improvement/ctc_entropy_corroboration_v1/runtime.py`, `Sidecars.__init__`, imports the retained Zipformer `train.py` and calls `module.get_params()`.
2. `source/runtime/third_party/icefall-p12-3f848bb6/egs/librispeech/ASR/zipformer/train.py`, `get_params()`, inserts `"env_info": get_env_info()` into the parameter dictionary.
3. `icefall/env.py`, `get_env_info()`, evaluates `socket.gethostbyname(socket.gethostname())` while building diagnostic metadata. No exception handler protects this lookup.

If the generated container hostname is absent from the hosts mapping and cannot be resolved in the offline network, Python raises `socket.gaierror`. That exception can abort ASR worker initialization before a ready receipt is sent. The reported `gaierror: [Errno -3] Temporary failure in name resolution` and successful `lifemate-offline → 127.0.0.1` mapping are consistent with this exact path. This is an incidental diagnostic lookup, not an ASR need for an external service.

The saved host directory contains only a llama-server log showing successful LLM startup and teardown. It does not contain a full ASR traceback or the later successful smoke result. Therefore this is a source-supported diagnosis with an isolated reproduction, not a claim to have inspected the complete failed host stack. Other startup networking, including the notebook's local kernel sockets, still needs the prescribed independent host test.

The original retained Icefall utility also contains `hostname -f` in its logging helper. The demonstrated fatal lookup is the eager `get_env_info` expression; replacing it alone requires an actual no-flags startup test before concluding that no hostname dependency remains.

`proposed-fix/icefall-offline-metadata.patch` replaces only the diagnostic `"IP address"` expression with `None`. It avoids both resolution failure and resolver delay without inventing a network address or monkey-patching Python's global socket functions. It retains the hostname and other environment metadata. `env_info` is logging metadata; no weights, decoding policy, model dimensions, tokenizer, tool policy or frozen K records change.

The patch has **not been applied** to any release source, runtime, model or image. `tests/test_hostname_fix.py` extracts the original function into an isolated namespace with lightweight stubs. A mocked failed resolver reproduces the original exception. The proposed function returns metadata without invoking that resolver. This does not load ASR or prove trajectory parity.

A future authorized candidate should be built in a separate source tree and receive a new image ID/tag, updated source manifest and provenance. Apply the same metadata change to the staged Icefall source that enters that candidate image; preserve the original archive and imported image. Independently test:

- The unchanged image as the control with the existing mapping.
- Candidate CLI smoke and ten-case pilot with `--network none`, omitting both `--hostname` and `--add-host`; inspect fresh ASR/LLM loading evidence.
- Candidate notebook smoke and pilot in a fresh kernel under the same no-flags conditions, so notebook connection setup is tested too.
- All ten trajectories, calls, hashes, statuses, SDK origins and timing before any full run.
- Explicit candidate full CLI and full notebook 634-case regression, including all nine original step-limit cases, against the original K reference and unchanged-image host results.

Do not promote the candidate or remove the current validation workaround until these tests pass. This task stops before candidate modification/build or host execution.
