"""Verify the pinned source tree, including deployments copied without .git."""
import argparse
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, default=Path("vendor/scope"))
parser.add_argument("--manifest", type=Path, default=Path("configs/scope-source.sha256.json"))
args = parser.parse_args()
manifest = json.loads(args.manifest.read_text())
digest = hashlib.sha256()
for path in sorted((args.root / "src").rglob("*")):
    if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
        digest.update(path.relative_to(args.root).as_posix().encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
assert digest.hexdigest() == manifest["src_tree_sha256"], "Scope source tree differs from the pinned commit"
for name, expected in manifest["files_sha256"].items():
    path = args.root / name
    if name == "uv.lock" and (args.root / "uv.lock.upstream").exists():
        path = args.root / "uv.lock.upstream"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, f"Pinned file differs: {name}"
print(json.dumps({"verified": True, "commit": manifest["commit"], "src_tree_sha256": digest.hexdigest()}))
