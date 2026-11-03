#!/bin/bash
# Pass = the answer's RESULT line says Left does NOT move the runner and Right does (truth from a direct emulator
# replay of the supplied ROM), and an animated play-test GIF at the Game Boy screen size is in /task/outputs.
set -uo pipefail
python3 /task/playcheck.py
