#!/bin/bash
# Pass = a Game Boy Color ROM (CGB flag 80/C0) titled GEMFALL with valid checksums that boots and draws in the
# emulator, plus a colour screenshot at the 160x144 screen size (or an integer multiple) in /task/outputs.
set -uo pipefail
python3 /task/gbccheck.py || exit 1
python3 /task/romcheck.py --platform gb --outputs /task/outputs --title GEMFALL
