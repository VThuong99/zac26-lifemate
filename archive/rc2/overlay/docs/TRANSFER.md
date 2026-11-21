# Authorized source and container transfer

**No destination or artifact has been approved for publication. No registry login, push, upload or submission has been executed.** The company's GitHub account does not establish ownership or redistribution rights. The source, trained checkpoints, Python/CUDA redistribution notices, competition training data, and container must each be approved. Prefer an authorized private repository and private GHCR package. If only public repositories are available, stop at local preparation until explicit publication approval.

Proposed immutable local tag: `lifemate-k:k48.46-20261115-rc1`. Intended repository: an approved `lifemate-k-release` repository under the owner the user selects. Intended GHCR repository: `ghcr.io/<approved-owner>/lifemate-k`. These are proposals, not claims that a destination exists or was approved. Registry digest remains absent until an actual authorized push and registry inspection.

The Git repository must contain only `source/` contents. Do not import the research repository or its history. No Git history was created for this candidate. `manifests/source-release.json` is the reviewed file inventory; `.gitignore` is only a secondary safeguard. Recompute the manifest after any change. The independent siblings `model_artifacts/`, `native/`, and `dependencies/` are local build inputs, not normal Git objects. The archive under `artifacts/` is a container artifact, not a source file.

After the final report's blockers are resolved and **explicit user approval** identifies the authorized destinations/artifacts, these commands may be reviewed and run manually:

```bash
# Select exact approved values. Do not put credentials in commands or shell history.
export APPROVED_SOURCE_URL='https://github.com/<approved-owner>/lifemate-k-release.git'
export APPROVED_GHCR_REPOSITORY='ghcr.io/<approved-owner>/lifemate-k'
export RELEASE_TAG='k48.46-20261115-rc1'
export LOCAL_IMAGE='lifemate-k:k48.46-20261115-rc1'

# Authentication is manual and was not performed by the release agent.
gh auth login --hostname github.com --git-protocol https --web
gh auth token | docker login ghcr.io --username YOUR_APPROVED_GITHUB_USERNAME --password-stdin

# In the isolated source directory, initialize a fresh history only after approval.
git init -b main
python3 - <<'PY'
import json, subprocess
from pathlib import Path
items = json.loads(Path('manifests/source-release.json').read_text())
paths = [x['path'] for x in items] + ['manifests/source-release.json']
subprocess.run(['git','add','--',*paths],check=True)
PY
git diff --cached --stat
git diff --cached --check
# Review every staged file and scan the staged content; do not use git add .
git commit -m 'Prepare frozen LifeMate K release candidate'
git remote add origin "$APPROVED_SOURCE_URL"
git push -u origin main

# Only after Docker load/build and validation have passed on an authorized host:
docker tag "$LOCAL_IMAGE" "$APPROVED_GHCR_REPOSITORY:$RELEASE_TAG"
docker push "$APPROVED_GHCR_REPOSITORY:$RELEASE_TAG"
docker image inspect "$APPROVED_GHCR_REPOSITORY:$RELEASE_TAG" --format '{{json .RepoDigests}}'
# Save the actual returned sha256 registry digest, plus image ID and source manifest.
```

The exact source stage is produced before approval; the commands above do not grant approval. Remove documentation placeholders and set the approved owner/account before execution. `gh auth token` is piped directly to Docker, not echoed or logged; disable shell tracing. Package visibility must be reviewed separately from repository visibility.

On the personal computer, an NVIDIA GPU is unnecessary for pulling, inspecting, saving and hashing a Linux AMD64 image. On ARM computers explicitly select `linux/amd64` during pull; do not rebuild or change native kernels. After any required manual private-registry login:

```bash
: "${APPROVED_GHCR_REPOSITORY:?Set the approved ghcr.io owner/image}"
: "${APPROVED_REGISTRY_DIGEST:?Set the recorded sha256:... registry manifest digest}"
docker pull --platform linux/amd64 "$APPROVED_GHCR_REPOSITORY@$APPROVED_REGISTRY_DIGEST"
docker image inspect "$APPROVED_GHCR_REPOSITORY@$APPROVED_REGISTRY_DIGEST"
docker tag "$APPROVED_GHCR_REPOSITORY@$APPROVED_REGISTRY_DIGEST" lifemate-k:k48.46-20261115-rc1
set -o pipefail
docker save lifemate-k:k48.46-20261115-rc1 | gzip -n > lifemate-k-final.tar.gz
md5sum lifemate-k-final.tar.gz > lifemate-k-final.tar.gz.md5
sha256sum lifemate-k-final.tar.gz > lifemate-k-final.tar.gz.sha256
md5sum -c lifemate-k-final.tar.gz.md5
sha256sum -c lifemate-k-final.tar.gz.sha256
docker load -i lifemate-k-final.tar.gz
docker image inspect lifemate-k:k48.46-20261115-rc1
```

Registry manifest digest, local image/config ID, uncompressed layer digest and compressed archive checksums are distinct identities. Do not compare MD5/SHA-256 of a newly generated gzip archive with a different export without verifying the bytes. `gzip -n` removes gzip timestamp/name variation; it does not guarantee independently generated `docker save` tar streams match.

If the personal computer lacks Docker, transfer the already exported and approved archive through an organizationally approved storage method, verify its published checksums, and submit that unchanged file. A separate Docker-enabled host must still perform the required `docker load` and inference validation. Do not evade company transfer restrictions, place multi-gigabyte archives in ordinary Git history, or assume Git LFS grants weight redistribution rights.

The final manual competition step, only after rights and validation are complete, follows the supplied guide pp18–19: upload the approved `.tar.gz` to Google Drive, allow “Anyone with the link,” calculate/provide MD5, and enter the download link and checksum in the official solution form. SHA-256 is an additional integrity check. The supplied rule says November 16, 2026, 23:59 GMT+7, at most two solution submissions and only the last evaluated. No upload or form submission is automated here.
