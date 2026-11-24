#!/usr/bin/env bash
# Run as the deployment user from the project root; no host package changes.
set -euo pipefail
project_root="$(pwd)"
uv_bin="${UV_BIN:-uv}"
scope_commit=2aced4ded3513a76cd35f0dbfb42fbfbf5e98ab0
test -f "$project_root/pyproject.toml"
mkdir -p runtime logs models vendor
export UV_CACHE_DIR="$project_root/runtime/uv"
export UV_PYTHON_INSTALL_DIR="$project_root/runtime/python"
export UV_HTTP_TIMEOUT="${UV_HTTP_TIMEOUT:-180}"
"$uv_bin" python install 3.12.8
runtime_python="$("$uv_bin" python find --managed-python 3.12.8)"
if ! test -d vendor/scope/src; then
  git clone --no-checkout https://github.com/daydreamlive/scope.git vendor/scope
  git -C vendor/scope checkout --detach "$scope_commit"
fi
"$runtime_python" scripts/verify_scope_source.py
if [ "${1:-}" = "--use-mirrors" ]; then
  "$runtime_python" scripts/use_dependency_mirrors.py vendor/scope
fi
UV_PROJECT_ENVIRONMENT="$project_root/runtime/hub-env" "$uv_bin" sync --frozen --no-dev --python "$runtime_python"
UV_PROJECT_ENVIRONMENT="$project_root/runtime/scope-env" "$uv_bin" sync --project vendor/scope --frozen --no-dev --python "$runtime_python" --no-install-package sageattention
printf '%s\n' 'Shared-disk environments installed. Verify model hashes before starting workers.'
