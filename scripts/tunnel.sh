#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -lt 1 ]; then printf 'Usage: bash scripts/tunnel.sh SSH_ALIAS [LOCAL_PORT] [REMOTE_PORT]\n' >&2; exit 2; fi
target="$1"
local_port="${2:-8080}"
remote_port="${3:-8080}"
printf 'Keep this terminal open; visit http://127.0.0.1:%s\n' "$local_port"
exec ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -L "127.0.0.1:${local_port}:127.0.0.1:${remote_port}" "$target"
