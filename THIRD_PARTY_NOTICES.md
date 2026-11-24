# Third-party notices

LongLive Rooms currently has no project-wide license selected. This document identifies dependencies; it does not relicense them or grant rights to third-party code, models or containers.

## Scope

The integration targets Scope 0.2.5, commit `2aced4ded3513a76cd35f0dbfb42fbfbf5e98ab0`.

- Source: https://github.com/daydreamlive/scope/tree/2aced4ded3513a76cd35f0dbfb42fbfbf5e98ab0
- That revision's license: [CC BY-NC-SA 4.0](https://github.com/daydreamlive/scope/blob/2aced4ded3513a76cd35f0dbfb42fbfbf5e98ab0/LICENSE.md).
- Scope is downloaded separately or supplied by its upstream container. Its source and weights are not included in this repository's source exports. Its license remains applicable to those components; publishing this adapter does not change it.
- `deploy/scope_bootstrap.py` documents our runtime changes: internal ICE configuration and generated-frame instrumentation. Scope source fingerprints are recorded in `configs/scope-source.sha256.json`.

## LongLive and model assets

LongLive research and upstream implementation: https://github.com/NVlabs/LongLive . The runtime in this project uses the implementation bundled in the pinned Scope version, not the current upstream main branch.

Exact model repositories and revisions are recorded in `configs/models.lock.json`; file hashes are in `configs/models.sha256.json`. Model assets are obtained separately from these sources:

- [daydreamlive/LongLive-1.3B](https://huggingface.co/daydreamlive/LongLive-1.3B)
- [daydreamlive/Wan2.1-T2V-1.3B](https://huggingface.co/daydreamlive/Wan2.1-T2V-1.3B)
- [daydreamlive/WanVideo_comfy](https://huggingface.co/daydreamlive/WanVideo_comfy)
- [daydreamlive/Autoencoders](https://huggingface.co/daydreamlive/Autoencoders)

Consult each repository's model card and license at the pinned revision. The source distribution does not grant a blanket license to these weights or claim that every dependency permits commercial use.

## Libraries and build images

Python and JavaScript dependencies retain their original licenses and notices. Exact packages are listed in `uv.lock`, the pinned Scope lockfile, and `package-lock.json`. Container sources and fingerprints are recorded in `configs/images.lock.json`; the Node build stage uses the official Node image. No third-party package source is vendored into the clean source archive.
