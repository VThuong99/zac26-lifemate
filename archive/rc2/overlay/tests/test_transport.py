import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from predict import discover_split, read_cases, write_predictions, backend_for_device

class TransportTest(unittest.TestCase):
    def fixture(self, root, split):
        p=root/split;p.mkdir()
        (p/'zaic_tools').mkdir();(p/'zaic_tools/__init__.py').write_text('')
        (p/(split+'_tools_catalog.json')).write_text('{"apps":[]}')
        row={'id':'unseen_case','audio':'audio/unseen_case.wav','context':{},'history':[]}
        (p/(split+'.jsonl')).write_text(json.dumps(row)+'\n')
        return p,row

    def test_private_split_discovery_and_ambiguous_mount(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.fixture(root,'private_test')
            self.assertEqual(discover_split(root),'private_test')
            self.fixture(root,'public_test')
            with self.assertRaises(ValueError):discover_split(root)
            self.assertEqual(discover_split(root,'private_test'),'private_test')

    def test_reference_fields_and_duplicate_ids_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p,row=self.fixture(root,'private_test')
            file=p/'private_test.jsonl'
            file.write_text(json.dumps({**row,'label':{}})+'\n')
            with self.assertRaises(ValueError):read_cases(root,'private_test')
            file.write_text((json.dumps(row)+'\n')*2)
            with self.assertRaises(ValueError):read_cases(root,'private_test')

    def test_partial_failure_never_becomes_submission(self):
        class Failed:
            def infer(self,item,index):
                if index:raise TimeoutError('actual request timeout')
                return {'id':'first','tool_calls':[],'state_hash':'hash','time':1}
        with tempfile.TemporaryDirectory() as d:
            output=Path(d)/'submission.jsonl'
            with self.assertRaises(TimeoutError):write_predictions(Failed(),[{},{}],output)
            self.assertFalse(output.exists())
            self.assertTrue(output.with_suffix('.jsonl.partial').exists())

    def test_offline_socket_guard(self):
        code="from predict import offline_guard; import sys; offline_guard(); sys.audit('socket.connect',None,('192.0.2.1',443))"
        r=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
        self.assertNotEqual(r.returncode,0)
        self.assertIn('Offline inference rejected an external socket',r.stderr)

    def test_failed_ampere_candidate_cannot_be_auto_selected(self):
        torch=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:True,get_device_capability=lambda i:(8,0)))
        with patch.dict(sys.modules,{'torch':torch}):
            with self.assertRaisesRegex(RuntimeError,'changed a consequential K decision'):
                backend_for_device('/unused')

if __name__=='__main__':unittest.main()
