"""Bounded candidate checks; never construct a ToolEnv or read hidden data."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys


def main():
    report = {'success': False}
    try:
        assert 'sitecustomize' in sys.modules, 'Audit hook missing'
        bad = []
        for base in ('/code', '/opt/k-python'):
            for root, dirs, files in os.walk(base):
                for name in dirs[:]:
                    if name == 'zaic_tools' or name.endswith('_environment'):
                        bad.append(str(Path(root) / name)); dirs.remove(name)
                for name in files:
                    if name in ('state.json', 'submission_K.jsonl', 'public_test.jsonl', 'private_test.jsonl', 'train.jsonl'):
                        bad.append(str(Path(root) / name))
        report['forbidden_packaged_paths'] = bad
        assert not bad, bad
        sys.path.insert(0, '/data/public_test')
        spec = importlib.util.find_spec('zaic_tools')
        report['sdk_spec_origin'] = spec.origin if spec else None
        assert spec and Path(spec.origin).resolve().is_relative_to(Path('/data/public_test/zaic_tools'))
        import torch
        assert torch.cuda.is_available() and torch.cuda.device_count() == 1
        report['capability'] = list(torch.cuda.get_device_capability(0))
        assert report['capability'] in ([8, 0], [12, 0]), report['capability']
        report['gpu_name'] = torch.cuda.get_device_name(0)
        torch.zeros(1, device='cuda').add_(1)
        torch.cuda.synchronize()
        report['predict_sha256'] = hashlib.sha256(Path('/code/predict.py').read_bytes()).hexdigest()
        report['notebook_sha256'] = hashlib.sha256(Path('/code/predict_notebook.ipynb').read_bytes()).hexdigest()
        report['hostname_flags_required'] = False
        report['success'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        Path('/result/container-preflight.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
