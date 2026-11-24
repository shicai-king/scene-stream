import asyncio
import struct
import json
import pytest

from longlive.config import Settings, WorkerConfig
from longlive.manager import RoomManager
from longlive.schemas import ApiError, CreateRoom, PromptRequest


class FakeSource:
    instances = []

    def __init__(self, config, settings, prompt):
        self.config, self.settings = config, settings
        self.sent, self.stopped = [], False
        self.instances.append(self)

    async def start(self, on_frame, on_error):
        await asyncio.sleep(self.config.first_frame_delay_s)
        await on_frame(b"jpeg", {"source_frames": 1, "source_fps": 24, "width": 576, "height": 320})

    async def send_prompt(self, text):
        self.sent.append(text)

    async def stop(self):
        self.stopped = True
        return not self.config.fail_reset


def settings(count=2, **overrides):
    return Settings(workers=[WorkerConfig(id=f"w-{i}") for i in range(count)], rooms=[], auto_start=False, prompt_interval_s=0.025, **overrides)


async def settle(predicate, seconds=2):
    async with asyncio.timeout(seconds):
        while not predicate():
            await asyncio.sleep(.005)


async def create_live(manager, key="one"):
    view, _ = await manager.create(CreateRoom(name=key, initial_prompt="initial"), key)
    await settle(lambda: manager.room(view.id).state == "LIVE")
    return manager.room(view.id)


@pytest.mark.parametrize("count", [1, 2, 4])
async def test_atomic_capacity_and_idempotency(count):
    manager = RoomManager(settings(count), FakeSource)
    results = await asyncio.gather(*(manager.create(CreateRoom(name=f"room-{i}", initial_prompt="test"), str(i)) for i in range(count + 12)), return_exceptions=True)
    accepted = [r for r in results if not isinstance(r, Exception)]
    assert len(accepted) == count
    assert all(r.status == 429 for r in results if isinstance(r, ApiError))
    assert len({w.room_id for w in manager.workers}) == count
    replay, created = await manager.create(CreateRoom(name="room-0", initial_prompt="test"), "0")
    assert not created and replay.id == accepted[0][0].id
    with pytest.raises(ApiError) as exc:
        await manager.create(CreateRoom(name="changed", initial_prompt="test"), "0")
    assert exc.value.status == 409
    await manager.shutdown()
    assert all(w.state == "FREE" for w in manager.workers)


async def test_viewers_share_one_source_and_leaving_keeps_generation():
    manager = RoomManager(settings(), FakeSource)
    room = await create_live(manager)
    _, a = await manager.join(room.config.id)
    _, b = await manager.join(room.config.id)
    assert a.frame == b.frame and a.frame is not None
    header_size = struct.unpack("!I", a.frame[:4])[0]
    assert json.loads(a.frame[4:4+header_size])["room_id"] == room.config.id
    assert manager.capacity().active_sessions == 1
    await manager.leave(room, a)
    assert room.state == "LIVE" and len(room.viewers) == 1
    await manager.leave(room, b)
    assert room.state == "LIVE" and manager.capacity().active_sessions == 1
    await manager.shutdown()


async def test_latest_wins_all_messages_broadcast_and_retry_does_not_resurrect():
    manager = RoomManager(settings(), FakeSource)
    room = await create_live(manager)
    _, viewer = await manager.join(room.config.id)
    requests = [PromptRequest(client_id=f"client-{i%2}", message_id=f"m-{i}", text=f"idea-{i}") for i in range(20)]
    prompts = await asyncio.gather(*(manager.accept_prompt(room.config.id, p) for p in requests))
    await settle(lambda: prompts[-1].status == "sent")
    assert room.source.sent == ["idea-19"]
    assert all(p.status == "superseded" for p in prompts[:-1])
    assert [p.seq for p in prompts] == list(range(1, 21))
    assert len([e for e in viewer.events if e["type"] == "prompt"]) == 20
    assert (await manager.accept_prompt(room.config.id, requests[0])).status == "superseded"
    await asyncio.sleep(.04)
    assert room.source.sent == ["idea-19"]
    conflicting = requests[0].model_copy(update={"text": "different"})
    with pytest.raises(ApiError) as exc:
        await manager.accept_prompt(room.config.id, conflicting)
    assert exc.value.status == 409
    await manager.shutdown()


async def test_cross_room_prompt_isolation():
    manager = RoomManager(settings(), FakeSource)
    a, b = await create_live(manager, "a"), await create_live(manager, "b")
    await manager.accept_prompt(a.config.id, PromptRequest(client_id="same", message_id="same", text="forest"))
    await manager.accept_prompt(b.config.id, PromptRequest(client_id="same", message_id="same", text="ocean"))
    await settle(lambda: a.current_prompt == "forest" and b.current_prompt == "ocean")
    assert a.source.sent == ["forest"] and b.source.sent == ["ocean"]
    assert a.sequence == b.sequence == 1
    await manager.shutdown()


async def test_reset_failure_quarantines_worker_and_repeated_stop_is_safe():
    config = settings(1)
    config.workers[0].fail_reset = True
    manager = RoomManager(config, FakeSource)
    room = await create_live(manager)
    await manager.stop(room.config.id)
    await manager.stop(room.config.id)
    await settle(lambda: room.state == "FAILED")
    assert manager.workers[0].state == "QUARANTINED"
    assert manager.capacity().available_slots == 0
    with pytest.raises(ApiError):
        await manager.create(CreateRoom(name="next", initial_prompt="next"), "next")
    await manager.shutdown()


async def test_close_during_start_does_not_reactivate_old_source():
    config = settings(1)
    config.workers[0].first_frame_delay_s = 5
    manager = RoomManager(config, FakeSource)
    view, _ = await manager.create(CreateRoom(name="test", initial_prompt="test"), "test")
    await asyncio.sleep(.01)
    source = manager.room(view.id).source
    await manager.stop(view.id)
    await settle(lambda: manager.room(view.id).state == "STOPPED")
    assert source.stopped and manager.workers[0].state == "FREE"
    assert manager.room(view.id).frame_seq == 0
    await manager.shutdown()


async def test_prompt_expiry_and_global_capacity_limit():
    manager = RoomManager(settings(4, active_limit=1, prompt_ttl_s=.001), FakeSource)
    room = await create_live(manager)
    assert manager.capacity().available_slots == 0
    message = await manager.accept_prompt(room.config.id, PromptRequest(client_id="test", message_id="test", text="late"))
    await settle(lambda: message.status == "expired")
    assert room.source.sent == []
    await manager.shutdown()
