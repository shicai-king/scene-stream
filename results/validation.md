# Validation record

Updated 2026-11-24. This file records actual observations; it is not a promise of model FPS.

| Level | Status | Evidence |
|---|---|---|
| 1 — software framework | PASS for checks executed so far | 15 pytest checks; production frontend build; local and remote Docker two-browser shared frames, prompt broadcast, room switching and mobile layout |
| 2 — real single stream | NOT RUN | Docker images and fixed model assets are being prepared |
| 3 — real concurrent rooms | NOT RUN | Depends on real single-stream validation |

Local tests used Python 3.12.3 and a real aiortc Mock peer pair. Mock/browser reports and screenshots are under ignored `artifacts/`. Remote dependency downloads are not evidence of completed real model inference.

The remote Docker test used the shared-disk Python environment with read-only runtime mounts and an SSH TCP forward. Two viewers shared one room, then one switched to the other room while the first stream continued. No browser JavaScript errors were observed. Supervisor failure tests also verify that a real child process is terminated when startup or reset cannot reach readiness.
