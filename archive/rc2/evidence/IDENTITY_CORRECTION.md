# rc2 existing-image verification correction

Run on the host:

```bash
bash /home/duongthuong/GPU_benchmark_host/lifemate-final-20261116-rc2/host.sh resume 0
```

This executes verify → GPU preflight → one-request smoke → ten-request CLI parity → ten-request notebook parity → archive packaging, stopping on any failure. It never invokes the build branch. Each stage is also available individually as `host.sh verify|gpu|smoke|pilot|notebook|package 0`. After a stage failure, retry that stage and subsequent stages individually. Existing archives and partial exports are preserved. Upload and submission are manual.

The complete raw configuration comparison from `runs/20261116T135201Z-build-RNHQa5/image-inspect.json`, after the two intentionally changed release labels, differs only in ArgsEscaped. Expected: absent (default false). Actual: true. JSON key ordering has no effect. `identity-correction.json` contains complete expected/actual normalized configurations and the exact difference.

The [OCI image configuration specification](https://github.com/opencontainers/image-spec/blob/main/config.md#properties) states: “It is used by Docker for Windows images”. The field controls Windows pre-escaped command lines. The Linux/amd64 comparison therefore normalizes this boolean only after the original strict configuration parser validates its type. Windows/unknown OS comparisons retain the field. Unknown configuration fields and every other configuration value remain significant. This changes comparison semantics only; no image configuration bytes are rewritten.

Identities retained separately:

- Docker store image ID and OCI manifest digest: `sha256:e212336277d5b37c5359599961c56b7f9331e4f63b3985902a2e7c588c114a8c`.
- Image configuration digest from the completed build export: `sha256:00cf5905325e57fa68e7034d4e773bc81fcea8e347d41c3e3e100e47de486306`.
- Flattened filesystem DiffID: `sha256:8cb79c8d27ce91d0df79e76f176334c962d30a8ca10d57210681ef7f00900e32`.
- Empty tail DiffID: `sha256:5f70bf18a086007016e948b04aed3b82103a36bea41755b6cddfaf10ace3c6ef`, independently computed as SHA-256 of 1024 zero bytes (the empty tar).

An additional pre-existing assumption required exactly one layer and would have failed immediately after fixing ArgsEscaped. The flattened build has two layers. Validation now permits only one flattened layer with an optional second layer having that exact empty-tar DiffID. Resume pins the complete original ordered RootFS list; packaging recomputes both DiffIDs from actual archive layer bytes. Arbitrary extra or changed layers fail.

The original context manifest and three original host-tool files are preserved in `identity-before/`. Original context SHA-256 is `e6f9f2872fb0d4507f165d51483c4909cd2eb5184ea2212298c59a7bcc9e9b25`. Resume verifies this manifest, all unchanged image/harness inputs, all saved build evidence hashes, authenticated rc1 identity before/after the build, 42,199 passing release-file checks, and the exported manifest/configuration digests. Fresh host inspection must match the original built image, including raw configuration. A new BUILD.json records this provenance and the current host-tool context without pretending that modified host tools were image build inputs.

Packaging additionally verifies the exact exported configuration digest and OCI manifest digest against the build. Semantically equivalent but byte-different configuration fails that integrity check. The output archive receives SHA-256, MD5 and a RELEASE.json with validation receipts. No checksums or archive completion are claimed before host export succeeds.

Affected active files: `tools/candidate.py`, `tools/package.py`, `host.sh`, `tests/test_identity_resume.py`, `CONTEXT_SHA256.json`, `STATUS.json`, evidence files and `../lifemate-host-validation/FINAL_SUBMISSION_ACTIONS.md`. The original host validator's 33 bundled files, rc1, rc2 Dockerfile/overlay/harness, model weights and frozen K are unchanged. No Docker build, Docker execution or GPU experiment was performed in the development container.

Validation: 31 candidate CPU tests and 43 original validator CPU tests passed. Syntax checks passed for 235 Python files and eight shell scripts. Tests cover Linux boolean representations, unchanged Windows semantics, invalid types/unknown fields, every other configuration field, runtime/platform/layer changes, evidence tampering, idempotent verification, changed raw image metadata, exact archive digests, and fail-fast resume order. Existing schema/SDK/behavior-integrity tests also pass. Logs: `identity-correction-cpu-tests.log`, `identity-correction-original-validator-tests.log`, `identity-correction-syntax.json`.

The user reports rc2 offline RTX 5090 request public_0002 finished in 2,808 ms with sm120, network none, no hostname mapping and Docker exit 0. Corrected host-stage parity and export remain pending. Actual A30 execution, complete training reproduction, full rc2 634-case parity and redistribution authorization remain unresolved. No official compliance claim follows from CPU tests or this metadata correction.
