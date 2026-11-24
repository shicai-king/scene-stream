from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from dataclasses import dataclass, field
import json
import struct
import time
import uuid
import httpx

from .config import RoomConfig, Settings, WorkerConfig
from .eventlog import EventLog, utc_now
from .media import make_source
from .schemas import ApiError, Capacity, CreateRoom, PromptRequest, PromptView, RoomView


@dataclass
class Worker:
    config: WorkerConfig
    state: str = "FREE"
    room_id: str | None = None


@dataclass
class Viewer:
    id: str
    events: deque = field(default_factory=deque)
    notify: asyncio.Event = field(default_factory=asyncio.Event)
    frame: bytes | None = None
    last_seen: float = field(default_factory=time.monotonic)
    overflow: bool = False


@dataclass
class Room:
    config: RoomConfig
    state: str = "STOPPED"
    worker: Worker | None = None
    source: object | None = None
    start_task: asyncio.Task | None = None
    close_task: asyncio.Task | None = None
    prompt_task: asyncio.Task | None = None
    prompt_notify: asyncio.Event = field(default_factory=asyncio.Event)
    pending: PromptView | None = None
    pending_deadline: float = 0
    sequence: int = 0
    event_sequence: int = 0
    history: deque = field(default_factory=deque)
    dedupe: OrderedDict = field(default_factory=OrderedDict)
    viewers: dict[str, Viewer] = field(default_factory=dict)
    current_prompt: str = ""
    frame_seq: int = 0
    source_frames: int = 0
    source_fps: float = 0
    first_frame_ms: float | None = None
    started: float = 0
    last_frame: bytes | None = None
    last_frame_time: float = 0
    error: str | None = None
    backend: str | None = None


