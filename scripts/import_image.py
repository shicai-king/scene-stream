"""Import an immutable registry image without changing Docker daemon proxy settings.

Requires a verified `crane` binary. All proxy overrides apply to this process only.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

parser = argparse.ArgumentParser()
parser.add_argument("image")
parser.add_argument("--tag", required=True)
parser.add_argument("--archive", required=True)
parser.add_argument("--crane", default="tools/crane")
parser.add_argument("--direct", action="store_true")
args = parser.parse_args()
env = os.environ.copy()
if args.direct:
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(key, None)
digest = subprocess.check_output([args.crane, "digest", args.image], env=env, text=True).strip()
repository = args.image.split("@")[0]
if ":" in repository.rsplit("/", 1)[-1]:
    repository = repository.rsplit(":", 1)[0]
immutable = repository + "@" + digest
archive = Path(args.archive)
archive.parent.mkdir(parents=True, exist_ok=True)
print(json.dumps({"event": "image_download", "image": immutable}), flush=True)
subprocess.run([args.crane, "pull", "--platform", "linux/amd64", immutable, str(archive)], env=env, check=True)
subprocess.run(["docker", "load", "-i", str(archive)], check=True)
with tarfile.open(archive) as stream:
    manifest = json.load(stream.extractfile("manifest.json"))
    config = stream.extractfile(manifest[0]["Config"]).read()
    image_id = "sha256:" + hashlib.sha256(config).hexdigest()
subprocess.run(["docker", "tag", image_id, args.tag], check=True)
report = {"image": immutable, "local_tag": args.tag, "image_id": image_id}
archive.with_suffix(".json").write_text(json.dumps(report, indent=2))
print(json.dumps(report), flush=True)
