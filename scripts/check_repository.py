#!/usr/bin/env python3
"""Bounded source-publication checks: syntax, local doc links, file types, secrets.

Examines Git's tracked and nonignored file set. Prints paths, never matching
secret contents. Pattern checks cannot prove ownership or absence of all secrets.
"""

import ast
import json
from pathlib import Path
import re
import subprocess
import tomllib
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_SUFFIXES = {
    ".jsonl", ".wav", ".flac", ".mp3", ".ogg", ".m4a", ".pt", ".pth",
    ".ckpt", ".gguf", ".safetensors", ".onnx", ".bin", ".pkl", ".pickle",
    ".npy", ".npz", ".zip", ".tar", ".gz", ".tgz", ".whl", ".so", ".pem", ".key",
}
SECRET_PATTERNS = [
    re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{60,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"hf_[A-Za-z0-9]{30,}"),
]


def publication_paths(root=ROOT):
    raw = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root
    )
    return sorted({name for name in raw.decode().split("\0") if name})


def check(root=ROOT):
    paths = publication_paths(root)
    issues, counts = [], {"files": len(paths), "python": 0, "json": 0, "shell": 0, "links": 0}
    for name in paths:
        path = root / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            issues.append(f"Nonregular or missing publication file: {name}")
            continue
        if path.suffix in FORBIDDEN_SUFFIXES or path.name.startswith(".env") or any(
            part in {".aws", ".ssh"} for part in path.parts
        ):
            issues.append(f"Forbidden publication file: {name}")
        data = path.read_bytes()
        if len(data) > 1024 * 1024 or b"\0" in data:
            issues.append(f"Binary or oversized publication file: {name}")
            continue
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError:
            issues.append(f"Non-UTF8 publication file: {name}")
            continue
        if any(pattern.search(content) for pattern in SECRET_PATTERNS):
            issues.append(f"Potential credential: {name}")
        try:
            if path.suffix == ".py":
                ast.parse(content, filename=name)
                counts["python"] += 1
            elif path.suffix in {".json", ".ipynb"}:
                json.loads(content)
                counts["json"] += 1
            elif path.suffix == ".toml":
                tomllib.loads(content)
            elif path.suffix == ".sh":
                subprocess.run(["bash", "-n", str(path)], check=True, capture_output=True)
                counts["shell"] += 1
        except (SyntaxError, ValueError, subprocess.CalledProcessError) as exc:
            issues.append(f"Syntax failure in {name}: {type(exc).__name__}")
        # Historical archive docs intentionally refer to missing private inputs.
        if path.suffix == ".md" and not name.startswith("archive/"):
            for target in re.findall(r"\[[^\]]*\]\(([^\s)]+)\)", content):
                parsed = urlsplit(target.strip("<>"))
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                counts["links"] += 1
                resolved = (path.parent / unquote(parsed.path)).resolve()
                if not resolved.is_relative_to(root.resolve()) or not resolved.exists():
                    issues.append(f"Broken local link in {name}: {target}")
    if issues:
        raise ValueError("\n".join(issues))
    return {"status": "PASS", **counts, "secret_pattern_matches": 0}


if __name__ == "__main__":
    print(json.dumps(check(), indent=2))
