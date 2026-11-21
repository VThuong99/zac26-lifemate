# Configuration and provenance

- [rc2-reference.toml](rc2-reference.toml) records the verified RC2 settings for
  readers. It is descriptive, not consumed by the frozen entrypoint. Changing it
  cannot change Docker inference.
- [source_layout.json](source_layout.json) maps the 15 portable modules to their
  frozen sources and defines the sole allowed import relocation. The verifier
  checks byte equality after that transformation.
- The authoritative historical [model manifest](../archive/rc2/overlay/manifests/models.json)
  and [Python environment inventory](../archive/rc2/overlay/requirements.txt)
  remain in the archive. That inventory describes restored package bytes; it is
  not a tested fresh-install lockfile.

The mock demo has no credentials, data paths or network endpoints. Its only
runtime option is `--max-steps`. For authorized real execution, follow the
[inference guide](../docs/INFERENCE.md); do not point tests at restricted datasets.
