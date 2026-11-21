#!/usr/bin/env python3
"""Read-only integrity checks; never import research, load models, or open ToolEnv."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


def relative_path(value):
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or str(path) != value:
        raise ValueError(f"Invalid manifest path: {value!r}")
    return path


def contained(root, value):
    path = root / relative_path(value)
    # Do not follow a directory symlink outside the selected root.
    if not path.parent.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes root: {value}")
    return path


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def verify_file(path, record):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing or non-regular file: {path}")
    if path.stat().st_size != record["bytes"] or digest(path) != record["sha256"]:
        raise ValueError(f"Size or SHA-256 mismatch: {path}")


def verify(root, originals_root=None, frozen_root=None):
    manifest = json.loads((root / "archive/MANIFEST.json").read_text())
    if manifest["format"] != 1 or not manifest["files"]:
        raise ValueError("Unsupported or empty archive manifest")
    for name, record in manifest["files"].items():
        if not name.startswith("archive/"):
            raise ValueError(f"Copy outside archive: {name}")
        verify_file(contained(root, name), record)
        if originals_root is not None:
            verify_file(contained(originals_root, record["source"]), record)

    frozen_count = 0
    if frozen_root is not None:
        frozen = json.loads((root / "archive/FROZEN_RC2_SHA256.json").read_text())
        names = [row["path"] for row in frozen["entries"]]
        if len(set(names)) != len(names):
            raise ValueError("Duplicate frozen manifest paths")
        actual = {
            str(path.relative_to(frozen_root))
            for path in frozen_root.rglob("*")
            if path.is_symlink() or path.is_file()
        }
        if actual != set(names):
            raise ValueError(
                f"Frozen tree membership changed: missing={sorted(set(names) - actual)}, "
                f"extra={sorted(actual - set(names))}"
            )
        for record in frozen["entries"]:
            path = contained(frozen_root, record["path"])
            if "link" in record:
                if not path.is_symlink() or str(path.readlink()) != record["link"]:
                    raise ValueError(f"Frozen symlink changed: {path}")
            else:
                verify_file(path, record)
        frozen_count = len(names)
    return {
        "status": "PASS",
        "copied_files_verified": len(manifest["files"]),
        "original_files_verified": len(manifest["files"]) if originals_root else 0,
        "frozen_entries_verified": frozen_count,
        "models_executed": 0,
        "toolenv_instances": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--originals-root", type=Path, help="Workspace containing original sibling trees")
    parser.add_argument("--frozen-root", type=Path, help="Rehash the whole original RC2 tree, including Docker archive")
    args = parser.parse_args()
    try:
        result = verify(args.root, args.originals_root, args.frozen_root)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"FAIL: {exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
