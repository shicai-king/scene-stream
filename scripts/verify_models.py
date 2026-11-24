import argparse
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--root", default="models")
parser.add_argument("--manifest", default="configs/models.sha256.json")
parser.add_argument("--report", default="results/raw/model-verification.json")
args = parser.parse_args()
manifest = json.loads(Path(args.manifest).read_text())
results = []
for repo in manifest["repositories"]:
    for expected in repo["files"]:
        path = Path(args.root) / repo["repo_id"].split("/")[-1] / expected["path"]
        digest = hashlib.sha256()
        if not path.is_file() or path.stat().st_size != expected["size"]:
            raise SystemExit(f"Missing or incorrect size: {path}")
        with path.open("rb") as file:
            while chunk := file.read(8 * 1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != expected["sha256"]:
            raise SystemExit(f"SHA256 mismatch: {path}")
        item = {"repo_id": repo["repo_id"], "revision": repo["revision"], "path": expected["path"], "size": expected["size"], "sha256": digest.hexdigest(), "verified": True}
        results.append(item)
        print(json.dumps(item), flush=True)
output = Path(args.report)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps({"verified": True, "files": results}, indent=2))
