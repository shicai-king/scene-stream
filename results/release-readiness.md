# Source distribution checks

Checked 2026-11-24 after reorganizing the repository. Real GPU acceptance remains recorded in [validation.md](validation.md); the running deployment was not rebuilt or restarted during this cleanup.

| Check | Result |
|---|---|
| Software and deployment tests | 23 passed; one upstream Starlette/AnyIO deprecation warning |
| Frontend production build | PASS |
| Current tracked files and reachable Git blobs | No matches for the checked credential patterns; no private deployment host/path strings found |
| Markdown links outside the historical archive | PASS |
| Docker build-context isolation | Hub, Scope and shared-runtime contexts excluded all private/generated canary files |
| Compose parsing | Mock, full-image and shared-runtime configurations passed `docker compose config --quiet` |
| Fresh shared-runtime Docker image | Built successfully in an isolated test directory |
| Isolated image media check | Two Mock WebRTC streams, prompt retry deduplication and full-capacity rejection passed; test container removed |
| Project license | Intentionally not selected; third-party notices retained |

The Docker context test caught and corrected a directory reinclusion rule that could send extra configuration files into a build context. The final rules include only intended application inputs. The full CUDA Scope image was not rebuilt in this check, and the new GitHub Actions workflow has not yet run on GitHub.

Local message event logs, raw message captures and screenshots containing chat/danmaku were deleted at the owner's request. Retained reports contain performance/check results without message content. Runtime models, caches, virtual environments and private settings remain outside Git and the source archives.

`scripts/package_source.py` exports the committed tree with `git archive`, compares ZIP/tar file lists and writes SHA256 checksums. A package is a source snapshot; it does not include model weights, Python environments, compiled frontend output or `.git` history.
