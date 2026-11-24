"""Resumable HTTP range downloads of the exact, SHA256-pinned model files.

Use when a proxy times out on full-file downloads. Completed parts are reusable;
only a full file matching the manifest hash is installed into the model tree.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def download_file(repo, expected, args):
    target = Path(args.root) / repo["repo_id"].split("/")[-1] / expected["path"]
    if target.is_file() and target.stat().st_size == expected["size"] and sha256(target) == expected["sha256"]:
        print(json.dumps({"event": "verified_existing", "path": str(target)}), flush=True)
        return
    parts = Path(args.parts) / expected["sha256"]
    parts.mkdir(parents=True, exist_ok=True)
    chunk_size = args.chunk_mb * 1024 * 1024
    count = (expected["size"] + chunk_size - 1) // chunk_size
    url = f"{args.endpoint.rstrip('/')}/{repo['repo_id']}/resolve/{repo['revision']}/{quote(expected['path'])}?download=true"

    def fetch(index):
        start = index * chunk_size
        end = min(expected["size"], start + chunk_size) - 1
        size = end - start + 1
        path = parts / f"{start}-{end}.part"
        if path.is_file() and path.stat().st_size == size:
            return path
        for attempt in range(8):
            temporary = path.with_suffix(".pending")
            try:
                request = Request(url, headers={"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"})
                with urlopen(request, timeout=180) as response, temporary.open("wb") as output:
                    if response.status == 206:
                        if response.headers.get("Content-Range") != f"bytes {start}-{end}/{expected['size']}":
                            raise ValueError("Incorrect HTTP content range")
                    elif not (response.status == 200 and count == 1):
                        raise ValueError("Server did not honor the range request")
                    received = 0
                    while block := response.read(1024 * 1024):
                        received += len(block)
                        if received > size:
                            raise ValueError("Response exceeded the expected part size")
                        output.write(block)
                if temporary.stat().st_size != size:
                    raise ValueError("Incomplete part")
                temporary.replace(path)
                return path
            except Exception as error:
                print(json.dumps({"event": "part_retry", "path": expected["path"], "part": index, "attempt": attempt + 1, "error_type": type(error).__name__}), flush=True)
                if attempt == 7:
                    raise RuntimeError(f"Failed part {index} of {expected['path']}") from None
                time.sleep(min(30, 2 ** attempt))

    print(json.dumps({"event": "download_start", "path": str(target), "bytes": expected["size"], "parts": count}), flush=True)
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(fetch, i) for i in range(count)]
        for done, future in enumerate(as_completed(futures), 1):
            future.result()
            print(json.dumps({"event": "download_progress", "path": expected["path"], "parts_done": done, "parts_total": count, "elapsed_s": round(time.monotonic() - started, 1)}), flush=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".verified-download")
    digest = hashlib.sha256()
    with temporary.open("wb") as output:
        for index in range(count):
            start = index * chunk_size
            end = min(expected["size"], start + chunk_size) - 1
            with (parts / f"{start}-{end}.part").open("rb") as source:
                while block := source.read(8 * 1024 * 1024):
                    output.write(block)
                    digest.update(block)
    if digest.hexdigest() != expected["sha256"]:
        temporary.unlink()
        raise ValueError(f"SHA256 mismatch for {target}; remove its cached parts before retrying")
    temporary.replace(target)
    print(json.dumps({"event": "download_verified", "path": str(target), "sha256": digest.hexdigest(), "elapsed_s": round(time.monotonic() - started, 1)}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="models")
    parser.add_argument("--manifest", default="configs/models.sha256.json")
    parser.add_argument("--parts", default="cache/model-parts")
    parser.add_argument("--repo")
    parser.add_argument("--endpoint", default="https://huggingface.co", help="Optional HTTPS mirror; official manifest SHA256 checks remain mandatory")
    parser.add_argument("--workers", type=int, default=4, choices=range(1, 17))
    parser.add_argument("--chunk-mb", type=int, default=32, choices=range(1, 129))
    args = parser.parse_args()
    if urlsplit(args.endpoint).scheme != "https":
        parser.error("Model endpoint must use HTTPS")
    manifest = json.loads(Path(args.manifest).read_text())
    repositories = [r for r in manifest["repositories"] if not args.repo or r["repo_id"] == args.repo]
    if not repositories:
        parser.error("Requested repo is absent from the manifest")
    for repo in repositories:
        for expected in repo["files"]:
            download_file(repo, expected, args)
    print(json.dumps({"event": "all_downloads_verified"}), flush=True)


if __name__ == "__main__":
    main()
