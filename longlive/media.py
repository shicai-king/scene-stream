"""One upstream WebRTC source per room; bounded JPEG fanout is handled by the hub."""
from __future__ import annotations

import asyncio
from collections import deque
from fractions import Fraction
import io
import json
import math
import time
from typing import Awaitable, Callable

import av
import httpx
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from aiortc.mediastreams import MediaStreamError

from .config import Settings, WorkerConfig

FrameCallback = Callable[[bytes, dict], Awaitable[None]]
ErrorCallback = Callable[[str], Awaitable[None]]


class WebRTCSource:
    def __init__(self, config: WorkerConfig, settings: Settings, prompt: str):
        self.config, self.settings, self.prompt = config, settings, prompt
        self.pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self.channel = self.pc.createDataChannel("parameters", ordered=True)
        self.channel_open = asyncio.Event()
        self.first_frame = asyncio.Event()
        self.closing = False
        self.reader: asyncio.Task | None = None
        self.frames = 0
        self.frame_times = deque(maxlen=240)
        self.on_frame: FrameCallback | None = None
        self.on_error: ErrorCallback | None = None
        self.pc.addTransceiver("video", direction="recvonly")

        @self.channel.on("open")
        def on_open():
            self.channel_open.set()

        @self.channel.on("message")
        def on_message(message):
            try:
                data = json.loads(message)
                if data.get("type") == "stream_stopped" and not self.closing and self.on_error:
                    asyncio.create_task(self.on_error(str(data.get("error_message", "Upstream stream stopped"))))
            except (ValueError, TypeError):
                pass

        @self.pc.on("track")
        def on_track(track):
            if track.kind == "video":
                self.reader = asyncio.create_task(self._read(track))

    async def _read(self, track):
        next_send = 0.0
        try:
            while not self.closing:
                frame = await track.recv()
                now = time.monotonic()
                self.frames += 1
                self.frame_times.append(now)
                if now < next_send:
                    continue
                next_send = max(next_send + 1 / self.settings.media_fps, now)
                jpeg = await asyncio.to_thread(self._encode, frame)
                fps = ((len(self.frame_times) - 1) / (now - self.frame_times[0])) if len(self.frame_times) > 1 and now > self.frame_times[0] else 0
                if self.on_frame:
                    await self.on_frame(jpeg, {"source_frames": self.frames, "source_fps": round(fps, 2), "width": frame.width, "height": frame.height})
                self.first_frame.set()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self.closing and self.on_error:
                await self.on_error(f"Media stream ended: {type(exc).__name__}: {exc}")

    def _encode(self, frame):
        output = io.BytesIO()
        frame.to_image().save(output, format="JPEG", quality=self.settings.jpeg_quality)
        return output.getvalue()

    async def send_prompt(self, text: str):
        if self.channel.readyState != "open":
            raise ConnectionError("Upstream parameter channel is not open")
        if self.channel.bufferedAmount > 65536:
            raise ConnectionError("Upstream parameter channel is congested")
        self.channel.send(json.dumps({"prompts": [{"text": text, "weight": 1.0}]}))

    async def close_peer(self):
        self.closing = True
        if self.reader:
            self.reader.cancel()
            await asyncio.gather(self.reader, return_exceptions=True)
        await self.pc.close()


class MockTrack(VideoStreamTrack):
    """Visible diagnostic pattern, real encoded WebRTC video, no GPU."""
    def __init__(self, config: WorkerConfig, prompt: str):
        super().__init__()
        self.config, self.prompt = config, prompt
        self.started = None
        self.index = 0
        try:
            self.font = ImageFont.truetype("DejaVuSans.ttf", 15)
        except OSError:
            self.font = ImageFont.load_default()

    async def recv(self):
        if self.started is None:
            await asyncio.sleep(self.config.first_frame_delay_s)
            self.started = time.monotonic()
        await asyncio.sleep(max(0, self.started + self.index / 24 - time.monotonic()))
        width, height = self.config.width, self.config.height
        x, y = np.meshgrid(np.linspace(0, 1, width), np.linspace(0, 1, height))
        t = self.index / 24
        offset = sum(self.config.id.encode()) % 30
        wave = np.sin(x * 9 + y * 4 + t + offset) * 0.5 + 0.5
        pixels = np.stack([25 + 70 * wave, 20 + 100 * y, 70 + 110 * (1 - wave)], axis=2).astype(np.uint8)
        picture = Image.fromarray(pixels)
        draw = ImageDraw.Draw(picture)
        for i in range(9):
            cx = int((i / 8 + math.sin(t * 0.3 + i) * 0.05) * width)
            cy = int((0.5 + math.sin(t * 0.7 + i) * 0.22) * height)
            draw.ellipse((cx - 15, cy - 15, cx + 15, cy + 15), outline=(150, 210, 255), width=2)
        draw.rectangle((0, height - 76, width, height), fill=(15, 16, 30))
        draw.text((18, height - 66), f"MOCK / {self.config.id} / FRAME {self.index}", font=self.font, fill="white")
        draw.text((18, height - 35), self.prompt[:65], font=self.font, fill=(200, 200, 235))
        frame = av.VideoFrame.from_image(picture)
        frame.pts, frame.time_base = int(self.index * 90000 / 24), Fraction(1, 90000)
        self.index += 1
        return frame


