#!/usr/bin/env python3
"""Export already-public training source into a NEW workspace; execute no training.

Preserves historical paths and bytes. Restricted inputs and the excluded parity
report are never restored. This is source extraction, not a runnable environment.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path("archive/rc2/overlay/training_code/restored/lifemate")


def export_source(output, root=ROOT):
    output = Path(output).resolve()
    if output.is_relative_to(root.resolve()) or root.resolve().is_relative_to(output):
        raise ValueError("Choose a new training workspace outside this repository")
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite: {output}")
    source = root / SOURCE
    receipt = json.loads((source / "RESTORE_RECEIPT.json").read_text())
    exclusions = json.loads((root / "archive/PUBLIC_EXCLUSIONS.json").read_text())["excluded"]
    excluded = {entry["path"]: entry["sha256"] for entry in exclusions}
    payloads, omitted = {}, []
    for name, expected in receipt["files_sha256"].items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or str(relative) != name:
            raise ValueError(f"Unsafe source path: {name}")
        path = source / name
        if str(SOURCE / name) in excluded:
            if excluded[str(SOURCE / name)] != expected:
                raise ValueError(f"Exclusion hash mismatch: {name}")
            omitted.append(name)
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(source.resolve()):
            raise ValueError(f"Unsafe source file: {name}")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f"Training source hash mismatch: {name}")
        payloads[name] = data
    # Verify the complete source selection before creating any output.
    output.mkdir(parents=True, exist_ok=False)
    for name, data in payloads.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    report = {
        "status": "SOURCE_ONLY",
        "files": len(payloads),
        "excluded": omitted,
        "training_executed": False,
        "data_or_weights_copied": False,
        "historical_absolute_paths_preserved": True,
        "files_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()},
    }
    (output / "PUBLIC_SOURCE_EXPORT.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = export_source(args.output)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"FAIL: {exc}\n")
    print(json.dumps({key: value for key, value in report.items() if key != "files_sha256"}, indent=2))


if __name__ == "__main__":
    main()
