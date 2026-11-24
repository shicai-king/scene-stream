# Validation record

Updated 2026-11-24. These are observed results for the tested configuration, not performance guarantees.

| Level | Status | Evidence |
|---|---|---|
| 1 — software framework | PASS | 18 pytest checks; matching exported OpenAPI; production frontend build; real aiortc Mock transport; lifecycle/deadline/failure tests |
| 2 — real single stream | PASS | Actual LongLive frames in the browser; visible prompt-driven scene changes; owned-process replacement, model reload and reuse |
| 3 — real concurrent rooms | PASS | Two actual GPU streams; shared viewers; independent prompts and images; capacity rejection; normal recovery and injected single-worker failure while the other room continued |

## Tested configuration

Two NVIDIA A800-SXM4-80GB devices, one worker per physical GPU (1 and 2). Scope 0.2.5 at the pinned commit in `docs/compatibility.md`; Python 3.12.8, Torch 2.9.1+cu128, Flash Attention 2.8.3. Resolution **384×224**, BF16 diffusion, four denoising steps, full WAN VAE, VACE off, SageAttention disabled. The hub relays JPEG at a configured maximum of 24 FPS, quality 78.

All 16 model files (17,306,975,523 bytes) passed official SHA256 checks. A real BF16 matrix operation and Flash Attention 2 kernel passed on the target A800. Both final workers subsequently generated actual video using the newly installed shared-disk environment. Container inspection verified distinct GPU assignments, read-only dependency mounts under the current runtime root, and no dependency on the previous deployment root. The hub entrypoint binds only to server loopback.

Application image used by all three final containers: `sha256:59b18a589428e6bbb71c1ba1550d8bf70789c70e78c847fe055278cce3627229`. Base image and source/model fingerprints are pinned separately in `configs/`.

## Actual video and prompts

Two browser pages received the same room's real generated frames. Prompt broadcasts and delivery status reached both pages; switching one page to the other room preserved the first stream and isolated chat. Desktop/mobile rendering passed without JavaScript errors.

Visual inspection of retained frames confirmed:

- Initial room 1: rainy neon roadway. Initial room 2: flowers floating above clouds.
- After changing room 1: an orange fox and snowy trees appeared, while room 2 continued its garden imagery.
- After changing room 2: fish and underwater colors appeared, while room 1 retained fox/forest imagery.

Old scene structures persist during transitions. Prompt delivery is observable, but it is not a guarantee of a clean cut or exact visual compliance. The paired capture recorded both rooms before each change and 5, 15 and 30 seconds afterward, and checked that the untouched room's prompt stayed unchanged while its frames advanced.

## Measured throughput

The single-worker 30-second run received 649 JPEG frames at **21.623 FPS**. The final two-worker run measured both streams concurrently:

| Room | Received JPEG frames / elapsed | Received FPS | Raw model FPS | Raw model observation |
|---|---|---|---|---|
| night-walk | 642 / 30.007 s | 21.395 | 23.395 | 118 batches / 60.526 s |
| floating-garden | 640 / 30.018 s | 21.321 | 22.935 | 115 batches / 60.169 s |

JPEG measurements used a client on the server, avoiding SSH bandwidth as a confounder. Raw model FPS is total generated frames divided by recorded batch intervals over approximately 60 seconds; it is measured before Scope playback and hub sampling. These rates are distinct from browser display FPS. Joining already-running streams delivered the first relay frame in 9.17 / 14.71 ms on the server itself; these are **not** model startup times or laptop network latency.

The initial single room took 67.53 s from allocation to first source frame. The final dual deployment took about 94.4 s per room after hub allocation, including owned-process reset and model load. Earlier cold Python imports over NFS also added minutes before the hub started; startup budgets are separate from generation speed.

## Recovery and failure isolation

Normal stop/reset/reuse passed. Cleanup plus verified model readiness took **64.3 s**; starting that room again reached LIVE in **66.6 s**. One slot was available only after recovery, no worker was quarantined, and the other room continued generating. Supervisor generation tokens changed for the recovered worker and stayed unchanged for the other worker.

A separate fault test sent SIGKILL only to the exact `scope_bootstrap.py` child inside the project's first worker container. Observed states: **LIVE at 0.24 s, CLOSING at 34.39 s, FAILED at 76.57 s** (2-second polling). The manager recovered the owned process, reloaded the model and returned one slot to availability. The other room remained LIVE and retained its supervisor generation token. Explicitly starting the failed room reached LIVE again in **46.51 s**. Both rooms were left running after the test.

## Evidence and limits

Ignored local evidence under `artifacts/real/`: `models-verified.json`, `gpu-1-preflight.log`, `runtime-final.json`, `real-single.json`, `real-two.json`, `real-two-model-fps.json`, `real-recovery.json`, `real-recovery-generations.json`, `real-failure.json`, both `browser-*/browser-report.json` reports and screenshots, and `pair-scenes/report.json` with before/after JPEGs. Server raw records are under `results/raw/`; lifecycle logs are under `logs/`. Raw logs, private deployment paths and weights are not committed.

This is a course-demo validation at one resolution with two workers. Higher resolutions, more than two simultaneous real workers, long-duration soak reliability, and alternative models have not been validated. The standard full CUDA image path has not been exercised here; the tested Docker variant uses pinned dependencies on the shared disk. The one observed pytest warning is an upstream Starlette/AnyIO deprecation warning.
