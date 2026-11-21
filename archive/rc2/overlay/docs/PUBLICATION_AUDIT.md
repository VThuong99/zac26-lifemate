# Local publication and transfer audit

Status: **no artifact is approved for external transfer or publication**. This is an engineering inventory, not a legal authorization. The user explicitly withheld automatic GitHub/GHCR publication, storage upload, registry login and competition submission; none was performed.

| Artifact group | Inventory / evidence | Rights finding | Treatment |
|---|---|---|---|
| Team inference source and policies | `manifests/source.json`, final `source-release.json`; exact K import dependency closure | Company/user ownership and pre-submission public-disclosure authority not provided | Local source candidate; no push |
| Qwen-derived GGUF and two adapters | Every size/hash in `models.json`; pinned source revision and historical recipes | Upstream Qwen model currently identifies Apache-2.0; that does not establish derivative/company/training-data transfer rights | Local only; no LFS/registry upload |
| P34 RNNT/CTC weights and vocabulary | Epoch2 and ONNX hashes preserved | Gipformer card declares MIT; historical audit lacks full publisher notice; organizational rights unresolved | Local only; full notice/approval required |
| PhoWhisper | Pinned revision, SHA-256 and copied model card | Card declares BSD-3-Clause; complete notices and organizational transfer review still required | Local only |
| llama.cpp / Icefall code | Pinned revisions and license notices | MIT / Apache-2.0 notices retained; company release review still pending | Include attribution in local candidate |
| CUDA and Python distributions | `native.json`, `python-files.json`, `python-distributions.json`, base-image manifest | Package metadata/notices retained; dependency-by-dependency redistribution review incomplete | Local build inputs; image transfer blocked |
| Training data, reviewed pairs, masks and training-only models | `training_code/required-private-assets.json` | No authorized immutable distribution URLs; competition/company restrictions unresolved | Excluded; reproduction incomplete |
| Reserved labels, unused holdouts, prior experiment results | Not in publication/source/image context | Must remain preserved and unused | Excluded; no new labels consumed |
| Historical Git repository | Existing dirty research repository left untouched; isolated source has no Git history | History could contain restricted work and is not approved | Never copy `.git`; fresh reviewed source history only after approval |
| Container archive | Final `ARTIFACTS.json`, manifest, layer and checksum verification | Inherits every contained asset's permissions | Kept locally; Docker-load/offline/A30 qualification unresolved |

Source and image inputs use explicit allowlists. The build context excludes evidence, cached results, mounted SDK/data/environment files, all `.git` directories, research archives, credentials and the failed `sm80` backend. The final source inventory is generated from actual files and checked for binary models, symlinks, private keys and common token patterns. Pattern scans cannot establish ownership or prove every possible secret is absent. Package files retain third-party fixtures and examples; permission review must inspect included licenses, not infer permission from import success.

The daemonless image path starts from verified public NVIDIA blobs and explicitly copies release inputs. It does not export the company workstation filesystem. Temporary resolver files, CPU information, audio smoke input, and any host-driver test files must be removed before layer creation; the final archive audit verifies their absence. No old image layer containing those temporary inputs is retained in the flattened image. Actual Docker image-layer inspection is pending a Docker-enabled host.

Current upstream Qwen licensing reference: [Qwen3.5-4B LICENSE](https://huggingface.co/Qwen/Qwen3.5-4B/blob/main/LICENSE). This mutable page is supporting context, not immutable permission evidence for the team's particular derived artifacts. Publication remains blocked until the user confirms artifact-level rights and the exact destinations.
