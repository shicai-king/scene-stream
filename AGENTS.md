# Project implementation rules

- Read `docs/implementation_spec.md`, `api/openapi.yaml`, and `docs/compatibility.md` before changing interfaces or backend behavior. `docs/archive/` contains superseded historical inputs.
- Develop locally. Deploy only to the host/path explicitly authorized in the current conversation; local deployment notes are ignored by Git. Never infer permission to use additional GPUs, stop another user's process, expose public ports, change host drivers, or push GitHub.
- A room owns one generation source. Viewers share that source; leaving a room never stops it. Keep viewer, room, worker and upstream peer lifecycles separate.
- All accepted prompts become events. Keep at most one unsent prompt per room; newest replaces older pending prompts. One server-side sender orders upstream delivery. A successful send is not a model/visual acknowledgement.
- Keep queues bounded, protect allocation/idempotency with the manager lock, and check stale callbacks against the currently bound source.
- A worker becomes reusable only after verified cleanup. Restart only the worker supervisor's own child. External workers without safe reset must be quarantined.
- Scope compatibility facts must be checked against the pinned source. Do not invent APIs. Do not use Mock FPS as real model performance.
- Keep dependencies and model/image versions pinned. Never commit model weights, private deployment configuration, credentials or raw user content.
- Run relevant tests and `npm run build`. After API changes run `PYTHONPATH=. .venv/bin/python scripts/export_openapi.py` and verify the exported contract matches the service.
- Report Level 1 (software), Level 2 (real single stream), and Level 3 (real concurrent rooms) separately, with actual evidence and unverified limitations.