class MockSource(WebRTCSource):
    def __init__(self, *args):
        super().__init__(*args)
        self.sender = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self.track = MockTrack(self.config, self.prompt)

        @self.sender.on("datachannel")
        def channel_created(channel):
            @channel.on("message")
            def prompt_received(message):
                data = json.loads(message)
                self.track.prompt = data["prompts"][0]["text"]

    async def start(self, on_frame: FrameCallback, on_error: ErrorCallback):
        self.on_frame, self.on_error = on_frame, on_error
        async with asyncio.timeout(self.settings.connect_timeout_s):
            await self.pc.setLocalDescription(await self.pc.createOffer())
            await self.sender.setRemoteDescription(self.pc.localDescription)
            self.sender.addTrack(self.track)
            await self.sender.setLocalDescription(await self.sender.createAnswer())
            await self.pc.setRemoteDescription(self.sender.localDescription)
            await self.channel_open.wait()
        await asyncio.wait_for(self.first_frame.wait(), self.settings.first_frame_timeout_s)

    async def stop(self) -> bool:
        await self.close_peer()
        self.track.stop()
        await self.sender.close()
        return not self.config.fail_reset


class ScopeSource(WebRTCSource):
    def __init__(self, *args):
        super().__init__(*args)
        self.http = httpx.AsyncClient(base_url=self.config.endpoint.rstrip("/"), timeout=30, trust_env=False)
        self.upstream_id = None

    async def reset_owned_process(self):
        if self.config.launch_mode != "managed" or not self.config.control_endpoint:
            return False
        async with httpx.AsyncClient(timeout=self.settings.worker_startup_timeout_s + self.settings.reset_timeout_s, trust_env=False) as client:
            response = await client.post(self.config.control_endpoint.rstrip("/") + "/control/reset")
            response.raise_for_status()
            data = response.json()
            if not data.get("process_replaced") or not data.get("generation"):
                raise RuntimeError("Supervisor did not verify process replacement")
        return True

    async def load_pipeline(self):
        params = {"height": self.config.height, "width": self.config.width, "base_seed": self.config.seed, "quantization": None, "vace_enabled": False, **self.config.load_params}
        response = await self.http.post("/api/v1/pipeline/load", json={"pipeline_ids": [self.config.pipeline_id], "load_params": params})
        response.raise_for_status()
        deadline = time.monotonic() + self.settings.pipeline_ready_timeout_s
        while time.monotonic() < deadline:
            response = await self.http.get("/api/v1/pipeline/status")
            response.raise_for_status()
            data = response.json()
            if data.get("status") == "loaded":
                return
            if data.get("status") == "error":
                raise RuntimeError(str(data.get("error", "Pipeline load failed")))
            await asyncio.sleep(1)
        raise TimeoutError("Pipeline loading deadline exceeded")

    async def start(self, on_frame: FrameCallback, on_error: ErrorCallback):
        self.on_frame, self.on_error = on_frame, on_error
        if self.config.launch_mode == "managed":
            await self.reset_owned_process()
        await self.load_pipeline()
        parameters = {"pipeline_ids": [self.config.pipeline_id], "input_mode": "text", "manage_cache": True, "denoising_step_list": [1000, 750, 500, 250], **self.config.runtime_params, "prompts": [{"text": self.prompt, "weight": 1.0}]}
        async with asyncio.timeout(self.settings.connect_timeout_s):
            await self.pc.setLocalDescription(await self.pc.createOffer())
            response = await self.http.post("/api/v1/webrtc/offer", json={"type": self.pc.localDescription.type, "sdp": self.pc.localDescription.sdp, "initialParameters": parameters}, timeout=self.settings.connect_timeout_s)
            response.raise_for_status()
            answer = response.json()
            self.upstream_id = answer["sessionId"]
            await self.pc.setRemoteDescription(RTCSessionDescription(type=answer["type"], sdp=answer["sdp"]))
            await self.channel_open.wait()
        await asyncio.wait_for(self.first_frame.wait(), self.settings.first_frame_timeout_s)

    async def stop(self) -> bool:
        await self.close_peer()
        try:
            if self.upstream_id:
                try:
                    await self.http.delete(f"/api/v1/webrtc/offer/{self.upstream_id}", timeout=self.settings.reset_timeout_s)
                except httpx.HTTPError:
                    pass  # Owned process replacement below is the isolation boundary.
            if not await self.reset_owned_process():
                return False  # Never recycle external workers on HTTP health alone.
            await self.load_pipeline()
            return True
        finally:
            await self.http.aclose()


def make_source(config: WorkerConfig, settings: Settings, prompt: str):
    return (MockSource if config.backend == "mock" else ScopeSource)(config, settings, prompt)
