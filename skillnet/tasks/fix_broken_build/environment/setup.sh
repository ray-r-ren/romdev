#!/bin/bash
set -e
# Deterministic setup: no network, no clock. Inputs go to /task/inputs, the expected properties to /task/truth.
set -euo pipefail
mkdir -p /task/inputs /task/truth
cp /task/meadow-project.zip /task/inputs/meadow-project.zip
echo "88ad089cc9314586b41df4104326471318516b44e5495fb99bf44237f85c0538  /task/inputs/meadow-project.zip" | sha256sum -c - >/dev/null
cat > /task/truth/expected.json <<'JSON'
{"platform": "nes", "background": "green", "dpad_moves_player": true, "input_sha256": "88ad089cc9314586b41df4104326471318516b44e5495fb99bf44237f85c0538"}
JSON
