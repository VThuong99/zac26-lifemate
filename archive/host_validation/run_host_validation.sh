#!/usr/bin/env bash
# Host-only; never load, rebuild, retag, commit, or delete the sealed image.
set -euo pipefail
usage() {
  cat <<'EOF'
Usage: run_host_validation.sh smoke|pilot|full [--workflow cli|notebook] [--gpu INDEX_OR_UUID]
Runs only on /home/duongthuong/GPU_benchmark_host; explicit full mode never follows pilot automatically.
Requires host bash, python3, Docker permission, nvidia-smi, flock, timeout, tee.
EOF
}
fail() { echo "ERROR: $*" >&2; exit 2; }
[[ ${1:-} == --help || ${1:-} == -h ]] && { usage; exit 0; }
[[ $# -ge 1 ]] || { usage; exit 2; }
MODE=$1; shift
WORKFLOW=cli; GPU=0
case "$MODE" in smoke) COUNT=1; DEADLINE=600;; pilot) COUNT=10; DEADLINE=1200;; full) COUNT=634; DEADLINE=7200;; *) usage; exit 2;; esac
while [[ $# -gt 0 ]]; do
  case "$1" in
    --workflow) [[ $# -ge 2 ]] || fail 'Missing workflow'; WORKFLOW=$2; shift 2;;
    --gpu) [[ $# -ge 2 ]] || fail 'Missing GPU'; GPU=$2; shift 2;;
    *) fail "Unknown option: $1";;
  esac
done
[[ "$WORKFLOW" == cli || "$WORKFLOW" == notebook ]] || fail 'Workflow must be cli or notebook'
[[ "$GPU" =~ ^[0-9]+$ || "$GPU" =~ ^GPU-[a-fA-F0-9-]+$ ]] || fail 'Select one GPU index or UUID'
# Guard before even contacting Docker. No override for use inside the dev container.
[[ ! -e /.dockerenv && ! -e /run/.containerenv ]] || fail 'Execute manually on the host, not in a container'
if command -v systemd-detect-virt >/dev/null && systemd-detect-virt --container --quiet; then
  fail 'Container execution is forbidden'
fi
[[ -z ${container:-} ]] || fail 'Container execution is forbidden'
[[ $(id -u) -ne 0 ]] || fail 'Run as the host user with Docker access, not sudo/root (outputs must remain user-owned)'
HOST_ROOT=/home/duongthuong/GPU_benchmark_host
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
[[ "$HERE" == "$HOST_ROOT/lifemate-host-validation" ]] || fail "Expected host path $HOST_ROOT/lifemate-host-validation"
SPLIT="$HOST_ROOT/lifemate/public_test"
IMAGE_TAG=lifemate-k:k48.46-20261115-rc1
RELEASE_MANIFEST="$HOST_ROOT/lifemate-release-k-20261115/artifacts/ARTIFACTS.json"
for tool in docker nvidia-smi python3 flock timeout tee mktemp; do command -v "$tool" >/dev/null || fail "Required host command missing: $tool"; done
# Refuse remote daemon contexts: all bind paths are defined for this local host.
ENDPOINT=${DOCKER_HOST:-$(docker context inspect --format '{{.Endpoints.docker.Host}}')}
[[ "$ENDPOINT" == unix://* ]] || fail 'A local Unix Docker endpoint is required; do not use a remote context'
[[ -d "$SPLIT" ]] || fail "Input split absent: $SPLIT"
mkdir -p "$HERE/runs"
RUN=$(mktemp -d "$HERE/runs/$(date -u +%Y%m%dT%H%M%SZ)-${WORKFLOW}-${MODE}-XXXXXX")
umask 0022
printf '%s\n' "$RUN" > "$RUN/result-location.txt"
echo "Evidence directory: $RUN"
CID=''; MONITOR=''; CLEANED=0
cleanup() {
  [[ "$CLEANED" == 0 ]] || return 0
  CLEANED=1
  (
    set +e
    if [[ -n "$MONITOR" ]]; then kill "$MONITOR" 2>/dev/null; wait "$MONITOR" 2>/dev/null; fi
    if [[ -n "$CID" ]]; then
      # CID is exclusively the exact ID returned by this invocation's create command.
      if [[ $(docker inspect --format '{{.State.Running}}' "$CID" 2>/dev/null) == true ]]; then
        timeout 35s docker stop --time 20 "$CID" > "$RUN/owned-stop.log" 2>&1
      fi
      if [[ $(docker inspect --format '{{.State.Running}}' "$CID" 2>/dev/null) == true ]]; then
        timeout 20s docker kill "$CID" > "$RUN/owned-kill.log" 2>&1
      fi
      docker logs "$CID" > "$RUN/container-recovered.log" 2>&1
      docker inspect "$CID" > "$RUN/container-final.json" 2> "$RUN/final-inspect.stderr"
      docker rm "$CID" > "$RUN/owned-remove.log" 2>&1
      REMOVE_RC=$?
      printf '{"owned_container":"%s","remove_exit_code":%s}\n' "$CID" "$REMOVE_RC" > "$RUN/cleanup.json"
    fi
    nvidia-smi -i "$GPU" --query-gpu=uuid,name,memory.used,memory.free,utilization.gpu --format=csv > "$RUN/gpu-after.csv" 2>&1
  )
  return 0
}
trap 'rc=$?; cleanup; exit "$rc"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# User-readable logs retain failed preflight evidence as well as successful runs.
docker version > "$RUN/docker-version.txt" 2>&1 || fail 'Docker client/daemon unavailable; see docker-version.txt'
docker image inspect "$IMAGE_TAG" > "$RUN/image-inspect.json" 2> "$RUN/image-inspect.stderr" || fail 'The imported release tag is missing'
echo 'Verifying the sealed 17 GB archive and loaded image identity; this may take several minutes.'
if ! python3 "$HERE/validation.py" image-check "$RUN/image-inspect.json" \
  --release-manifest "$RELEASE_MANIFEST" --output "$RUN/image-identity.json" \
  > "$RUN/verified-image-reference.txt" 2> "$RUN/image-identity.log"; then
  cat "$RUN/image-identity.log" >&2
  fail 'Image provenance/configuration verification failed; see expected/actual details above'
fi
cat "$RUN/image-identity.log"
IFS= read -r IMAGE < "$RUN/verified-image-reference.txt"
[[ "$IMAGE" =~ ^sha256:[a-f0-9]{64}$ ]] || fail 'Invalid verified Docker execution reference' 
python3 "$HERE/validation.py" prepare --split "$SPLIT" --out "$RUN" --mode "$MODE" --workflow "$WORKFLOW"
nvidia-smi -i "$GPU" --query-gpu=uuid,name,driver_version,memory.used,memory.free,utilization.gpu --format=csv,noheader,nounits > "$RUN/gpu-before.csv"
GPU_UUID=$(python3 - "$RUN/gpu-before.csv" <<'PY'
import csv,sys
rows=list(csv.reader(open(sys.argv[1])))
if len(rows)!=1: raise SystemExit('Exactly one GPU must be selected')
uuid,name,driver,used,free,util=[x.strip() for x in rows[0]]
if int(used)>1024 or int(free)<12000 or int(util)>5:
    raise SystemExit('GPU is busy or lacks 12,000 MiB headroom. Wait for the existing workload; do not stop it.')
print(uuid)
PY
)
# Advisory lock coordinates only these validators; occupancy checks also catch other work.
exec 9> "$HERE/.validation-${GPU_UUID}.lock"
flock -n 9 || fail 'Another validation owns this GPU lock'
nvidia-smi -i "$GPU_UUID" --query-compute-apps=pid,process_name,used_gpu_memory --format=csv,noheader > "$RUN/gpu-processes-before.csv"
[[ ! -s "$RUN/gpu-processes-before.csv" ]] || fail 'Existing compute processes are present; wait for their owner'
# Immutable snapshot of only container helpers. No reference records are mounted.
mkdir "$RUN/harness"
for helper in entry.sh preflight.py run_notebook.py sitecustomize.py; do cp -- "$HERE/container/$helper" "$RUN/harness/"; done
python3 - "$RUN/harness" <<'PY'
from pathlib import Path
import hashlib,json,sys
p=Path(sys.argv[1]); files={x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in p.iterdir() if x.is_file()}
with (p.parent/'harness-sha256.json').open('x') as f: json.dump(files,f,indent=2)
PY
NAME="lifemate-k-${WORKFLOW}-${MODE}-$(basename "$RUN")"
CREATE=(docker create --name "$NAME" --label "lifemate.host-validation=$NAME"
  --network none --hostname lifemate-offline --add-host lifemate-offline:127.0.0.1
  --gpus "device=$GPU_UUID" --cpus 16 --memory 48g --memory-swap 48g --shm-size 2g --pids-limit 1024
  --user "$(id -u):$(id -g)" --cap-drop ALL --security-opt no-new-privileges
  --mount "type=bind,src=$SPLIT,dst=/data/public_test,readonly"
  --mount "type=bind,src=$RUN,dst=/result"
  --mount "type=bind,src=$RUN/harness,dst=/validation,readonly"
  --env HOME=/result/home --env USER=lifemate-validation --env LOGNAME=lifemate-validation --env XDG_CACHE_HOME=/result/cache --env JUPYTER_RUNTIME_DIR=/result/jupyter-runtime
  --env PYTHONPATH=/validation:/opt/k-python/main:/opt/k-python/sherpa:/opt/k-python/jupyter
  --env LIFEMATE_DATA_ROOT=/data --env LIFEMATE_SPLIT=public_test
  --env LIFEMATE_NOTEBOOK_OUTPUT=/result/jupyter_submission.jsonl
  "$IMAGE" /bin/bash /validation/entry.sh "$WORKFLOW" "$MODE" "$COUNT")
printf '%q ' "${CREATE[@]}" > "$RUN/create-command.sh"
printf '\n' >> "$RUN/create-command.sh"
CID=$("${CREATE[@]}" 2> "$RUN/create.stderr")
[[ "$CID" =~ ^[a-f0-9]{64}$ ]] || fail 'Unexpected Docker container ID'
printf '%s\n' "$CID" > "$RUN/container-id.txt"
docker inspect "$CID" > "$RUN/container-created.json"
python3 "$HERE/validation.py" container-image-check "$RUN"
python3 "$HERE/monitor_resources.py" "$CID" "$GPU_UUID" "$RUN/resources.jsonl" &
MONITOR=$!
# Capture PIPESTATUS immediately: tee must not hide Docker/start/timeout failures.
set +e
timeout --foreground --signal=TERM --kill-after=20s "${DEADLINE}s" docker start --attach "$CID" 2>&1 | tee "$RUN/container.log"
PIPE_CODES=("${PIPESTATUS[@]}")
set -e
DOCKER_RC=${PIPE_CODES[0]}; TEE_RC=${PIPE_CODES[1]}
printf '{"docker_attach_exit_code":%s,"tee_exit_code":%s,"wall_limit_seconds":%s}\n' "$DOCKER_RC" "$TEE_RC" "$DEADLINE" > "$RUN/exit.json"
cleanup
CONTAINER_RC=$(python3 - "$RUN/container-final.json" <<'PYCODE'
import json,sys
try:
    state=json.load(open(sys.argv[1]))[0]['State']
    print(state['ExitCode'] if not state['Running'] else 125)
except (OSError,ValueError,KeyError,IndexError):
    print(125)
PYCODE
)
set +e
python3 "$HERE/validation.py" analyze "$RUN"
ANALYSIS_RC=$?
set -e
echo "Saved host evidence: $RUN"
# Original Docker/start/timeout status wins; then log failure; then parity/audit failure.
[[ "$DOCKER_RC" == 0 ]] || exit "$DOCKER_RC"
[[ "$TEE_RC" == 0 ]] || exit "$TEE_RC"
[[ "$CONTAINER_RC" == 0 ]] || exit "$CONTAINER_RC"
exit "$ANALYSIS_RC"
