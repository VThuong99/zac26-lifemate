# Training restoration supplement

The dual-GPU handoff adds an optional operational-path relocation. Six historical P34 scripts contain absolute workstation paths. Restore into a genuinely new workspace with the same sibling layout for `lifemate/`, `models/`, `third_party/` and `.venvs/`:

```bash
python3 restore_training_code.py --source /approved/source \
  --workspace-root /new/training-workspace \
  --output /new/training-workspace/lifemate
```

This changes only the known historical workspace prefix inside `.py`/`.sh` files, records original and relocated hashes, and leaves historical JSON provenance unchanged. It refuses the original workstation root and existing output directories. The six relocated scripts passed Python/shell syntax checks; no training/preparation module was imported or executed. Relocated path strings are not proof that serialized training inputs or every intermediate are portable.

An additional read-only audit verified15 known training base/checkpoint/metadata files locally: five pinned Qwen source files, the P9 merged model and four metadata files, three Gipformer base/tokenizer files, the P19 adapter and its gate report. Both pinned Icefall/llama.cpp checkouts match their expected revisions with clean tracked files. These assets are not copied into the handoff. The exact local status, required hashes and logical paths are inventoried in `TRAINING_ASSET_STATUS.json`. No listed checkpoint is physically missing locally; external restoration remains blocked by missing approved locations/permissions and incomplete environment/audio/preparation closure.

Historical P34 training requires a real clean Icefall Git checkout at the pinned revision, not merely a source tar, because it checks `git rev-parse` and tracked cleanliness. Adapter export also needs the pinned llama.cpp converter/`gguf-py` and its Python environment. Restore these dependencies to the documented sibling paths. No Git history or environment lockfile was fabricated to satisfy those checks.

This additive supplement repairs source-layout and direct-import omissions in the sealed source archive. It does not change that archive, the image, runtime policy, or weights. No training or data preparation was executed.

`restore_training_code.py` checks all 44 original training-source records, merges their 42 unique paths without conflicting overwrites, and adds 23 files. Twenty historical Python dependencies and the prompt come from the recorded P19 source snapshot; the P9 requirements file matches its historical config hash. The remaining terminal-preparation transform comes from the sealed K inference source. Its exact historical training version is not independently attested. Every origin and SHA-256 is in `training-supplement-manifest.json`.

The resulting 65-file layout passed syntax checks for all 50 Python files and a static audit found no unresolved direct local `src`, `scripts`, or `experiments` imports. This is a source restoration check, not proof that runtime imports, dynamic imports, historical environments, data pipelines, or training execute successfully.

```bash
# Extract the original source archive into a reviewed directory first.
python3 restore_training_code.py --source /approved/source --output /new/isolated-training
# The command refuses an existing output directory and copies no data or weights.
```

After authorized inputs and the archived environment have been restored, the historical module invocations are:

```bash
cd /new/isolated-training
PYTHONPATH="$PWD" python -m scripts.train_p9 --model "$PINNED_QWEN_BASE" --output "$NEW_P9_OUTPUT"
PYTHONPATH="$PWD" python -m scripts.train_p19_real_asr --model "$VERIFIED_P9_MERGED" --output "$NEW_P19_OUTPUT"
# Follow the archived P34, DPO and terminal recipes for their separate stages.
# The terminal --arm K command writes historical relative paths: use only this new layout.
```

Do not execute preparation modules as a discovery step: some read serialized data or write outputs at import time. No dependency installation or retraining was attempted during release completion.

| Category | Evidence and remaining work |
|---|---|
| Available historical implementation | Original 44 records verified; supplemental 23 files verified; 65-file reconstruction tested. Original recipes, revisions and parameter counts remain in `source/training_code/README.md`. |
| Local private inputs | All ten files in `source/training_code/required-private-assets.json` exist and match their recorded SHA-256 and byte counts. They are excluded from both archives and this supplement. Local presence does not establish transfer permission. |
| Additional gate metadata | `results/p19_real_asr_training_gate_v1/report.json`, 1,325 bytes, SHA-256 `c58e3080935f94e31629b7c62dc76d82a3f69e1d39cd2d51c8e59453ca19a9a1`, matches P19 config. It is not packaged. |
| Public pinned resources | Qwen, Gipformer, PhoWhisper and Icefall revision links are recorded in the original training README. Access and license review are prerequisites; links alone do not establish permission or reproduce team checkpoints. No network retrieval was needed for this repair. |
| Restoration still incomplete | Authorized underlying training audio, training-only base/checkpoint restoration, preparation intermediates, historical environment reconstruction, and a complete clean-machine pipeline remain unverified. The ten-file manifest is a known-input inventory, not a claim that it covers the entire pipeline. |
| Rights unresolved | Company source/checkpoints, organizer data, derived training artifacts, runtime dependencies, and final image require their respective owners' authorization and applicable notices. No approved immutable transfer locations were supplied. |
| Excluded from distribution | Credentials, hidden environment state, reserved labels, unused holdouts and research history are outside the handoff. No assertion is made that every unresolved asset is legally non-distributable; its status is unknown. |

Full training reproducibility and external transfer remain **BLOCKED**. An authorized owner must resolve the asset/rights inventory and supply approved restoration locations before a clean-machine reproduction can be attempted. No missing provenance has been invented.
