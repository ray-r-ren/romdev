#!/bin/bash
# Pass = a nes ROM in /task/outputs with a valid header that boots in the emulator, shows a mostly dark-blue screen and reacts to the D-pad.
set -uo pipefail
python3 /task/romcheck.py --platform nes --outputs /task/outputs --need-input --colour darkblue
