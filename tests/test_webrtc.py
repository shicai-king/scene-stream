import asyncio

from longlive.config import Settings, WorkerConfig
from longlive.media import MockSource


async def test_real_webrtc_frames_and_parameters_channel():
    config = WorkerConfig(id="rtc-test", width=320, height=192)
    settings = Settings(workers=[config], auto_start=False, first_frame_timeout_s=10, connect_timeout_s=10)
    source = MockSource(config, settings, "before")
    frames, errors = [], []

    async def on_frame(jpeg, meta):
        frames.append((jpeg, meta))

    async def on_error(error):
        errors.append(error)

    try:
        await source.start(on_frame, on_error)
        await source.send_prompt("after")
        async with asyncio.timeout(5):
            while len(frames) < 4 or source.track.prompt != "after":
                await asyncio.sleep(.02)
        assert frames[0][0].startswith(b"\xff\xd8")
        assert frames[-1][1]["source_frames"] > frames[0][1]["source_frames"]
        assert source.pc.connectionState == source.sender.connectionState == "connected"
        assert not errors
    finally:
        assert await source.stop()
    assert source.pc.connectionState == source.sender.connectionState == "closed"
