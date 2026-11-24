# Shared AI livestream rooms — implementation specification V4

This is the current specification. It supersedes the independent-browser session semantics in the original root-level Markdown and OpenAPI v2. The original files remain as design history.

## User experience

- A sidebar lists rooms; selecting a room joins its existing stream.
- The room's viewers see the same generated content, with normal network timing differences.
- Anyone able to access this private demo may submit a prompt and nickname. Every accepted prompt appears in the room's chat and optional moving danmaku overlay.
- Default configuration starts two rooms. Worker count and optional generation limit are configurable. Viewing a room consumes no new generation slot.
- The newest unsent prompt replaces the previous pending prompt. A single server-side data channel sends the selected prompt to the model. Already-sent prompts cannot be reliably revoked.
- Switching rooms or closing a browser only closes that viewer connection. Rooms continue until explicitly stopped or an upstream failure triggers cleanup.
- Course demo: no account system, billing, public hosting, audio or automatic narrative LLM. State and bounded chat history are in memory. A manager restart starts fresh generation.

## Architecture

```text
Browser(s) ── HTTP + one multiplexed WebSocket ── FastAPI room hub
                                                     │
                                   one WebRTC peer per active room
                                                     │
                                          owned Scope worker
                                                     │
                                              GPU generation
```

Scope-to-hub WebRTC runs within the private Docker network with no external ICE servers. The hub decodes the one upstream video track, JPEG-encodes a bounded-rate preview, and shares the same packet with viewers. Browser media and control use the same TCP entrypoint, allowing ordinary SSH port forwarding. This deliberately replaces the old requirement for browser-to-Worker WebRTC; it is documented as `websocket-jpeg` in `/api/v1/info`.

Text generation uses an explicit Scope graph connecting the loaded pipeline's video output to a sink. No camera or synthetic input video is required. This selects the pinned release's output-only track instead of its legacy track that waits for incoming video.

The tradeoff is CPU JPEG encoding and more bandwidth than interframe video codecs. Browser display rate, hub source receive rate, and model output rate are separate metrics. The hub keeps a single newest frame per viewer, so a slow viewer does not accumulate an old video backlog or block other viewers.

## Objects and states

- Room: stable ID, display name, configured initial prompt, current sent prompt, event sequence and bounded history.
- Worker: one generation slot; `FREE → RESERVED → BUSY → RESETTING → FREE`; unverified cleanup leads to `QUARANTINED`.
- Viewer: one WebSocket, bounded event queue, replaceable latest frame and independent heartbeat lease.
- Room state: `STOPPED → STARTING → LIVE → CLOSING → STOPPED`; startup/media/recovery failure ends in `FAILED`.
- Prompt status: `accepted → sent / superseded / expired / failed`. `sent` only reports successful upstream channel enqueue.

The manager runs in exactly one Uvicorn process. Allocation, create-idempotency and prompt ordering are serialized with an asyncio lock. Each callback verifies it still belongs to the bound source. Startup tasks are cancelled and awaited before recovery completes.

## HTTP and stream contracts

`api/openapi.yaml` is exported from the actual application and checked by tests. Public endpoints operate on rooms, not Scope session IDs. Worker addresses and private Scope IDs are not returned.

- Create requires an `Idempotency-Key`; same content replays with 200, new creation returns 201, conflicting content returns 409.
- Prompt submission requires `(client_id, message_id)` for idempotency; the server assigns the room's ordering sequence. Retries never re-broadcast or resurrect superseded messages.
- The current manager retains up to 4096 create keys and 2048 prompt idempotency entries per room. These are bounded in-memory guarantees, not durable exactly-once processing across restarts.
- Stop returns 202 while cleanup proceeds. Poll room state for completion. Repeating stop does not free resources twice.
- Capacity counts generation slots; viewers are tracked separately. Full generation capacity returns 429 while existing rooms remain viewable.
- Lists use limit/cursor pagination. The demo UI can display the configured directory of up to 100 rooms; the server default maximum is 100 rooms.
- WebSocket protocol is specified in `docs/stream-protocol.md`.

## Recovery and ownership

Mock uses a real pair of aiortc peers and a generated diagnostic track. Closing both peers and stopping the track clears source state; injected reset failure quarantines the worker.

Managed Scope containers run `deploy/supervisor.py`, which owns exactly one child process. Recovery closes the upstream peer, attempts the documented Scope session DELETE, replaces the owned process, checks the new generation token and HTTP health, then reloads the pipeline before releasing the slot. A 204 DELETE or healthy HTTP endpoint alone does not prove history was cleared.

The hub never mounts the Docker socket. The supervisor never accepts a client PID or shell command. External Scope endpoints without an owned supervisor are usable only under the operator's clean-start responsibility and are quarantined after use; no safe external reset is currently implemented.

Separate settings control viewer heartbeats/lease, connection deadline, first-frame deadline, media-stall detection, reset RPC, process startup, and pipeline readiness. Heartbeats cannot extend an upstream connection deadline. Media-stall detection applies to LIVE sources even if the browser continues heartbeats.

The upstream connection deadline starts after model loading and covers ICE gathering, the offer exchange, remote description and parameter-channel opening as one cumulative budget. First-frame waiting starts afterward with its independent limit. Room startup can therefore include a separate, longer model-loading phase.

## Measurements and acceptance

- Level 1: state/concurrency/failure tests, true Mock WebRTC frames, shared-viewer browser checks, danmaku/prompt isolation, matching API contract and frontend build.
- Level 2: actual Scope/LongLive loading, decoded frames, prompt delivery and visibly assessed scene changes, safe process replacement and reuse.
- Level 3: two real rooms concurrently generating on distinct authorized GPUs, shared viewers per room, no cross-room prompt leakage, measured per-room rates and failure behavior.

`scripts/smoke_api.py` measures received JPEG packets and first relay frame delay; it does not label those as model generation FPS. `scope_bootstrap.py` separately records raw output batches from Scope's pinned PipelineProcessor before playback-rate clamping. Client first-frame observations use one browser clock.

Raw reports belong under ignored `artifacts/` or `results/raw/`. Public validation summaries must distinguish observed outcomes from unverified behavior.
