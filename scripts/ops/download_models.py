"""Run with the Scope image's Python; model repository revisions are explicit."""
import argparse
import json
import os
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "180")
os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "30")
from huggingface_hub import snapshot_download

parser = argparse.ArgumentParser()
parser.add_argument("--root", default="/models")
parser.add_argument("--manifest", default="configs/models.lock.json")
parser.add_argument("--repo", help="Download only this repo ID from the pinned manifest")
args = parser.parse_args()
manifest = json.loads(Path(args.manifest).read_text())
if args.repo and not any(r["repo_id"] == args.repo for r in manifest["repositories"]):
    parser.error("Requested repo is absent from the pinned manifest")
for repository in manifest["repositories"]:
    if args.repo and repository["repo_id"] != args.repo:
        continue
    destination = Path(args.root) / repository["repo_id"].split("/")[-1]
    print(json.dumps({"event": "model_download", "repo": repository["repo_id"], "revision": repository["revision"]}), flush=True)
    for attempt in range(8):
        try:
            snapshot_download(**repository, local_dir=str(destination), max_workers=4)
            break
        except Exception as exc:
            print(json.dumps({"event": "model_download_retry", "repo": repository["repo_id"], "attempt": attempt+1, "error_type": type(exc).__name__}), flush=True)
            if attempt == 7:
                raise
            time.sleep(min(30, 2**attempt))
print(json.dumps({"event": "model_download_complete"}), flush=True)
