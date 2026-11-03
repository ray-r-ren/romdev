#!/bin/bash
set -e
# Deterministic setup: no network, no clock. Inputs go to /task/inputs, the expected properties to /task/truth.
set -euo pipefail
mkdir -p /task/inputs /task/truth

cat > /task/truth/expected.json <<'JSON'
{"platform": "gb", "header_title": "TURBOLANE", "dpad_moves_player": true}
JSON
