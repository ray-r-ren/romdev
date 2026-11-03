#!/bin/bash
# Pass = a gb ROM in /task/outputs with a valid header that boots in the emulator, has TURBOLANE in the header title, valid checksums and reacts to the D-pad.
set -uo pipefail
python3 /task/romcheck.py --platform gb --outputs /task/outputs --need-input --title TURBOLANE
