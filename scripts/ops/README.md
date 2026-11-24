# Optional deployment utilities

Run from the repository root. These tools are not required for the normal application startup.

- `import_image.py`: download a digest-resolved image with a separately verified `crane` binary, import it into the current Docker engine, and tag it. Avoids changing a shared daemon's proxy configuration. Example: `python3 scripts/ops/import_image.py IMAGE --tag LOCAL_TAG --archive cache/image.tar`.
- `download_models.py`: alternative downloader using `huggingface_hub` inside the Scope environment. Always run `python3 scripts/verify_models.py --root models` afterward. The normal documented downloader is `scripts/download_verified_models.py`.
- `download_proxy.py`: temporary loopback-only CONNECT proxy for public dependency hosts. It is not an application endpoint. Stop it after deployment preparation.

Archives, credentials, real hostnames and temporary operator scripts belong in ignored local files. No host-wide proxy or Docker settings are changed by the normal deployment workflow.
