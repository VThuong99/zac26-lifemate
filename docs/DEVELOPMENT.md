# Development

The maintained Python package exposes 15 modules copied from the published RC2
source. Only their `from src.…` imports and module filenames were adapted.
[source_layout.json](../configs/source_layout.json) records each origin and hash;
`python scripts/verify_source_layout.py` checks exact transformed bytes. The demo
is new teaching code. The frozen Docker still imports its original modules.

## CPU setup

Use Python 3.11 or 3.12 on Linux. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
lifemate-demo
python -m unittest discover -s tests -v
python scripts/test_archived_helpers.py
python -m ruff check src tests scripts examples
python scripts/verify_source_layout.py
python scripts/verify_archive.py
python scripts/check_repository.py
```

The package has no third-party runtime dependencies. `dev` adds pinned Ruff.
Network access is needed for initial packaging/linter installation unless those
wheels are cached. Afterwards the tests and demo use local synthetic inputs.
For the core tests/demo without installation:

```bash
PYTHONPATH=src python3 -B -m unittest discover -s tests -v
PYTHONPATH=src python3 -B -m lifemate.demo
```

The CLI's `--max-steps` includes the finish decision. With `--max-steps 1` the
demo reports `max_steps` after its read. This makes budget behavior observable.
The mock hash has no equivalence to an official SDK hash.

## Extension points

`Agent` accepts a planner with `next_action(text, context, history, timeout=…)` and
an existing environment with `validate(name, arguments)` / `call(name, arguments)`.
It owns neither environment construction nor reset. A planner returned after the
deadline cannot initiate another tool effect. The base agent's deadline checks
are cooperative; RC2 adds a hard deadline in a separate parent process.

`LLMPlanner` builds messages, parses a single JSON decision and accepts an injected
client. `LLMClient` implements the real llama.cpp HTTP interface with timing and
error propagation. Native-tool support exists in the base code, but the submitted
RC2 path uses strict custom JSON. Base-client defaults are not a complete RC2
server configuration; use the [runtime source map](SOURCE_MAP.md).

`GipformerASR` and `PhoWhisperASR` defer heavy imports until construction. Importing
their modules is CPU-safe. Constructing them requires the specific libraries,
checkpoints and environment described in [inference](INFERENCE.md); `pip install
-e .` does not provision ASR or CUDA. Full K additionally uses acoustic sidecars,
composition policies and adapter routing outside this package.

`schema_validation` is a local proposal check, not a replacement for ToolEnv.
It preserves historical permissive format handling; do not advertise it as a
complete JSON Schema validator. The SDK remains authoritative at dispatch.

## Making changes

Add synthetic behavioral tests when changing execution, matching, parsing or
input boundaries. Never use organizer excerpts as test fixtures. Keep the RC2
archive immutable. For intentional future core behavior changes, explicitly
version the derivation contract and add a reviewed patch/equivalence policy;
do not simply update hashes to make a failing preservation test pass.

`scripts/check_repository.py` scans the exact tracked and nonignored file set,
parses Python/JSON/TOML, checks shell syntax and maintained Markdown file links,
and rejects selected payload extensions, binaries, oversized files and common
credential patterns. It is a bounded check, not proof of ownership or a complete
secret detector. Historical archive Markdown is excluded from link checking
because it records intentionally absent private assets.

CI runs the same checks on Python 3.11 and 3.12, then builds a wheel and executes
its demo from `/tmp` in another environment. The wheel contains only `lifemate`;
archive inspection/export utilities require a source checkout. There is no GPU
job, model download, training run or official SDK evaluation in CI.
