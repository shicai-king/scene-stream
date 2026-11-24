# Docker with dependencies on a shared disk

Use this variant when the Docker storage partition cannot hold the full CUDA image. Python environments, models and cache live under the project directory; a small, digest-pinned official Python image contains only application code. This does not change Docker's global data-root or host drivers.

Prepare the production frontend locally with `npm ci && npm run build`, then copy the source and `dist/` to the server. Do not copy `.git`, `.env`, local credentials, `node_modules`, or the local `.venv`.

On the server, from the project directory:

```bash
# Requires uv, git and Python 3; installs Python 3.12.8 under runtime/.
bash scripts/prepare_shared_runtime.sh
# Optional alternative download origins; package versions and hashes stay fixed:
# bash scripts/prepare_shared_runtime.sh --use-mirrors

python3 scripts/download_verified_models.py
# For a network where the official host is unavailable:
# python3 scripts/download_verified_models.py --endpoint https://hf-mirror.com --workers 8
# Use alternate model repositories with the exact same official file hashes:
# python3 scripts/download_verified_models.py --mirrors configs/models.mirrors.json --workers 8 --file-workers 2
python3 scripts/verify_models.py

docker build -f deploy/Dockerfile.runtime -t longlive-runtime:0.1.0 .
runtime/hub-env/bin/python scripts/render_scope_deployment.py \
  --gpu-ids 0,1 --width 384 --height 224 --runtime-root "$PWD/runtime"
docker compose -f compose.scope.local.yaml up --no-build -d
```

`--gpu-ids` must contain only devices the operator may use. The renderer creates writable worker log directories as the current user. The containers run as that user and mount only their required environment, managed Python and Scope source as read-only, plus model/log/config directories. No host network or Docker socket is mounted. Assets and per-process caches remain inside the worker's temporary directory.

The deployment source must match `configs/scope-source.sha256.json`. `use_dependency_mirrors.py` keeps `vendor/scope/uv.lock.upstream`, changes only PyPI/PyTorch download origins in the deployment copy, and verifies unchanged versions and artifact hashes. `--restore` restores the original lock. The mirror directory is documented by [Aliyun](https://mirrors.aliyun.com/pytorch-wheels/cu128/). SageAttention is omitted and disabled; see [compatibility](compatibility.md).

The full-range downloader verifies every completed file against the official manifest before installing it. Its `cache/model-parts/` directory supports interrupted-download recovery. Run only one downloader per file/cache directory. Source and weight verification must pass before loading the model.

`configs/models.mirrors.json` maps official SHA256 values to fixed ModelScope revisions whose API metadata reports the same size and hash. It does not replace the official manifest. Files absent from this mapping still use the selected Hugging Face endpoint. `--file-workers` limits concurrent files; `--workers` limits range requests per file.

If the base image was imported by Docker archive, the archive may lack a RepoDigest. Verify `docker image inspect` returns the `linux_amd64_image_id` in `configs/images.lock.json`, then build with `--build-arg RUNTIME_IMAGE=ghcr.io/astral-sh/uv:0.9.11-python3.12-bookworm-slim`. This changes the local lookup reference, not the verified image content.

For a GPU kernel check before starting the service:

```bash
docker compose -f compose.scope.local.yaml run --rm --no-deps worker-1 \
  "$PWD/runtime/scope-env/bin/python" /opt/longlive/probe_gpu.py
```

This uses only that worker's assigned GPU. Real model loading, prompt response and recovery still need separate validation; a successful CUDA probe alone does not complete Level 2.

This variant depends on stable absolute paths: moving the project requires recreating its virtual environments and regenerating Compose. The standard full-image deployment is the more portable option when Docker storage is sufficient.