class RoomManager:
    def __init__(self, settings: Settings, source_factory=make_source):
        self.settings = settings
        self.log = EventLog(settings.log_path)
        self.workers = [Worker(w) for w in settings.workers]
        self.rooms = {r.id: Room(r, current_prompt=r.initial_prompt) for r in settings.rooms}
        self.lock = asyncio.Lock()
        self.create_keys: OrderedDict = OrderedDict()
        self.source_factory = source_factory
        self.shutting_down = False
        self.monitor: asyncio.Task | None = None

    async def startup(self):
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            for worker in self.workers:
                if worker.config.backend == "scope":
                    try:
                        (await client.get(worker.config.endpoint.rstrip("/") + "/health")).raise_for_status()
                        if worker.config.control_endpoint:
                            (await client.get(worker.config.control_endpoint.rstrip("/") + "/healthz")).raise_for_status()
                    except httpx.HTTPError as exc:
                        worker.state = "QUARANTINED"
                        self.log.emit("worker_startup_probe_failed", worker_id=worker.config.id, error=str(exc))
        self.monitor = asyncio.create_task(self._monitor())
        if self.settings.auto_start:
            for room_id in self.rooms:
                try:
                    await self.start(room_id)
                except ApiError as exc:
                    self.rooms[room_id].error = exc.message
        self.log.emit("manager_started", workers=len(self.workers), rooms=len(self.rooms))

    def room(self, room_id: str) -> Room:
        if room_id not in self.rooms:
            raise ApiError(404, "ROOM_NOT_FOUND", "直播间不存在")
        return self.rooms[room_id]

    def view(self, room: Room) -> RoomView:
        return RoomView(id=room.config.id, name=room.config.name, color=room.config.color,
                        initial_prompt=room.config.initial_prompt, current_prompt=room.current_prompt,
                        state=room.state, backend=room.backend, viewers=len(room.viewers),
                        frame_seq=room.frame_seq, source_frames=room.source_frames,
                        source_fps=room.source_fps, first_frame_ms=room.first_frame_ms,
                        error=room.error, prompt_seq=room.sequence)

    def capacity(self) -> Capacity:
        states = [w.state for w in self.workers]
        active, reserved = states.count("BUSY"), states.count("RESERVED")
        healthy = sum(s in {"FREE", "RESERVED", "BUSY"} for s in states)
        limit = min(healthy, self.settings.active_limit or healthy)
        return Capacity(total_slots=healthy, active_sessions=active, reserved_sessions=reserved,
                        resetting_slots=states.count("RESETTING"), quarantined_slots=states.count("QUARANTINED"),
                        available_slots=max(0, min(states.count("FREE"), limit - active - reserved)), effective_limit=limit)

    def _allocate(self, room: Room):
        if self.shutting_down or self.capacity().available_slots <= 0:
            raise ApiError(429, "NO_CAPACITY", "生成资源已满，现有直播间仍可加入")
        worker = next(w for w in self.workers if w.state == "FREE")
        worker.state, worker.room_id = "RESERVED", room.config.id
        room.worker, room.state, room.backend = worker, "STARTING", worker.config.backend
        room.error, room.first_frame_ms = None, None
        room.frame_seq, room.source_frames, room.source_fps = 0, 0, 0
        room.last_frame, room.started = None, time.monotonic()
        room.current_prompt = room.config.initial_prompt
        room.start_task = asyncio.create_task(self._run(room, worker))
        self._event(room, "room_state", {"room": self.view(room).model_dump()})

    async def start(self, room_id: str):
        async with self.lock:
            room = self.room(room_id)
            if room.state in {"LIVE", "STARTING"}:
                return self.view(room)
            if room.state == "CLOSING":
                raise ApiError(409, "ROOM_CLOSING", "直播间正在回收资源")
            self._allocate(room)
            return self.view(room)

    async def create(self, request: CreateRoom, key: str):
        async with self.lock:
            body = request.model_dump()
            if key in self.create_keys:
                previous, room_id = self.create_keys[key]
                if previous != body:
                    raise ApiError(409, "IDEMPOTENCY_CONFLICT", "同一幂等键不能对应不同内容")
                return self.view(self.room(room_id)), False
            if len(self.rooms) >= self.settings.max_rooms:
                raise ApiError(429, "ROOM_LIMIT", "房间目录已达配置上限")
            room_id = "room-" + uuid.uuid4().hex[:12]
            room = Room(RoomConfig(id=room_id, name=request.name, initial_prompt=request.initial_prompt), current_prompt=request.initial_prompt)
            self._allocate(room)
            self.rooms[room_id] = room
            self.create_keys[key] = (body, room_id)
            if len(self.create_keys) > 4096:
                self.create_keys.popitem(last=False)
            self.log.emit("room_created", room_id=room_id, worker_id=room.worker.config.id)
            return self.view(room), True

    async def _run(self, room: Room, worker: Worker):
        source = self.source_factory(worker.config, self.settings, room.config.initial_prompt)
        room.source = source

        async def on_frame(jpeg, meta):
            if room.source is not source or room.state not in {"STARTING", "LIVE"}:
                return
            room.frame_seq += 1
            room.last_frame_time = time.monotonic()
            room.source_frames, room.source_fps = meta["source_frames"], meta["source_fps"]
            if room.first_frame_ms is None:
                room.first_frame_ms = round((time.monotonic() - room.started) * 1000, 2)
                self.log.emit("first_upstream_frame", room_id=room.config.id, worker_id=worker.config.id, elapsed_ms=room.first_frame_ms)
            header = json.dumps({"room_id": room.config.id, "frame_seq": room.frame_seq, "created_at": utc_now(), **meta}, separators=(",", ":")).encode()
            room.last_frame = struct.pack("!I", len(header)) + header + jpeg
            for viewer in room.viewers.values():
                viewer.frame = room.last_frame
                viewer.notify.set()

        async def on_error(message):
            if room.source is source and room.state in {"STARTING", "LIVE"}:
                room.error = "视频流意外中断，正在回收生成资源。"
                self.log.emit("upstream_failure", room_id=room.config.id, worker_id=worker.config.id, error=message)
                # Do not await shutdown from a task that shutdown itself must cancel.
                asyncio.create_task(self.stop(room.config.id, failed=True))

        try:
            await source.start(on_frame, on_error)
            async with self.lock:
                if room.state != "STARTING" or room.source is not source:
                    return
                room.state, worker.state = "LIVE", "BUSY"
                room.prompt_task = asyncio.create_task(self._deliver(room))
                self._event(room, "room_state", {"room": self.view(room).model_dump()})
                self.log.emit("room_live", room_id=room.config.id, worker_id=worker.config.id, backend=worker.config.backend)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            room.error = "生成服务启动失败，请检查部署日志。"
            self.log.emit("room_start_failed", room_id=room.config.id, error=f"{type(exc).__name__}: {exc}")
            asyncio.create_task(self.stop(room.config.id, failed=True))

    def _event(self, room: Room, kind: str, data: dict):
        room.event_sequence += 1
        event = {"type": kind, "event_seq": room.event_sequence, "room_id": room.config.id, **data}
        for viewer in room.viewers.values():
            if len(viewer.events) >= 128:
                viewer.overflow = True
            else:
                viewer.events.append(event)
            viewer.notify.set()

    async def accept_prompt(self, room_id: str, request: PromptRequest):
        async with self.lock:
            room = self.room(room_id)
            key = (request.client_id, request.message_id)
            body = request.model_dump()
            if key in room.dedupe:
                previous, message = room.dedupe[key]
                if previous != body:
                    raise ApiError(409, "IDEMPOTENCY_CONFLICT", "消息 ID 已用于不同内容")
                return message
            if room.state != "LIVE":
                raise ApiError(409, "ROOM_NOT_LIVE", "直播间尚未开始生成，请稍候")
            if room.pending:
                room.pending.status = "superseded"
                self._event(room, "prompt_status", {"prompt": room.pending.model_dump()})
                self.log.emit("prompt_superseded", room_id=room_id, seq=room.pending.seq)
            room.sequence += 1
            message = PromptView(id=uuid.uuid4().hex, seq=room.sequence, nickname=request.nickname, text=request.text, status="accepted", accepted_at=utc_now())
            room.history.append(message)
            while len(room.history) > self.settings.history_limit:
                room.history.popleft()
            room.dedupe[key] = (body, message)
            if len(room.dedupe) > 2048:
                room.dedupe.popitem(last=False)
            room.pending, room.pending_deadline = message, time.monotonic() + self.settings.prompt_ttl_s
            room.prompt_notify.set()
            self._event(room, "prompt", {"prompt": message.model_dump()})
            self.log.emit("prompt_accepted", room_id=room_id, seq=message.seq, message_id=message.id)
            return message

    async def _deliver(self, room: Room):
        try:
            while room.state == "LIVE":
                await room.prompt_notify.wait()
                await asyncio.sleep(self.settings.prompt_interval_s)
                async with self.lock:
                    message, deadline = room.pending, room.pending_deadline
                    room.pending = None
                    room.prompt_notify.clear()
                if message is None:
                    continue
                if time.monotonic() > deadline:
                    message.status = "expired"
                else:
                    try:
                        await room.source.send_prompt(message.text)
                        message.status, message.sent_at = "sent", utc_now()
                        room.current_prompt = message.text
                    except Exception as exc:
                        message.status = "failed"
                        self.log.emit("prompt_delivery_failed", room_id=room.config.id, seq=message.seq, error=str(exc))
                self._event(room, "prompt_status", {"prompt": message.model_dump()})
                self.log.emit("prompt_" + message.status, room_id=room.config.id, seq=message.seq)
        except asyncio.CancelledError:
            raise

    async def join(self, room_id: str):
        async with self.lock:
            room = self.room(room_id)
            if len(room.viewers) >= self.settings.max_viewers_per_room:
                raise ApiError(429, "VIEWER_LIMIT", "直播间观看人数已达配置上限")
            viewer = Viewer(uuid.uuid4().hex)
            room.viewers[viewer.id] = viewer
            viewer.frame = room.last_frame
            viewer.events.append({"type": "snapshot", "room": self.view(room).model_dump(), "history": [m.model_dump() for m in room.history], "viewer_id": viewer.id, "heartbeat_interval_s": self.settings.heartbeat_interval_s, "event_seq": room.event_sequence})
            self._event(room, "viewers", {"count": len(room.viewers)})
            self.log.emit("viewer_joined", room_id=room_id, viewer_id=viewer.id)
            return room, viewer

    async def leave(self, room: Room, viewer: Viewer):
        async with self.lock:
            room.viewers.pop(viewer.id, None)
            self._event(room, "viewers", {"count": len(room.viewers)})
            self.log.emit("viewer_left", room_id=room.config.id, viewer_id=viewer.id)

    async def stop(self, room_id: str, failed=False):
        async with self.lock:
            room = self.room(room_id)
            if room.state in {"STOPPED", "FAILED", "CLOSING"}:
                return self.view(room)
            room.state = "CLOSING"
            if room.worker:
                room.worker.state = "RESETTING"
            room.close_task = asyncio.create_task(self._cleanup(room, failed))
            self._event(room, "room_state", {"room": self.view(room).model_dump()})
            return self.view(room)

    async def _cleanup(self, room: Room, failed: bool):
        worker, source = room.worker, room.source
        for task in (room.start_task, room.prompt_task):
            if task and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        if room.pending:
            room.pending.status = "failed"
            self._event(room, "prompt_status", {"prompt": room.pending.model_dump()})
            room.pending = None
        safe = False
        try:
            # If start was cancelled before it created a source, nothing used the worker.
            safe = True if source is None else await source.stop()
        except Exception as exc:
            room.error = "资源恢复失败，已隔离对应生成实例。"
            self.log.emit("worker_recovery_failed", room_id=room.config.id, error=f"{type(exc).__name__}: {exc}")
        async with self.lock:
            if worker:
                worker.state = "FREE" if safe else "QUARANTINED"
                worker.room_id = None
            room.worker, room.source, room.last_frame = None, None, None
            room.state = "FAILED" if failed or not safe else "STOPPED"
            if not safe and not room.error:
                room.error = "Worker state could not be safely reset; worker quarantined"
            self._event(room, "room_state", {"room": self.view(room).model_dump()})
            self.log.emit("room_closed", room_id=room.config.id, state=room.state, worker_state=worker.state if worker else None)

    async def _monitor(self):
        while True:
            await asyncio.sleep(5)
            for room in self.rooms.values():
                if room.state == "LIVE":
                    self.log.emit("stream_stats", room_id=room.config.id, source_frames=room.source_frames, source_fps=room.source_fps, relay_frames=room.frame_seq, viewers=len(room.viewers))
                    if time.monotonic() - room.last_frame_time > self.settings.media_stall_timeout_s:
                        room.error = "Upstream media stopped producing frames"
                        await self.stop(room.config.id, failed=True)

    async def shutdown(self):
        self.shutting_down = True
        if self.monitor:
            self.monitor.cancel()
            await asyncio.gather(self.monitor, return_exceptions=True)
        for room_id in list(self.rooms):
            await self.stop(room_id)
        tasks = [r.close_task for r in self.rooms.values() if r.close_task]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.log.close()
