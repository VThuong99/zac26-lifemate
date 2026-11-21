"""Exercise get_env_info in isolation with failed DNS; no ASR/GPU imports."""
import ast
from pathlib import Path
import socket
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'lifemate-release-k-20261115/source/runtime/third_party/icefall-p12-3f848bb6/icefall/env.py'
OLD = '"IP address": socket.gethostbyname(socket.gethostname()),'
NEW = '"IP address": None,  # Diagnostic metadata: no DNS in offline inference.'


def function(source):
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'get_env_info')
    def fail(*_): raise socket.gaierror(-3, 'Temporary failure in name resolution')
    version = SimpleNamespace(__version__='stub', __build_type__='stub', __git_sha1__='stub', __git_date__='stub')
    namespace = {'Dict': dict, 'Any': object, 'Path': Path, '__file__': str(SOURCE),
                 'socket': SimpleNamespace(gethostname=lambda: 'unresolvable-host', gethostbyname=fail),
                 'sys': SimpleNamespace(version='3.12.0'),
                 'k2': SimpleNamespace(version=version, with_cuda=True, __file__='/stub/k2.py'),
                 'lhotse': SimpleNamespace(__version__='stub', __file__='/stub/lhotse.py'),
                 'torch': SimpleNamespace(__version__='stub', version=SimpleNamespace(cuda='stub'), cuda=SimpleNamespace(is_available=lambda: True)),
                 'get_git_branch_name': lambda: None, 'get_git_sha1': lambda: None, 'get_git_date': lambda: None}
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<isolated-env-info>', 'exec'), namespace)
    return namespace['get_env_info']


class HostnameTests(unittest.TestCase):
    def test_current_metadata_lookup_fails_with_dns_error(self):
        with self.assertRaises(socket.gaierror): function(SOURCE.read_text())()

    def test_proposed_change_never_calls_resolver(self):
        source = SOURCE.read_text(); self.assertEqual(source.count(OLD), 1)
        metadata = function(source.replace(OLD, NEW))()
        self.assertEqual(metadata['hostname'], 'unresolvable-host'); self.assertIsNone(metadata['IP address'])


if __name__ == '__main__': unittest.main()
