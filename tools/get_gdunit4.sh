#!/usr/bin/env bash
# Install gdUnit4 v6.2.0 into the client project (spec M2-D4). Idempotent.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

if [ -d client/addons/gdUnit4 ]; then
  echo "gdUnit4 already present at client/addons/gdUnit4"
  exit 0
fi

tmp="$(mktemp -d)"
curl -fSL --retry 3 "https://github.com/godot-gdunit-labs/gdUnit4/archive/refs/tags/v6.2.0.tar.gz" -o "$tmp/gdunit4.tar.gz"
echo "74e00f49e245b9b0c1599d1359d0ea88d1a867d05d7e5b12fa982bc4ca312a1a  $tmp/gdunit4.tar.gz" | sha256sum --check --status || { echo "gdUnit4 tarball checksum mismatch" >&2; exit 1; }
tar -xzf "$tmp/gdunit4.tar.gz" -C "$tmp"
mkdir -p client/addons
cp -r "$tmp/gdUnit4-6.2.0/addons/gdUnit4" client/addons/gdUnit4
rm -rf "$tmp"
echo "gdUnit4 v6.2.0 installed to client/addons/gdUnit4"
