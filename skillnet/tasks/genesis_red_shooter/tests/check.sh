#!/bin/bash
# Pass = a genesis ROM in /task/outputs with a valid header that boots in the emulator, shows a mostly red screen and reacts to the D-pad.
set -uo pipefail
python3 /task/romcheck.py --platform genesis --outputs /task/outputs --need-input --colour red
