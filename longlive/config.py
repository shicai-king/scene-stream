from __future__ import annotations

import os
import math
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, model_validator
import yaml


class WorkerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    backend: str = "mock"
    endpoint: str | None = None
    control_endpoint: str | None = None
    pipeline_id: str = "longlive"
    launch_mode: str = "managed"
    width: int = Field(default=576, ge=128, le=2048, multiple_of=16)
    height: int = Field(default=320, ge=128, le=2048, multiple_of=16)
    seed: int = 42
    load_params: dict = Field(default_factory=dict)
    runtime_params: dict = Field(default_factory=dict)
    fail_reset: bool = False
    first_frame_delay_s: float = 0

    @model_validator(mode="after")
    def validate_backend(self):
        if self.backend not in {"mock", "scope"}:
            raise ValueError("backend must be mock or scope")
        if self.launch_mode not in {"managed", "external"}:
            raise ValueError("launch_mode must be managed or external")
        if self.backend == "scope" and not self.endpoint:
            raise ValueError("Scope requires endpoint")
        if self.backend == "scope" and self.launch_mode == "managed" and not self.control_endpoint:
            raise ValueError("Managed Scope requires an owned-process control_endpoint")
        return self


class RoomConfig(BaseModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=60)
    initial_prompt: str = Field(min_length=1, max_length=1500)
    color: str = "#a78bfa"


class Settings(BaseModel):
    workers: list[WorkerConfig]
    rooms: list[RoomConfig] = Field(default_factory=list)
    auto_start: bool = True
    active_limit: int | None = Field(default=None, ge=1)
    heartbeat_interval_s: float = 5
    lease_ttl_s: float = 25
    connect_timeout_s: float = 45
    first_frame_timeout_s: float = 180
    media_stall_timeout_s: float = 45
    reset_timeout_s: float = 30
    worker_startup_timeout_s: float = 90
    pipeline_ready_timeout_s: float = 600
    prompt_interval_s: float = 0.5
    prompt_ttl_s: float = 20
    max_viewers_per_room: int = Field(default=16, ge=1, le=100)
    media_fps: int = Field(default=24, ge=1, le=60)
    jpeg_quality: int = Field(default=78, ge=20, le=95)
    history_limit: int = Field(default=150, ge=1, le=1000)
    max_rooms: int = Field(default=100, ge=1, le=10000)
    static_dir: str = "dist"
    log_path: str | None = None
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])

    @model_validator(mode="after")
    def unique_ids(self):
        if len({w.id for w in self.workers}) != len(self.workers):
            raise ValueError("Duplicate worker ID")
        if len({r.id for r in self.rooms}) != len(self.rooms):
            raise ValueError("Duplicate room ID")
        for field in ("heartbeat_interval_s", "lease_ttl_s", "connect_timeout_s", "first_frame_timeout_s", "media_stall_timeout_s", "reset_timeout_s", "worker_startup_timeout_s", "pipeline_ready_timeout_s", "prompt_interval_s", "prompt_ttl_s"):
            value = getattr(self, field)
            if value <= 0 or not math.isfinite(value):
                raise ValueError(f"{field} must be positive and finite")
        if self.heartbeat_interval_s >= self.lease_ttl_s:
            raise ValueError("Heartbeat interval must be shorter than viewer lease TTL")
        return self


def load_settings() -> Settings:
    path = os.getenv("WORKER_CONFIG_PATH")
    data = yaml.safe_load(Path(path).read_text()) if path else {}
    if not isinstance(data, dict):
        raise ValueError("Worker configuration must be an object")
    data = dict(data)
    data.pop("schema_version", None)
    if "workers" not in data:
        count = int(os.getenv("MOCK_WORKER_COUNT", "2"))
        if not 1 <= count <= 32:
            raise ValueError("MOCK_WORKER_COUNT must be 1..32")
        data["workers"] = [{"id": f"mock-{n+1}", "backend": "mock"} for n in range(count)]
    if "rooms" not in data:
        data["rooms"] = [
            {"id": "night-walk", "name": "雨夜漫游", "color": "#a78bfa", "initial_prompt": "A cinematic tracking shot through a neon-lit city at night, rain reflecting colorful lights, smooth camera motion."},
            {"id": "floating-garden", "name": "漂浮花园", "color": "#64d8bb", "initial_prompt": "A dreamy floating garden above the clouds, flowers swaying in the breeze, golden sunlight, cinematic slow camera movement."},
        ][:len(data["workers"])]
    settings = Settings(**data)
    for field in ("heartbeat_interval_s", "lease_ttl_s", "connect_timeout_s", "first_frame_timeout_s", "reset_timeout_s", "worker_startup_timeout_s", "pipeline_ready_timeout_s", "prompt_interval_s", "prompt_ttl_s"):
        if field.upper() in os.environ:
            setattr(settings, field, float(os.environ[field.upper()]))
    for env, field in {"SESSION_CONNECT_TIMEOUT_S": "connect_timeout_s", "RESET_RPC_TIMEOUT_S": "reset_timeout_s", "MEDIA_STALL_TIMEOUT_S": "media_stall_timeout_s"}.items():
        if env in os.environ:
            setattr(settings, field, float(os.environ[env]))
    if "SESSION_ACTIVE_LIMIT" in os.environ:
        settings.active_limit = int(os.environ["SESSION_ACTIVE_LIMIT"]) if os.environ["SESSION_ACTIVE_LIMIT"].strip() else None
    if "AUTO_START" in os.environ:
        settings.auto_start = os.environ["AUTO_START"].lower() == "true"
    settings.log_path = os.getenv("LOG_PATH", settings.log_path)
    return Settings.model_validate(settings.model_dump())
