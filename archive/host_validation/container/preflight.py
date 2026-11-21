"""Runs in the constrained host-created container; does not create a ToolEnv."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys


def main():
    report = {'packaged_data_audit_pass': False, 'gpu_available': False}
    try:
        if 'sitecustomize' not in sys.modules:
            raise RuntimeError('Runtime SDK import audit was not installed')
        split = Path('/data/public_test')
        if not (split / 'zaic_tools/__init__.py').is_file():
            raise RuntimeError('Mounted SDK missing')
        # Scan names only, without reading packaged datasets or any environment file.
        forbidden = []
        packaged_sdks = []
        for base in ['/code', '/opt/k-python']:
            for root, dirs, files in os.walk(base):
                for name in dirs[:]:
                    if name == 'zaic_tools':
                        packaged_sdks.append(str(Path(root) / name))
                    if name in ('public_test', 'private_test', 'train_environment') or name.endswith('_environment'):
                        forbidden.append(str(Path(root) / name)); dirs.remove(name)
                for name in files:
                    if name in ('state.json', 'submission_K.jsonl', 'public_test.jsonl', 'private_test.jsonl', 'train.jsonl') or name.endswith(('_labels.jsonl', '_transcripts.jsonl')):
                        forbidden.append(str(Path(root) / name))
        report['forbidden_packaged_paths'] = forbidden
        report['packaged_sdk_paths'] = packaged_sdks
        report['sdk_packaging_audit_pass'] = not packaged_sdks
        if packaged_sdks:
            print('SDK COMPLIANCE FINDING: packaged SDK present; recording unchanged behavior for diagnosis:', packaged_sdks, flush=True)
        report['packaged_data_audit_pass'] = not forbidden
        if forbidden:
            raise RuntimeError('Forbidden packaged data found')
        # Resolve only. Actual imports are recorded in the inference worker by sitecustomize.
        sys.path.insert(0, str(split))
        spec = importlib.util.find_spec('zaic_tools')
        report['sdk_spec_origin'] = spec.origin if spec else None
        if spec is None or not Path(spec.origin).resolve().is_relative_to(split / 'zaic_tools'):
            raise RuntimeError('SDK resolution is outside mounted split')
        import torch
        report.update(gpu_available=torch.cuda.is_available(), gpu_count=torch.cuda.device_count())
        if not report['gpu_available'] or report['gpu_count'] != 1:
            raise RuntimeError('Exactly one CUDA GPU must be exposed')
        report.update(gpu_name=torch.cuda.get_device_name(0), capability=list(torch.cuda.get_device_capability(0)))
        if report['capability'] != [12, 0]:
            raise RuntimeError('This sealed image supports only its qualified sm120 backend')
        report['hostname'] = socket.gethostname()
        report['hostname_address'] = socket.gethostbyname(report['hostname'])
        if report['hostname_address'] != '127.0.0.1':
            raise RuntimeError('Proven hostname mapping missing')
        report['predict_sha256'] = hashlib.sha256(Path('/code/predict.py').read_bytes()).hexdigest()
        report['notebook_sha256'] = hashlib.sha256(Path('/code/predict_notebook.ipynb').read_bytes()).hexdigest()
        report['success'] = True
    except BaseException as e:
        report['error'] = repr(e)
        raise
    finally:
        with open('/result/container-preflight.json', 'x') as f:
            json.dump(report, f, indent=2); f.write('\n')

if __name__ == '__main__': main()
