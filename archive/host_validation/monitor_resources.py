#!/usr/bin/env python3
"""Read-only monitor scoped to our container and selected GPU."""
import json
import signal
import subprocess
import sys
import time

stopped = False

def stop(*_):
    global stopped
    stopped = True

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)

def capture(command):
    try:
        p = subprocess.run(command, capture_output=True, text=True, timeout=8)
        return {'exit_code': p.returncode, 'stdout': p.stdout.strip(), 'stderr': p.stderr.strip()}
    except subprocess.TimeoutExpired:
        return {'error': 'query timed out'}

if __name__ == '__main__':
    cid, gpu, out = sys.argv[1:]
    with open(out, 'x', buffering=1) as f:
        while not stopped:
            row = {'unix_time': time.time(),
                   'docker_stats': capture(['docker', 'stats', '--no-stream', '--format', '{{json .}}', cid]),
                   'gpu': capture(['nvidia-smi', '-i', gpu, '--query-gpu=uuid,memory.used,memory.free,utilization.gpu', '--format=csv,noheader,nounits'])}
            f.write(json.dumps(row) + '\n')
            time.sleep(2)
