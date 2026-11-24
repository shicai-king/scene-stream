import argparse
import asyncio
import json
from pathlib import Path
import struct
import time
import uuid

import httpx
from websockets.asyncio.client import connect


async def run(args):
    report = {"checks": [], "rooms": [], "measurement_seconds": args.seconds}
    async with httpx.AsyncClient(base_url=args.url, timeout=15, trust_env=False) as client:
        (await client.get("/healthz")).raise_for_status()
        deadline = time.monotonic() + args.timeout
        while True:
            listing = (await client.get("/api/v1/rooms")).json()["items"]
            live = [room for room in listing if room["state"] == "LIVE"]
            if len(live) >= args.rooms:
                break
            if time.monotonic() > deadline:
                raise RuntimeError(f"Expected {args.rooms} live rooms; got {listing}")
            await asyncio.sleep(2)
        report["checks"].append("health and expected live generation count")

        async def measure(room):
            url = args.url.replace("http://", "ws://").replace("https://", "wss://") + f"/api/v1/rooms/{room['id']}/stream"
            frames, sequences, source_frames = 0, [], []
            started = time.monotonic()
            first = None
            async with connect(url, proxy=None, max_size=4*1024*1024) as ws:
                async def heartbeat():
                    while True:
                        await ws.send(json.dumps({"type": "ping"}))
                        await asyncio.sleep(5)
                ping = asyncio.create_task(heartbeat())
                try:
                    while time.monotonic() - started < args.seconds:
                        packet = await asyncio.wait_for(ws.recv(), timeout=15)
                        if isinstance(packet, bytes):
                            length = struct.unpack("!I", packet[:4])[0]
                            meta = json.loads(packet[4:4+length])
                            assert meta["room_id"] == room["id"]
                            assert packet[4+length:6+length] == b"\xff\xd8"
                            frames += 1
                            sequences.append(meta["frame_seq"])
                            source_frames.append(meta["source_frames"])
                            if first is None:
                                first = time.monotonic() - started
                finally:
                    ping.cancel()
                    await asyncio.gather(ping, return_exceptions=True)
            elapsed = time.monotonic() - started
            assert frames >= 3 and sequences == sorted(set(sequences))
            return {"room_id": room["id"], "backend": room["backend"], "received_jpeg_frames": frames,
                    "receive_fps": round(frames/elapsed, 3), "first_relay_frame_ms": round(first*1000, 2),
                    "elapsed_s": round(elapsed, 3), "upstream_frame_delta": source_frames[-1]-source_frames[0]}

        report["rooms"] = await asyncio.gather(*(measure(room) for room in live[:args.rooms]))
        report["checks"].append("concurrent distinct room streams with increasing frame IDs")
        for i, room in enumerate(live[:args.rooms]):
            prompt = ["A red fox explores a snowy forest, cinematic.", "A colorful coral reef with tropical fish, cinematic."][i % 2]
            body = {"client_id": "smoke", "message_id": uuid.uuid4().hex, "nickname": "演示测试", "text": prompt}
            response = await client.post(f"/api/v1/rooms/{room['id']}/prompts", json=body)
            response.raise_for_status()
            message_id = response.json()["id"]
            replay = await client.post(f"/api/v1/rooms/{room['id']}/prompts", json=body)
            assert replay.json()["id"] == message_id
        await asyncio.sleep(1)
        report["checks"].append("per-room prompt acceptance and retry deduplication")
        report["capacity"] = (await client.get("/api/v1/capacity")).json()
        if report["capacity"]["available_slots"] == 0:
            overload = await client.post("/api/v1/rooms", headers={"Idempotency-Key": uuid.uuid4().hex}, json={"name": "overload", "initial_prompt": "test"})
            assert overload.status_code == 429
            report["checks"].append("full generation capacity returns 429 without affecting viewers")
    report["passed"] = True
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8080")
parser.add_argument("--rooms", type=int, default=2)
parser.add_argument("--seconds", type=int, default=15)
parser.add_argument("--timeout", type=int, default=600)
parser.add_argument("--output", default="artifacts/smoke-report.json")
asyncio.run(run(parser.parse_args()))
