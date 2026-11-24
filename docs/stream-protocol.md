# Browser stream protocol V1

Connect to `/api/v1/rooms/{room_id}/stream` with a same-origin WebSocket. The server checks the Origin header; configurable local Vite origins are permitted during development. This is a private demo, not an account/authorization system.

## Server text messages

- `snapshot`: room view, bounded `history`, viewer ID, heartbeat interval, current event sequence. Sent on every join/reconnect; replaces client history.
- `prompt`: newly accepted prompt. Render with textContent, not HTML. Add it to chat and danmaku.
- `prompt_status`: same prompt ID and updated status. Update its existing entry; do not add another danmaku.
- `room_state`: updated room view.
- `viewers`: participant count.
- `pong`: echoed client time plus room view.
- `error`: message explaining why the connection cannot join.

Room events include increasing `event_seq`. History and events are bounded. Slow event consumers are disconnected with 1013 and must reconnect for a snapshot; the protocol does not promise an unbounded replay log.

## Server binary messages

Each message consists of:

1. Four-byte unsigned big-endian JSON header length.
2. UTF-8 JSON header with `room_id`, `frame_seq`, `created_at`, `source_frames`, `source_fps`, `width`, `height`.
3. One complete JPEG image.

The browser decodes with createImageBitmap and draws on canvas. It retains only the latest pending frame when decoding is slower than receiving. The server independently retains only the latest pending packet for each viewer. Frame IDs may therefore skip, but must not go backward within one generation run.

`source_fps` measures received upstream WebRTC frames, not model output batches. Room restart resets frame counters. UTC timestamps are correlation metadata, not a claim of precise cross-machine one-way latency.

## Client heartbeat

Send JSON immediately after joining and every configured heartbeat interval:

```json
{"type":"ping","client_time":1234.5,"rendered_frames":42,"first_frame_ms":113}
```

The final two fields are optional browser observations. Only the server's monotonic receive time determines viewer lease expiry. No valid heartbeat within the lease closes only that viewer connection; room generation continues. Prompt submission uses the HTTP API; this WebSocket does not directly control the Scope data channel.
