from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CreateRoom(StrictModel):
    name: str = Field(min_length=1, max_length=60)
    initial_prompt: str = Field(min_length=1, max_length=1500)


class PromptRequest(StrictModel):
    client_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    message_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    nickname: str = Field(default="观众", min_length=1, max_length=24)
    text: str = Field(min_length=1, max_length=1500)


class PromptView(BaseModel):
    id: str
    seq: int
    nickname: str
    text: str
    status: Literal["accepted", "superseded", "sent", "expired", "failed"]
    accepted_at: str
    sent_at: str | None = None


class RoomView(BaseModel):
    id: str
    name: str
    color: str
    initial_prompt: str
    current_prompt: str
    state: str
    backend: str | None
    viewers: int
    frame_seq: int
    source_frames: int
    source_fps: float
    first_frame_ms: float | None
    error: str | None
    prompt_seq: int


class RoomList(BaseModel):
    items: list[RoomView]
    next_cursor: str | None


class Capacity(BaseModel):
    total_slots: int
    active_sessions: int
    reserved_sessions: int
    resetting_slots: int
    quarantined_slots: int
    available_slots: int
    effective_limit: int
    policy: str = "reject"


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message
