"""Rewrite only download origins in a deployment copy of Scope's lockfile.

Package versions, hashes and dependency markers stay pinned. The original is
retained next to the deployment lock and must match the pinned source commit.
"""
import argparse
import hashlib
from pathlib import Path
import tomllib

parser = argparse.ArgumentParser()
parser.add_argument("scope_path", type=Path)
parser.add_argument("--restore", action="store_true")
args = parser.parse_args()
lock = args.scope_path / "uv.lock"
backup = args.scope_path / "uv.lock.upstream"
if args.restore:
    lock.write_bytes(backup.read_bytes())
    raise SystemExit("Restored the upstream lockfile")
if not backup.exists():
    backup.write_bytes(lock.read_bytes())
original = backup.read_text()
rewritten = original
for before, after in [
    ("https://files.pythonhosted.org/packages/", "https://mirrors.aliyun.com/pypi/packages/"),
    ("https://pypi.org/simple", "https://mirrors.aliyun.com/pypi/simple"),
    ("https://download-r2.pytorch.org/whl/", "https://mirrors.aliyun.com/pytorch-wheels/"),
    ("https://download.pytorch.org/whl/", "https://mirrors.aliyun.com/pytorch-wheels/"),
]:
    rewritten = rewritten.replace(before, after)


def fingerprints(text):
    return sorted((package["name"], package["version"], tuple(sorted(wheel.get("hash", "") for wheel in package.get("wheels", []))), package.get("sdist", {}).get("hash", "")) for package in tomllib.loads(text)["package"])


assert fingerprints(original) == fingerprints(rewritten)
lock.write_text(rewritten)
print("Rewrote only dependency download origins; versions and artifact hashes preserved")
print("upstream_lock_sha256=" + hashlib.sha256(original.encode()).hexdigest())
