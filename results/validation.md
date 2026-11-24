# Validation record

Updated 2026-11-24. This file records actual observations; it is not a promise of model FPS.

| Level | Status | Evidence |
|---|---|---|
| 1 — software framework | PASS for checks executed so far | 17 pytest checks; production frontend build; local and remote Docker two-browser shared frames, prompt broadcast, room switching and mobile layout |
| 2 — real single stream | BLOCKED | Server dependencies/model assets are incomplete; SSH download forwarding repeatedly disconnected. No real inference evidence yet. |
| 3 — real concurrent rooms | BLOCKED | Depends on Level 2 and complete server assets. Two real GPU streams have not been validated. |

Local tests used Python 3.12.3 and a real aiortc Mock peer pair. Mock/browser reports and screenshots are under ignored `artifacts/`. Remote dependency downloads are not evidence of completed real model inference.

The remote Docker test used the shared-disk Python environment with read-only runtime mounts and an SSH TCP forward. Two viewers shared one room, then one switched to the other room while the first stream continued. No browser JavaScript errors were observed. Supervisor failure tests also verify that a real child process is terminated when startup or reset cannot reach readiness.

Remote Mock recovery also passed: stopping one room freed one slot in 0.22 s; starting it again reached LIVE in 2.38 s while the other room continued. These are diagnostic Mock observations, not real model recovery times.

Deployment preparation verified available A800 GPUs and a working small Docker image. The shared-disk variant avoids the host's limited Docker partition. Official model/source fingerprints and dependency lockfiles are recorded; optional mirrors preserve versions and hashes. Downloads and a successful build are not counted as real GPU acceptance. Remaining checks: complete all 16 server model files and dependencies, run the CUDA/Flash Attention probe, assess real prompt-driven scene changes, test owned-process reset/reuse, then measure two concurrent rooms on distinct authorized GPUs.

Two additional deadline checks verify one cumulative connection budget across signaling stages and a separate first-frame waiting budget.
