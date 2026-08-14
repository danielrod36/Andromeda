#!/usr/bin/env bash
# Install gdUnit4 v6.2.0 into the client project (spec M2-D4). Idempotent.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

if [ -d client/addons/gdUnit4 ]; then
  echo "gdUnit4 already present at client/addons/gdUnit4"
  exit 0
fi

tmp="$(mktemp -d)"
curl -fSL "https://github.com/godot-gdunit-labs/gdUnit4/archive/refs/tags/v6.2.0.tar.gz" -o "$tmp/gdunit4.tar.gz"
tar -xzf "$tmp/gdunit4.tar.gz" -C "$tmp"
mkdir -p client/addons
cp -r "$tmp/gdUnit4-6.2.0/addons/gdUnit4" client/addons/gdUnit4
rm -rf "$tmp"
echo "gdUnit4 v6.2.0 installed to client/addons/gdUnit4"
