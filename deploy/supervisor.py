"""Own exactly one child Scope process. No Docker socket or host process access."""
import asyncio
from contextlib import asynccontextmanager
import os
import signal
import sys
import time
import uuid

import httpx
from fastapi import FastAPI, HTTPException

child: asyncio.subprocess.Process | None = None
generation: str | None = None
lock = asyncio.Lock()


async def terminate_owned():
    global child
    if child is None or child.returncode is not None:
        return
    # This PID/process group is only the direct child created below.
    os.killpg(child.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(child.wait(), timeout=20)
    except TimeoutError:
        os.killpg(child.pid, signal.SIGKILL)
        await asyncio.wait_for(child.wait(), timeout=10)


async def spawn():
    global child, generation
    generation = uuid.uuid4().hex
    child = await asyncio.create_subprocess_exec(
        sys.executable, "/opt/longlive/scope_bootstrap.py", "--host", "0.0.0.0", "--port", "8000", "-N",
        start_new_session=True,
    )
    deadline = time.monotonic() + float(os.getenv("WORKER_STARTUP_TIMEOUT_S", "90"))
    async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
        while time.monotonic() < deadline:
            if child.returncode is not None:
                raise RuntimeError(f"Scope exited with {child.returncode}")
            try:
                response = await client.get("http://127.0.0.1:8000/health")
                if response.is_success:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1)
    raise TimeoutError("Scope HTTP startup timed out")


@asynccontextmanager
async def lifespan(app):
    try:
        await spawn()
        yield
    finally:
        await terminate_owned()


app = FastAPI(lifespan=lifespan)


@app.get("/healthz")
async def health():
    if child is None or child.returncode is not None:
        raise HTTPException(503, "Owned Scope process is not running")
    return {"status": "running", "generation": generation}


@app.post("/control/reset")
async def reset():
    async with lock:
        previous = generation
        try:
            await terminate_owned()
            await spawn()
        except Exception as exc:
            await terminate_owned()
            raise HTTPException(503, str(exc)) from exc
        return {"process_replaced": previous != generation, "generation": generation}
