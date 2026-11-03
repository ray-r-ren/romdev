#!/bin/bash
set -e
# Deterministic setup: no network, no clock. The ROM is a fixed file (Game Boy platformer whose Left control is broken).
set -euo pipefail
mkdir -p /task/inputs /task/truth
cp /task/dustrunner.gb /task/inputs/dustrunner.gb
echo "a2347886e65e20308f4101311d233fcebb8386890bd8c7d260c5677f38d9cfbc  /task/inputs/dustrunner.gb" | sha256sum -c - >/dev/null
cat > /task/truth/expected.json <<'JSON'
{"left_moves": false, "right_moves": true, "screen": [160, 144]}
JSON
