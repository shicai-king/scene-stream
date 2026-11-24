from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import time
import uuid
from urllib.parse import urlsplit

from anyio import CancelScope
from fastapi import FastAPI, Header, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.utils import get_openapi

from .config import Settings, load_settings
from .manager import RoomManager
from .schemas import ApiError, Capacity, CreateRoom, PromptRequest, PromptView, RoomList, RoomView


def create_app(settings: Settings | None = None, manager: RoomManager | None = None):
    settings = settings or load_settings()
    manager = manager or RoomManager(settings)

    @asynccontextmanager
    async def lifespan(app):
        await manager.startup()
        yield
        await manager.shutdown()

    app = FastAPI(title="LongLive Shared Rooms", version="3.0.0", lifespan=lifespan,
                  description="Shared generation rooms, latest-wins prompts and multiplexed viewer streams. A sent prompt is not proof of visual adoption.")
    app.state.manager = manager

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex
        start = time.monotonic()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        if request.url.path.startswith("/api/") and request.method != "GET":
            manager.log.emit("http_request", request_id=request.state.request_id, method=request.method,
                             path=request.url.path, status=response.status_code, elapsed_ms=round((time.monotonic() - start) * 1000, 2))
        return response

    @app.exception_handler(ApiError)
    async def api_error(request, exc):
        return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message, "request_id": getattr(request.state, "request_id", None)}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(status_code=400, content={"error": {"code": "INVALID_REQUEST", "message": "请求字段或格式不正确", "request_id": getattr(request.state, "request_id", None)}})

    @app.get("/healthz")
    async def health():
        return {"status": "ok"}

    @app.get("/readyz")
    async def ready():
        if any(r.state == "LIVE" for r in manager.rooms.values()) or manager.capacity().available_slots:
            return {"status": "ready"}
        return JSONResponse(status_code=503, content={"status": "not_ready"})

    @app.get("/api/v1/info")
    async def info():
        return {"version": "0.1.0", "transport": "websocket-jpeg", "upstream_transport": "webrtc",
                "prompt_policy": "latest_wins", "max_prompt_length": 1500, "heartbeat_interval_s": settings.heartbeat_interval_s}

    @app.get("/api/v1/capacity", response_model=Capacity)
    async def capacity():
        return manager.capacity()

    @app.get("/api/v1/rooms", response_model=RoomList)
    async def list_rooms(limit: int = Query(default=50, ge=1, le=100), cursor: str | None = None):
        try:
            offset = int(cursor or "0")
            if offset < 0:
                raise ValueError()
        except ValueError:
            raise ApiError(400, "INVALID_CURSOR", "分页游标不正确")
        rooms = list(manager.rooms.values())
        end = offset + limit
        return RoomList(items=[manager.view(r) for r in rooms[offset:end]], next_cursor=str(end) if end < len(rooms) else None)

    @app.post("/api/v1/rooms", response_model=RoomView, status_code=201, responses={200: {"model": RoomView}})
    async def create_room(body: CreateRoom, response: Response, idempotency_key: str = Header(min_length=1, max_length=128)):
        view, created = await manager.create(body, idempotency_key)
        response.status_code = 201 if created else 200
        return view

    @app.get("/api/v1/rooms/{room_id}", response_model=RoomView)
    async def get_room(room_id: str):
        return manager.view(manager.room(room_id))

    @app.post("/api/v1/rooms/{room_id}/start", response_model=RoomView, status_code=202)
    async def start_room(room_id: str):
        return await manager.start(room_id)

    @app.post("/api/v1/rooms/{room_id}/stop", response_model=RoomView, status_code=202)
    async def stop_room(room_id: str):
        return await manager.stop(room_id)

    @app.post("/api/v1/rooms/{room_id}/prompts", response_model=PromptView, status_code=202)
    async def prompt(room_id: str, body: PromptRequest):
        return await manager.accept_prompt(room_id, body)

    @app.get("/api/v1/rooms/{room_id}/history", response_model=list[PromptView])
    async def history(room_id: str, after_seq: int = Query(default=0, ge=0)):
        return [m for m in manager.room(room_id).history if m.seq > after_seq]

    @app.websocket("/api/v1/rooms/{room_id}/stream")
    async def stream(websocket: WebSocket, room_id: str):
        origin = websocket.headers.get("origin")
        host = websocket.headers.get("host")
        if origin and urlsplit(origin).netloc != host and origin not in settings.allowed_origins:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        try:
            room, viewer = await manager.join(room_id)
        except ApiError as exc:
            await websocket.send_json({"type": "error", "message": exc.message})
            await websocket.close(code=1008)
            return
        first_reported = False

        async def send():
            while True:
                await viewer.notify.wait()
                viewer.notify.clear()
                if viewer.overflow:
                    await websocket.close(code=1013, reason="Event consumer too slow; reconnect for snapshot")
                    return
                while viewer.events:
                    await asyncio.wait_for(websocket.send_json(viewer.events.popleft()), timeout=settings.lease_ttl_s)
                packet, viewer.frame = viewer.frame, None
                if packet is not None:
                    await asyncio.wait_for(websocket.send_bytes(packet), timeout=settings.lease_ttl_s)

        async def receive():
            nonlocal first_reported
            while True:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=settings.lease_ttl_s)
                if len(raw) > 4096:
                    await websocket.close(code=1009)
                    return
                data = json.loads(raw)
                if not isinstance(data, dict) or data.get("type") != "ping":
                    await websocket.close(code=1008, reason="Expected heartbeat")
                    return
                viewer.last_seen = time.monotonic()
                if len(viewer.events) < 128:
                    viewer.events.append({"type": "pong", "client_time": data.get("client_time"), "room": manager.view(room).model_dump()})
                    viewer.notify.set()
                if not first_reported and isinstance(data.get("rendered_frames"), int) and data["rendered_frames"] > 0:
                    first_reported = True
                    manager.log.emit("client_first_frame", room_id=room_id, viewer_id=viewer.id,
                                     client_first_frame_ms=data.get("first_frame_ms"), rendered_frames=data["rendered_frames"])

        sender, receiver = asyncio.create_task(send()), asyncio.create_task(receive())
        viewer.notify.set()
        try:
            done, _ = await asyncio.wait([sender, receiver], return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (WebSocketDisconnect, TimeoutError, ValueError, RuntimeError):
            pass
        finally:
            # ASGI shutdown may repeatedly cancel awaits; finish viewer cleanup
            # before allowing that cancellation to propagate to the caller.
            with CancelScope(shield=True):
                for task in (sender, receiver):
                    task.cancel()
                await asyncio.gather(sender, receiver, return_exceptions=True)
                await manager.leave(room, viewer)
                try:
                    await websocket.close()
                except RuntimeError:
                    pass

    static = Path(settings.static_dir)
    if (static / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    async def index():
        if not (static / "index.html").is_file():
            return JSONResponse(status_code=503, content={"error": "Build the frontend with npm run build first"})
        return FileResponse(static / "index.html", headers={"Cache-Control": "no-cache"})

    def openapi():
        if app.openapi_schema is None:
            schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
            for path in schema["paths"].values():
                for operation in path.values():
                    if isinstance(operation, dict) and "responses" in operation:
                        operation["responses"].pop("422", None)
                        operation["responses"].setdefault("400", {"description": "Invalid request; error.code/message/request_id envelope"})
                        for status, description in [(404, "Room not found"), (409, "Invalid state or idempotency conflict"), (429, "Capacity exhausted")]:
                            operation["responses"].setdefault(str(status), {"description": description})
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = openapi
    return app
