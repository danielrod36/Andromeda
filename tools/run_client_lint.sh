#!/usr/bin/env bash
# gdlint + gdformat over first-party GDScript only (never client/addons/).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

DIRS="client/app client/components client/engine client/screens client/tests client/theme"

printf '▶ gdlint\n'
uv run gdlint $DIRS

printf '▶ gdformat --check\n'
uv run gdformat --check $DIRS
