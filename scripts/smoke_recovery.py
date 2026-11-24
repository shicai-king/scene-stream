"""Stop/reuse an explicitly selected room and verify another room keeps streaming."""
import argparse
import asyncio
import json
from pathlib import Path
import time

import httpx


async def run(args):
    async with httpx.AsyncClient(base_url=args.url, timeout=30, trust_env=False) as client:
        async def get_room(room_id):
            response = await client.get(f"/api/v1/rooms/{room_id}")
            response.raise_for_status()
            return response.json()

        async def wait_state(state):
            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline:
                room = await get_room(args.room)
                if room["state"] == state:
                    return room
                if room["state"] == "FAILED":
                    raise RuntimeError(room["error"])
                await asyncio.sleep(2)
            raise TimeoutError(f"Room did not reach {state}")

        initial = await get_room(args.room)
        assert initial["state"] == "LIVE"
        other = await get_room(args.other_room) if args.other_room else None
        started = time.monotonic()
        stopped = await client.post(f"/api/v1/rooms/{args.room}/stop")
        assert stopped.status_code == 202
        await wait_state("STOPPED")
        reset_s = time.monotonic() - started
        capacity = (await client.get("/api/v1/capacity")).json()
        assert capacity["available_slots"] >= 1 and capacity["quarantined_slots"] == 0
        if other:
            current_other = await get_room(args.other_room)
            assert current_other["state"] == "LIVE" and current_other["frame_seq"] > other["frame_seq"]
        started = time.monotonic()
        restarted = await client.post(f"/api/v1/rooms/{args.room}/start")
        assert restarted.status_code == 202
        final = await wait_state("LIVE")
        assert final["backend"] == initial["backend"] and final["frame_seq"] > 0
        report = {"passed": True, "backend": final["backend"], "room_id": args.room,
                  "reset_and_ready_s": round(reset_s, 2), "restart_to_live_s": round(time.monotonic()-started, 2),
                  "other_room_continued": bool(other), "capacity_after_reset": capacity}
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))


parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8080")
parser.add_argument("--room", required=True)
parser.add_argument("--other-room")
parser.add_argument("--timeout", type=int, default=900)
parser.add_argument("--output", default="artifacts/recovery.json")
asyncio.run(run(parser.parse_args()))
