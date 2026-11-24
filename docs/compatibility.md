# Scope compatibility record

- Scope release: **0.2.5**.
- Source commit: `2aced4ded3513a76cd35f0dbfb42fbfbf5e98ab0`.
- Official image: `ghcr.io/daydreamlive/scope@sha256:3bed0bf78d7a6cf6b467912c9985eebf7d5479d0401cbbc5f07ed8f58ce9dfef`.
- Upstream stack: Python 3.12.8, Torch 2.9.1 / CUDA 12.8, flash-attn 2.8.3.
- Model revisions: `configs/models.lock.json`; exact 16-file sizes and official SHA-256 values: `configs/models.sha256.json`.
- Total declared model assets: 17,306,975,523 bytes, excluding images and Python packages.

## Checked against pinned source

- Async load: `POST /api/v1/pipeline/load`, then poll `GET /api/v1/pipeline/status`.
- Load uses **`base_seed`**, not the older documentation's `seed` example.
- Upstream offer: `POST /api/v1/webrtc/offer`; response includes `sessionId`, `type`, `sdp`.
- The hub creates an ordered `parameters` channel and recvonly video transceiver before offering. It waits for local ICE gathering and sends the complete SDP.
- `initialParameters` includes pipeline_ids, input_mode=text, prompts, manage_cache, and denoising_step_list. Later prompt messages are `{"prompts":[{"text":"...","weight":1.0}]}`.
- `DELETE /api/v1/webrtc/offer/{session_id}` exists in this release. It is used for connection cleanup but is not treated as proof of complete model-state reset.
- Each offer gets a separate FrameProcessor; multiple viewer offers to one Scope process are not assumed to share one output. This project uses one upstream peer per room.

## Controlled compatibility layer

`deploy/scope_bootstrap.py` makes two narrowly scoped adaptations before starting the application:

1. Replaces create_rtc_config with an empty ICE-server list. Internal Docker peers do not contact the upstream default Google STUN or optional TURN services.
2. Wraps PipelineProcessor._track_output_batch to print raw frame count and batch timing JSON. Scope's clamped playback FPS is not used as the raw generation-rate measure.

Set `DISABLE_SAGEATTENTION=1` for the initial A800 validation to use Flash Attention 2. Use BF16 diffusion with `quantization: null`; no assumption that Hopper FP8 throughput applies to Ampere. Driver/CUDA compatibility and actual kernels must be tested in the target environment; the project does not modify host drivers.

For the shared-disk runtime variant, the pinned upstream environment is installed with `uv sync --frozen --no-dev --no-install-package sageattention`. SageAttention is explicitly excluded because it is disabled for this configuration; Flash Attention 2 remains pinned. This is a documented departure from installing every upstream dependency. Runtime uses `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` after model hash verification; optional kernel downloads cannot silently add unpinned artifacts at startup.

## Sources

- [Pinned source and Dockerfile](https://github.com/daydreamlive/scope/tree/2aced4ded3513a76cd35f0dbfb42fbfbf5e98ab0)
- [WebRTC implementation](https://github.com/daydreamlive/scope/blob/2aced4ded3513a76cd35f0dbfb42fbfbf5e98ab0/src/scope/server/webrtc.py)
- [Pipeline throughput accounting](https://github.com/daydreamlive/scope/blob/2aced4ded3513a76cd35f0dbfb42fbfbf5e98ab0/src/scope/server/pipeline_processor.py)

Current runtime validation status is recorded separately in `results/validation.md`.
