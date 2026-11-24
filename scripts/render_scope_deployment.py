"""Generate a Compose topology and worker registry for any explicit GPU list."""
import argparse
import os
from pathlib import Path
import yaml

parser = argparse.ArgumentParser()
parser.add_argument("--gpu-ids", required=True, help="Comma-separated physical GPU IDs explicitly authorized for this deployment")
parser.add_argument("--scope-image", default="ghcr.io/daydreamlive/scope@sha256:3bed0bf78d7a6cf6b467912c9985eebf7d5479d0401cbbc5f07ed8f58ce9dfef")
parser.add_argument("--node-image", default="node:22.16.0-bookworm-slim")
parser.add_argument("--port", type=int, default=8080)
parser.add_argument("--width", type=int, default=576)
parser.add_argument("--height", type=int, default=320)
parser.add_argument("--worker-startup-timeout", type=int, default=90, help="Seconds for the owned Scope process to reach HTTP readiness")
parser.add_argument("--pipeline-ready-timeout", type=int, default=600, help="Separate model-loading deadline in seconds")
parser.add_argument("--first-frame-timeout", type=int, default=180, help="Separate first-frame deadline after connection in seconds")
parser.add_argument("--runtime-root", help="Optional preinstalled shared-disk venvs (scope-env, hub-env, python); reduces Docker layer storage")
args = parser.parse_args()
ids = args.gpu_ids.split(",")
if not ids or any(not x.isdigit() for x in ids) or len(set(ids)) != len(ids):
    parser.error("GPU IDs must be unique nonnegative integers")
if min(args.worker_startup_timeout, args.pipeline_ready_timeout, args.first_frame_timeout) <= 0:
    parser.error("Timeouts must be positive seconds")
base = yaml.safe_load(Path("configs/workers.example.yaml").read_text())
base["workers"] = []
base.update(worker_startup_timeout_s=args.worker_startup_timeout,
            pipeline_ready_timeout_s=args.pipeline_ready_timeout,
            first_frame_timeout_s=args.first_frame_timeout)
services = {"hub": {"build": {"context": ".", "args": {"NODE_IMAGE": args.node_image}}, "image": "longlive-rooms:0.1.0", "init": True, "restart": "unless-stopped", "ports": [f"127.0.0.1:{args.port}:8080"], "environment": {"WORKER_CONFIG_PATH": "/app/configs/workers.local.yaml", "LOG_PATH": "/app/logs/events.jsonl"}, "volumes": ["./configs/workers.local.yaml:/app/configs/workers.local.yaml:ro", "./logs:/app/logs"], "depends_on": {}}}
for i, gpu in enumerate(ids):
    name = f"worker-{i+1}"
    Path("logs", name).mkdir(parents=True, exist_ok=True)
    base["workers"].append({"id": name, "backend": "scope", "endpoint": f"http://{name}:8000", "control_endpoint": f"http://{name}:9100", "launch_mode": "managed", "pipeline_id": "longlive", "width": args.width, "height": args.height, "seed": 42+i})
    services[name] = {"build": {"context": ".", "dockerfile": "deploy/Dockerfile.scope", "args": {"SCOPE_IMAGE": args.scope_image}}, "image": "longlive-scope:0.2.5", "init": True, "restart": "unless-stopped", "shm_size": "2gb", "environment": {"CUDA_VISIBLE_DEVICES": "0", "NVIDIA_VISIBLE_DEVICES": gpu, "DISABLE_SAGEATTENTION": "1", "HF_HUB_DISABLE_TELEMETRY": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}, "volumes": ["./models:/models", f"./logs/{name}:/logs"], "expose": ["8000", "9100"], "deploy": {"resources": {"reservations": {"devices": [{"driver": "nvidia", "device_ids": [gpu], "capabilities": ["gpu"]}]}}}, "healthcheck": {"test": ["CMD", "/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9100/healthz', timeout=2)"], "interval": "10s", "timeout": "3s", "start_period": "90s", "retries": 12}}
    services["hub"]["depends_on"][name] = {"condition": "service_healthy"}
    services[name]["environment"]["WORKER_STARTUP_TIMEOUT_S"] = str(args.worker_startup_timeout)
    services[name]["healthcheck"]["start_period"] = f"{args.worker_startup_timeout}s"
for service in services.values():
    # Docker client defaults can inject unrelated proxies into new containers.
    # This topology uses private peers and preverified offline model assets.
    service["environment"].update({name: "" for name in (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy",
    )})
    service["environment"].update({"NO_PROXY": "*", "no_proxy": "*"})
base["rooms"] = base["rooms"][:len(ids)]
if args.runtime_root:
    runtime = Path(args.runtime_root).resolve()
    project = Path.cwd()
    python_binaries = list((runtime / "python").glob("cpython-3.12.8-*/bin/python3.12"))
    if not python_binaries:
        parser.error("Install the pinned Python 3.12.8 into runtime/python before rendering this variant")
    for env in ("scope-env", "hub-env"):
        if not (runtime / env / "bin/python").exists():
            parser.error(f"Missing {runtime / env / 'bin/python'}")
    image = "longlive-runtime:0.1.0"
    for name, service in services.items():
        service["build"] = {"context": ".", "dockerfile": "deploy/Dockerfile.runtime"}
        service["image"] = image
        service["user"] = f"{os.getuid()}:{os.getgid()}"
        service["environment"].update({
            "HOME": "/tmp/longlive", "USER": "longlive", "LOGNAME": "longlive",
            "PYTHONDONTWRITEBYTECODE": "1",
            "TORCHINDUCTOR_CACHE_DIR": "/tmp/longlive/torchinductor",
            "TRITON_CACHE_DIR": "/tmp/longlive/triton",
        })
        service["volumes"].append(f"{runtime / 'python'}:{runtime / 'python'}:ro")
        if name == "hub":
            python = str(runtime / "hub-env/bin/python")
            service["volumes"].append(f"{runtime / 'hub-env'}:{runtime / 'hub-env'}:ro")
            service["command"] = [python, "-m", "uvicorn", "longlive.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--ws-max-size", "4096"]
        else:
            python = str(runtime / "scope-env/bin/python")
            service["volumes"].extend([f"{runtime / 'scope-env'}:{runtime / 'scope-env'}:ro", f"{project / 'vendor/scope/src'}:{project / 'vendor/scope/src'}:ro"])
            service["environment"].update({"DAYDREAM_SCOPE_MODELS_DIR": "/models", "DAYDREAM_SCOPE_LOGS_DIR": "/logs", "DAYDREAM_SCOPE_ASSETS_DIR": "/tmp/longlive/assets", "OMP_NUM_THREADS": "8", "MKL_NUM_THREADS": "8"})
            service["command"] = [python, "-m", "uvicorn", "supervisor:app", "--app-dir", "/opt/longlive", "--host", "0.0.0.0", "--port", "9100"]
            service["healthcheck"]["test"][1] = python
Path("configs/workers.local.yaml").write_text(yaml.safe_dump(base, allow_unicode=True, sort_keys=False))
Path("compose.scope.local.yaml").write_text(yaml.safe_dump({"name": "longlive-rooms", "services": services}, sort_keys=False))
print("Created configs/workers.local.yaml and compose.scope.local.yaml")
