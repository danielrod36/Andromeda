#!/usr/bin/env bash
# Download the pinned Godot build (spec M2-D3). Idempotent: skips if present.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

GODOT_VERSION="4.7.1-stable"
GODOT_ZIP="Godot_v${GODOT_VERSION}_linux.x86_64.zip"
GODOT_BIN="tools/godot/Godot_v${GODOT_VERSION}_linux.x86_64"
# sha256 of the pinned zip (computed from the official release artifact) —
# CI executes this binary; a tampered/CDN-corrupted download must abort.
GODOT_SHA256="c7ff14fd28472c8d4f193043de30278dcf7e5241a1dcf7566b02e27addaa33ba"

if [ -x "$GODOT_BIN" ]; then
  echo "Godot ${GODOT_VERSION} already present at ${GODOT_BIN}"
  exit 0
fi

mkdir -p tools/godot
tmp="$(mktemp -d)"
curl -fSL --retry 3 "https://github.com/godotengine/godot/releases/download/${GODOT_VERSION}/${GODOT_ZIP}" -o "$tmp/godot.zip"
echo "${GODOT_SHA256}  $tmp/godot.zip" | sha256sum --check --status \
  || { echo "Godot zip checksum mismatch — aborting" >&2; exit 1; }
unzip -q "$tmp/godot.zip" -d tools/godot/
chmod +x "$GODOT_BIN"
rm -rf "$tmp"
"$GODOT_BIN" --version
