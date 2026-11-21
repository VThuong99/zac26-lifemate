"""Test the actual frozen RC2 transport with synthetic inputs and fake backends."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TRANSPORT = ROOT / "archive/rc2/overlay/predict.py"
SPEC = importlib.util.spec_from_file_location("frozen_rc2_transport", TRANSPORT)
transport = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(transport)


class TransportTests(unittest.TestCase):
    def fixture(self, root, split="synthetic"):
        directory = root / split
        (directory / "zaic_tools").mkdir(parents=True)
        (directory / "zaic_tools/__init__.py").write_text("")
        (directory / f"{split}_tools_catalog.json").write_text('{"apps":[]}')
        row = {"id": "synthetic", "audio": "audio/mock.wav", "context": {}, "history": []}
        (directory / f"{split}.jsonl").write_text(json.dumps(row) + "\n")
        return directory / f"{split}.jsonl", row

    def test_split_selection_requires_an_unambiguous_sdk_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            self.assertEqual(transport.discover_split(root), "synthetic")
            self.fixture(root, "second")
            with self.assertRaises(ValueError):
                transport.discover_split(root)
            self.assertEqual(transport.discover_split(root, "second"), "second")
            with self.assertRaises(ValueError):
                transport.discover_split(root, "absent")

    def test_reference_fields_and_duplicate_ids_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, row = self.fixture(root)
            variants = [
                [{**row, "label": {}}],
                [{**row, "history": [{"role": "user", "audio_text": "synthetic reference"}]}],
                [row, row],
            ]
            for rows in variants:
                with self.subTest(rows=rows):
                    path.write_text("".join(json.dumps(value) + "\n" for value in rows))
                    with self.assertRaises(ValueError):
                        transport.read_cases(root, "synthetic")

    def test_context_overflow_preserves_prefix_but_aborts_batch(self):
        class Runtime:
            def infer(self, item, index):
                if index:
                    raise RuntimeError("synthetic 8192-token context overflow")
                return {"id": "synthetic-first", "tool_calls": [], "state_hash": "mock", "time": 1}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "submission.jsonl"
            with self.assertRaisesRegex(RuntimeError, "context overflow"):
                transport.write_predictions(Runtime(), [{}, {}], output)
            self.assertFalse(output.exists())
            rows = output.with_suffix(".jsonl.partial").read_text().splitlines()
            self.assertEqual(len(rows), 1)
            self.assertEqual(json.loads(rows[0])["id"], "synthetic-first")

    def test_successful_batch_commits_output_and_refuses_overwrite(self):
        runtime = SimpleNamespace(infer=lambda item, index: {"id": "synthetic", "tool_calls": [], "state_hash": "mock", "time": 1})
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "submission.jsonl"
            transport.write_predictions(runtime, [{}], output)
            original = output.read_bytes()
            self.assertFalse(output.with_suffix(".jsonl.partial").exists())
            with self.assertRaises(FileExistsError):
                transport.write_predictions(runtime, [{}], output)
            self.assertEqual(output.read_bytes(), original)

    def test_rc2_backend_selection_with_fake_cuda_capabilities(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for capability, target in [((8, 0), "sm80"), ((12, 0), "sm120")]:
                binary = root / target / "bin/llama-server"
                binary.parent.mkdir(parents=True)
                binary.touch()
                torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True, get_device_capability=lambda index: capability))
                with patch.dict(sys.modules, {"torch": torch}):
                    self.assertEqual(transport.backend_for_device(root), (target, binary))
            torch.cuda.get_device_capability = lambda index: (9, 0)
            with patch.dict(sys.modules, {"torch": torch}), self.assertRaisesRegex(RuntimeError, "Unqualified"):
                transport.backend_for_device(root)

    def test_offline_guard_in_isolated_process(self):
        code = "from predict import offline_guard; import sys; offline_guard(); sys.audit('socket.connect', None, ('192.0.2.1', 443))"
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=TRANSPORT.parent, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Offline inference rejected", result.stderr)
