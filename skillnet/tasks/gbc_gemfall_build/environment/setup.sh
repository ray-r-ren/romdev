#!/bin/bash
set -e
# Deterministic setup: no network, no clock. No input files; the expected properties go to /task/truth.
set -euo pipefail
mkdir -p /task/inputs /task/truth
cat > /task/truth/expected.json <<'JSON'
{"platform": "gbc", "title": "GEMFALL", "cgb_flag": ["80", "C0"], "screen": [160, 144]}
JSON
