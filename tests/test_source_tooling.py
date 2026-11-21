"""Protect the clean source boundary, extraction semantics and import safety."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.export_training_source import export_source
from scripts.verify_archive import verify as verify_archive
from scripts.verify_source_layout import verify as verify_source_layout

ROOT = Path(__file__).resolve().parents[1]


class SourceTests(unittest.TestCase):
    def test_source_layout_has_only_documented_import_changes(self):
        self.assertEqual(verify_source_layout()["mapped_modules"], 15)

    def test_public_archive_hashes(self):
        self.assertEqual(verify_archive(ROOT)["copied_files_verified"], 363)

    def test_all_portable_modules_import_without_gpu_dependencies(self):
        modules = [f"lifemate.{path.stem}" for path in (ROOT / "src/lifemate").glob("*.py") if path.stem != "__init__"]
        code = (
            "import importlib, sys; "
            f"[importlib.import_module(name) for name in {modules!r}]; "
            "assert not ({'torch', 'transformers', 'sherpa_onnx', 'zaic_tools', 'numpy'} & set(sys.modules))"
        )
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_synthetic_demo_cli(self):
        result = subprocess.run([sys.executable, "-m", "lifemate.demo"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "finished")

    def test_training_export_omits_restricted_report_and_matches_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "training"
            report = export_source(output)
            self.assertEqual(report["files"], 64)
            self.assertEqual(report["excluded"], ["results/p34_gipformer_finetune_v1/export_parity.json"])
            self.assertFalse((output / report["excluded"][0]).exists())
            self.assertFalse(report["training_executed"])
            self.assertFalse(report["data_or_weights_copied"])
            self.assertTrue((output / "scripts/train_p19_real_asr.py").is_file())
            with self.assertRaises(FileExistsError):
                export_source(output)

    def test_training_export_refuses_repository_destinations(self):
        with self.assertRaises(ValueError):
            export_source(ROOT / "training/generated")

    def test_recorded_rc2_configuration_parses(self):
        import tomllib
        config = tomllib.loads((ROOT / "configs/rc2-reference.toml").read_text())
        self.assertEqual(config["planner"]["context_tokens"], 8192)
        self.assertEqual(config["planner"]["request_deadline_seconds"], 30)
        self.assertEqual(config["release"]["worker_arm"], "C")

    def test_all_documented_core_modules_are_discoverable(self):
        for name in ("asr", "phowhisper", "llm_planner", "agent", "controller", "evaluation"):
            with self.subTest(name=name):
                self.assertIsNotNone(importlib.util.find_spec(f"lifemate.{name}"))
