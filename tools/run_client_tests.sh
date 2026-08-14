#!/usr/bin/env bash
# One-command gdUnit4 entry (gate + local). Exit 0 on pass or warnings-only.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

GODOT_BIN="${GODOT_BIN:-tools/godot/Godot_v4.7.1-stable_linux.x86_64}"
if [ ! -x "$GODOT_BIN" ]; then
  echo "Godot binary not found at $GODOT_BIN — run tools/get_godot.sh first" >&2
  exit 1
fi

# First run needs an import pass to build .godot/ (fonts etc.).
if [ ! -d client/.godot ]; then
  "$GODOT_BIN" --headless --path client --import
fi

set +e
"$GODOT_BIN" --headless --path client \
  -s res://addons/gdUnit4/bin/GdUnitCmdTool.gd \
  -a res://tests -c --ignoreHeadlessMode -rd /tmp/gdunit-reports
code=$?
set -e

# gdUnit4 exit codes: 0 = pass, 100 = failures, 101 = warnings-only.
if [ "$code" -eq 0 ] || [ "$code" -eq 101 ]; then
  exit 0
fi
exit "$code"
