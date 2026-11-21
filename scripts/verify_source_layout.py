#!/usr/bin/env python3
"""Check the portable core against its frozen source, allowing only mapped imports."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify(root=ROOT):
    manifest = json.loads((root / "configs/source_layout.json").read_text())
    if manifest["format"] != 1 or not manifest["files"]:
        raise ValueError("Unsupported or empty source-layout manifest")
    targets = set()
    for record in manifest["files"]:
        source, target = root / record["source"], root / record["target"]
        for path in (source, target):
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError(f"Invalid source-layout path: {path}")
        if record["target"] in targets:
            raise ValueError("Duplicate source-layout target")
        targets.add(record["target"])
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != record["source_sha256"]:
            raise ValueError(f"Frozen source changed: {source}")
        expected = raw.decode("utf-8")
        for old, new in manifest["import_modules"].items():
            expected = expected.replace(f"from src.{old} import ", f"from lifemate.{new} import ")
        if expected.encode("utf-8") != target.read_bytes():
            raise ValueError(f"Source differs beyond import relocation: {target}")
    return {"status": "PASS", "mapped_modules": len(targets), "behavior_changes": 0}


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
