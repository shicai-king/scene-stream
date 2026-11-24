import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from longlive.config import Settings, WorkerConfig
from longlive.media import ScopeSource


async def source_with_fake_signaling(delay):
    worker = WorkerConfig(id="test", backend="scope", endpoint="http://scope.invalid", launch_mode="external")
    source = ScopeSource(worker, Settings(workers=[worker], connect_timeout_s=.1, first_frame_timeout_s=.3), "test")
    await source.pc.close()
    await source.http.aclose()

    async def negotiate(*args, **kwargs):
        await asyncio.sleep(delay)

    async def offer(*args, **kwargs):
        await asyncio.sleep(delay)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"sessionId": "test", "type": "answer", "sdp": "v=0\r\n"})

    source.pc = SimpleNamespace(createOffer=AsyncMock(), setLocalDescription=negotiate,
                                localDescription=SimpleNamespace(type="offer", sdp="test"), setRemoteDescription=AsyncMock())
    source.http = SimpleNamespace(post=offer)
    source.load_pipeline = AsyncMock()
    source.channel_open.set()
    return source


async def test_connection_deadline_covers_cumulative_signaling_time():
    source = await source_with_fake_signaling(.06)
    source.first_frame.set()
    with pytest.raises(TimeoutError):
        await source.start(AsyncMock(), AsyncMock())


async def test_first_frame_has_its_own_deadline_after_connection():
    source = await source_with_fake_signaling(0)

    async def frame_later():
        await asyncio.sleep(.15)
        source.first_frame.set()

    task = asyncio.create_task(frame_later())
    await source.start(AsyncMock(), AsyncMock())
    await task
