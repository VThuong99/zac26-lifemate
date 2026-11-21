"""Runs only inside the exact RC2 image; never creates ToolEnv or runs inference."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    report = {'success': False}
    try:
        assert 'sitecustomize' in sys.modules, 'SDK audit observer missing'
        forbidden = []
        for base in ('/code', '/opt/k-python'):
            for root, dirs, files in os.walk(base):
                for name in dirs[:]:
                    if name == 'zaic_tools' or name.endswith('_environment'):
                        forbidden.append(str(Path(root) / name))
                        dirs.remove(name)
                for name in files:
                    if name in ('state.json', 'submission_K.jsonl', 'public_test.jsonl', 'private_test.jsonl', 'train.jsonl'):
                        forbidden.append(str(Path(root) / name))
        report['forbidden_packaged_paths'] = forbidden
        assert not forbidden, forbidden
        # This is the frozen image's own verifier, not a replacement implementation.
        checked = subprocess.run([sys.executable, '/code/verify_release.py', '--image'], text=True, capture_output=True)
        report['image_artifact_verifier'] = {'returncode': checked.returncode, 'stdout': checked.stdout, 'stderr': checked.stderr}
        assert checked.returncode == 0, 'Frozen image artifact verifier failed'
        import torch
        assert torch.cuda.is_available() and torch.cuda.device_count() == 1
        report['gpu_name'] = torch.cuda.get_device_name(0)
        report['capability'] = list(torch.cuda.get_device_capability(0))
        assert 'RTX 5090' in report['gpu_name'] and report['capability'] == [12, 0]
        torch.zeros(1, device='cuda').add_(1)
        torch.cuda.synchronize()
        report['torch_version'] = torch.__version__
        report['torch_cuda_version'] = torch.version.cuda
        sys.path.insert(0, '/data/private_test')
        spec = importlib.util.find_spec('zaic_tools')
        report['sdk_origin'] = spec.origin if spec else None
        assert spec and Path(spec.origin).resolve().is_relative_to(Path('/data/private_test/zaic_tools'))
        import zaic_tools
        assert callable(zaic_tools.ToolEnv)
        from zaic_tools.apps import TOOLS
        catalog = json.loads(Path('/data/private_test/private_test_tools_catalog.json').read_text())
        names = {t['name'] for app in catalog['apps'] for t in app['tools']}
        report['missing_tool_implementations'] = sorted(names - TOOLS.keys())
        assert not report['missing_tool_implementations']
        assert len(names) == 207
        report['toolenv_instances_created'] = 0
        report['success'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        with Path('/result/preflight.json').open('x') as stream:
            json.dump(report, stream, indent=2)
            stream.write('\n')


if __name__ == '__main__':
    main()
