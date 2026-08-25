#!/usr/bin/env bash
# Launch the Andromeda client (the game). The Godot app boots the Python
# sidecar itself (client/engine/sidecar_process.gd) and tears it down on
# quit — this script only starts Godot with the pinned binary.
#
# Extra args pass through to Godot (e.g. --fullscreen, --resolution ...).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

GODOT_BIN="${GODOT_BIN:-tools/godot/Godot_v4.7.1-stable_linux.x86_64}"
if [ ! -x "$GODOT_BIN" ]; then
  echo "Godot binary not found at $GODOT_BIN — run tools/get_godot.sh first" >&2
  exit 1
fi

exec "$GODOT_BIN" --path client "$@"
