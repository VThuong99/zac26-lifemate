#!/usr/bin/env bash
# Manual host steps only. No upload, training, full regression, or shared-resource cleanup.
set -euo pipefail
fail() { echo "ERROR: $*" >&2; exit 2; }
MODE=${1:-}; GPU=${2:-0}
case "$MODE" in build|verify|resume|gpu|smoke|pilot|notebook|package) ;; *) echo 'Usage: bash host.sh verify|resume|gpu|smoke|pilot|notebook|package [GPU_INDEX_OR_UUID]'; exit 2;; esac
[[ ! -e /.dockerenv && ! -e /run/.containerenv && -z ${container:-} ]] || fail 'Run on the host, never inside the development container'
if command -v systemd-detect-virt >/dev/null && systemd-detect-virt --container --quiet; then fail 'Host required'; fi
[[ $(id -u) -ne 0 ]] || fail 'Run as the host user with Docker access, not root'
ROOT=/home/duongthuong/GPU_benchmark_host
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
[[ "$HERE" == "$ROOT/lifemate-final-20261116-rc2" ]] || fail 'Unexpected host shared directory'
[[ "$GPU" =~ ^[0-9]+$ || "$GPU" =~ ^GPU-[a-fA-F0-9-]+$ ]] || fail 'Select one GPU index or UUID'
for tool in docker python3 nvidia-smi flock timeout tee; do command -v "$tool" >/dev/null || fail "Missing $tool"; done
ENDPOINT=${DOCKER_HOST:-$(docker context inspect --format '{{.Endpoints.docker.Host}}')}
[[ "$ENDPOINT" == unix://* ]] || fail 'Only the local Docker daemon is supported'
python3 "$HERE/tools/candidate.py" context
if [[ "$MODE" == resume ]]; then
  # The orchestrator owns no stage lock. Each child owns and releases its locks.
  bash "$HERE/host.sh" verify "$GPU"
  for stage in gpu smoke pilot notebook; do
    if python3 "$HERE/tools/candidate.py" completed "$stage"; then
      echo "Reusing verified $stage evidence for this unchanged image."
    else
      status=$?
      [[ "$status" == 1 ]] || exit "$status"
      bash "$HERE/host.sh" "$stage" "$GPU"
    fi
  done
  bash "$HERE/host.sh" package "$GPU"
  exit 0
fi
mkdir -p "$HERE/runs"
exec 8> "$HERE/.host-step.lock"
if ! flock -w 20 8; then
  echo "Lock still owned after 20 seconds: $HERE/.host-step.lock" >&2
  if command -v lslocks >/dev/null; then lslocks -o PID,COMMAND,TYPE,MODE,PATH >&2 || true; fi
  fail 'Another candidate step or inherited descriptor is active; preserve the lock and wait for its owner'
fi
RUN=$(mktemp -d "$HERE/runs/$(date -u +%Y%m%dT%H%M%SZ)-${MODE}-XXXXXX")
echo "Evidence: $RUN"
TAG=lifemate-k:k48.46-20261116-rc2
BASE=lifemate-k:k48.46-20261115-rc1
CID=''; MONITOR=''; CLEANED=0
cleanup() {
  [[ "$CLEANED" == 0 ]] || return 0
  CLEANED=1
  # Reap in the shell that started this exact child, never in the subshell below.
  if [[ -n "$MONITOR" ]]; then
    kill "$MONITOR" 2>/dev/null || true
    wait "$MONITOR" 2>/dev/null || true
    MONITOR=''
  fi
  (
    set +e
    if [[ -n "$CID" ]]; then
      if [[ $(docker inspect --format '{{.State.Running}}' "$CID" 2>/dev/null) == true ]]; then timeout 35s docker stop --time 20 "$CID" > "$RUN/owned-stop.log" 2>&1; fi
      if [[ $(docker inspect --format '{{.State.Running}}' "$CID" 2>/dev/null) == true ]]; then timeout 20s docker kill "$CID" > "$RUN/owned-kill.log" 2>&1; fi
      docker logs "$CID" > "$RUN/container-recovered.log" 2>&1
      docker inspect "$CID" > "$RUN/container-final.json"
      docker rm "$CID" > "$RUN/owned-remove.log" 2>&1
    fi
    nvidia-smi -i "$GPU" --query-gpu=name,memory.used,utilization.gpu --format=csv > "$RUN/gpu-after.csv" 2>&1
  )
}
trap 'rc=$?; cleanup; exit "$rc"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if [[ "$MODE" != package && "$MODE" != verify ]]; then
  python3 - "$MODE" <<'PY'
from datetime import datetime, timezone
import sys
remaining=(datetime(2026,11,16,15,0,tzinfo=timezone.utc)-datetime.now(timezone.utc)).total_seconds()
budget={'build':1920, 'gpu':120, 'smoke':600, 'pilot':1200, 'notebook':1200}[sys.argv[1]]
if remaining < budget: raise SystemExit('Reserved packaging/transfer window starts 22:00 GMT+7. Do not start this test now; consult FINAL_SUBMISSION_ACTIONS.md.')
print('Minutes until packaging/transfer reserve:',round(remaining/60,1))
PY
fi
if [[ "$MODE" == verify ]]; then
  docker image inspect "$BASE" > "$RUN/base-inspect.json"
  python3 "$HERE/tools/candidate.py" base "$RUN/base-inspect.json" > "$RUN/base-reference.txt"
  docker image inspect "$TAG" > "$RUN/image-inspect.json"
  python3 "$HERE/tools/candidate.py" resume-build "$RUN" > "$RUN/verified-image-reference.txt"
  echo "Existing rc2 verified; no image was built or changed: $(cat "$RUN/verified-image-reference.txt")"
  exit 0
fi
if [[ "$MODE" == build ]]; then
  [[ ! -e "$HERE/BUILD.json" ]] || fail 'Already built: use gpu, smoke, pilot, notebook or package'
  if docker image inspect "$TAG" >/dev/null 2>&1; then fail 'Candidate tag already exists; refusing to overwrite it'; fi
  docker image inspect "$BASE" > "$RUN/base-inspect.json"
  python3 "$HERE/tools/candidate.py" base "$RUN/base-inspect.json" > "$RUN/base-reference.txt"
  python3 - "$HERE" <<'PY'
import shutil,sys
free=shutil.disk_usage(sys.argv[1]).free
if free < 70*1024**3: raise SystemExit('Need 70 GiB free for flattened image and export; do not delete protected artifacts')
PY
  echo 'Building offline from the verified imported rc1; no GPU is used during build.'
  timeout --foreground --signal=TERM --kill-after=20s 1800s docker build --network none --pull=false --provenance=false --progress=plain \
    --build-arg "BASE_IMAGE=$BASE" --tag "$TAG" "$HERE" 2>&1 | tee "$RUN/build.log"
  docker image inspect "$BASE" > "$RUN/base-after.json"
  python3 "$HERE/tools/candidate.py" base "$RUN/base-after.json" > "$RUN/base-reference-after.txt"
  cmp "$RUN/base-reference.txt" "$RUN/base-reference-after.txt"
  docker image inspect "$TAG" > "$RUN/image-inspect.json"
  python3 "$HERE/tools/candidate.py" record-build "$RUN" > "$RUN/verified-image-reference.txt"
  MODE=gpu
fi
python3 "$HERE/tools/candidate.py" prerequisite "$MODE"
docker image inspect "$TAG" > "$RUN/current-image-inspect.json"
IMAGE=$(python3 "$HERE/tools/candidate.py" image "$RUN/current-image-inspect.json")
[[ "$IMAGE" =~ ^sha256:[a-f0-9]{64}$ ]] || fail 'Invalid immutable image reference'
if [[ "$MODE" == package ]]; then
  python3 "$HERE/tools/package.py" "$IMAGE" "$RUN" 2>&1 | tee "$RUN/package.log"
  exit 0
fi
cp "$RUN/current-image-inspect.json" "$RUN/image-inspect.json"
python3 "$HERE/tools/candidate.py" inputs "$RUN" "$MODE"
nvidia-smi -i "$GPU" --query-gpu=uuid,name,memory.used,memory.free,utilization.gpu --format=csv,noheader,nounits > "$RUN/gpu-before.csv"
GPU_UUID=$(python3 - "$RUN/gpu-before.csv" <<'PY'
import csv,sys
rows=list(csv.reader(open(sys.argv[1])))
if len(rows)!=1: raise SystemExit('Exactly one GPU required')
uuid,name,used,free,util=[v.strip() for v in rows[0]]
if int(used)>1024 or int(free)<12000 or int(util)>5: raise SystemExit('GPU busy or insufficient headroom. Wait for its owner; do not stop other workloads.')
print(uuid)
PY
)
exec 9> "$ROOT/lifemate-host-validation/.validation-${GPU_UUID}.lock"
flock -w 20 9 || fail 'Another validator owns this GPU; preserve the lock and wait for its owner'
nvidia-smi -i "$GPU_UUID" --query-compute-apps=pid,process_name,used_gpu_memory --format=csv,noheader > "$RUN/gpu-processes-before.csv"
[[ ! -s "$RUN/gpu-processes-before.csv" ]] || fail 'GPU has existing compute processes; wait for their owner'
mkdir "$RUN/harness"
for helper in entry.sh preflight.py run_notebook.py sitecustomize.py; do cp "$HERE/container/$helper" "$RUN/harness/"; done
NAME="lifemate-rc2-$(basename "$RUN")"
CREATE=(docker create --name "$NAME" --label "lifemate.final-validation=$NAME"
  --network none --gpus "device=$GPU_UUID" --cpus 16 --memory 48g --memory-swap 48g --shm-size 2g --pids-limit 1024
  --user "$(id -u):$(id -g)" --cap-drop ALL --security-opt no-new-privileges
  --mount "type=bind,src=$ROOT/lifemate/public_test,dst=/data/public_test,readonly"
  --mount "type=bind,src=$RUN,dst=/result"
  --mount "type=bind,src=$RUN/harness,dst=/validation,readonly"
  --env HOME=/result/home --env USER=lifemate-validation --env LOGNAME=lifemate-validation
  --env XDG_CACHE_HOME=/result/cache --env JUPYTER_RUNTIME_DIR=/result/jupyter-runtime
  --env PYTHONPATH=/validation:/opt/k-python/main:/opt/k-python/sherpa:/opt/k-python/jupyter
  --env LIFEMATE_DATA_ROOT=/data --env LIFEMATE_SPLIT=public_test
  --env LIFEMATE_NOTEBOOK_OUTPUT=/result/jupyter_submission.jsonl
  "$IMAGE" /bin/bash /validation/entry.sh "$MODE")
printf '%q ' "${CREATE[@]}" > "$RUN/create-command.sh"
printf '\n' >> "$RUN/create-command.sh"
CID=$("${CREATE[@]}")
[[ "$CID" =~ ^[a-f0-9]{64}$ ]] || fail 'Invalid owned container ID'
docker inspect "$CID" > "$RUN/container-created.json"
python3 - "$RUN/container-created.json" "$IMAGE" <<'PY'
import json,sys
c=json.load(open(sys.argv[1]))[0]
assert c['Config']['Image']==sys.argv[2], 'Created container does not use verified reference'
assert c['HostConfig']['NetworkMode']=='none'
PY
# Telemetry and its subprocesses must never keep either validation lock alive.
python3 "$ROOT/lifemate-host-validation/monitor_resources.py" "$CID" "$GPU_UUID" "$RUN/resources.jsonl" 8>&- 9>&- &
MONITOR=$!
DEADLINE=1200
[[ "$MODE" != gpu ]] || DEADLINE=120
[[ "$MODE" != smoke ]] || DEADLINE=600
set +e
timeout --foreground --signal=TERM --kill-after=20s "${DEADLINE}s" docker start --attach "$CID" 2>&1 | tee "$RUN/container.log"
CODES=("${PIPESTATUS[@]}")
set -e
printf '{"docker_attach_exit_code":%s,"tee_exit_code":%s}\n' "${CODES[0]}" "${CODES[1]}" > "$RUN/exit.json"
cleanup
set +e
python3 "$HERE/tools/candidate.py" analyze "$RUN"
ANALYSIS=$?
set -e
echo "Saved evidence: $RUN"
[[ "${CODES[0]}" == 0 ]] || exit "${CODES[0]}"
[[ "${CODES[1]}" == 0 ]] || exit "${CODES[1]}"
exit "$ANALYSIS"
