"""Extra checks for the GEMFALL task: Game Boy Color header flag + title, and a real colour screenshot."""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, "/task")
from romcheck import gb_title, header_problems  # noqa: E402

truth = json.loads(Path("/task/truth/expected.json").read_text())
out = Path("/task/outputs")
roms = sorted(p for p in out.rglob("*") if p.is_file() and p.suffix.lower() in (".gbc", ".gb"))
good = []
for r in roms:
    b = r.read_bytes()
    probs = header_problems("gb", b)
    flag = f"{b[0x143]:02X}" if len(b) > 0x143 else "--"
    title = gb_title(b) if len(b) > 0x143 else ""
    if probs:
        print(f"{r.name}: {probs}")
    elif flag not in truth["cgb_flag"]:
        print(f"{r.name}: CGB flag at 0x143 is {flag}, not Game Boy Color ({truth['cgb_flag']})")
    elif truth["title"] not in title.replace(" ", "").upper():
        print(f"{r.name}: header title '{title}'")
    else:
        good.append(r)
        print(f"ok: {r.name} is a Game Boy Color ROM (flag {flag}) titled '{title}'")
if not good:
    print("FAIL: no Game Boy Color ROM with title", truth["title"])
    sys.exit(1)

W, H = truth["screen"]
shots = []
for p in sorted(out.rglob("*.png")):
    try:
        with Image.open(p) as im:
            a = np.asarray(im.convert("RGB")).astype(int)
    except Exception:
        continue
    h, w = a.shape[:2]
    if w % W or h % H or w // W != h // H:
        print(f"{p.name}: {w}x{h} is not the Game Boy screen size")
        continue
    colours = len({tuple(x) for x in a.reshape(-1, 3)[::3]})
    sat = float(((a.max(axis=2) - a.min(axis=2)) >= 60).mean())
    if colours < 4 or sat < 0.05:
        print(f"{p.name}: {colours} colours, {sat:.0%} saturated pixels (needs a colour picture)")
        continue
    shots.append(p)
    print(f"ok: screenshot {p.name} {w}x{h}, {colours} colours, {sat:.0%} saturated pixels")
if not shots:
    print("FAIL: no colour screenshot at the Game Boy screen size in outputs")
    sys.exit(1)
print("PASS")
