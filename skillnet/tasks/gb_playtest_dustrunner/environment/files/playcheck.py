"""Check for the DUSTRUNNER play-test: the RESULT line matches the truth and a play-test GIF exists."""
import json
import re
import sys
from pathlib import Path

from PIL import Image

truth = json.loads(Path("/task/truth/expected.json").read_text())
ans = Path("/task/answer.txt").read_text(errors="replace") if Path("/task/answer.txt").exists() else ""
m = re.findall(r"RESULT:\s*LEFT\s*=\s*(yes|no)\s*,?\s*RIGHT\s*=\s*(yes|no)", ans, re.I)
if not m:
    print("FAIL: no 'RESULT: LEFT=yes|no RIGHT=yes|no' line in the answer")
    sys.exit(1)
left, right = (v.lower() == "yes" for v in m[-1])
want = (truth["left_moves"], truth["right_moves"])
if (left, right) != want:
    print(f"FAIL: answer says LEFT={left} RIGHT={right}; replay shows LEFT={want[0]} RIGHT={want[1]}")
    sys.exit(1)
print(f"ok: answer LEFT={left} RIGHT={right} matches the replay")

W, H = truth["screen"]
for g in sorted(Path("/task/outputs").rglob("*.gif")):
    try:
        with Image.open(g) as im:
            n, (w, h) = getattr(im, "n_frames", 1), im.size
    except Exception:
        continue
    if n >= 2 and w % W == 0 and h % H == 0 and w // W == h // H:
        print(f"ok: {g.name} has {n} frames at {w}x{h}")
        print("PASS")
        sys.exit(0)
    print(f"{g.name}: {n} frames at {w}x{h}")
print("FAIL: no animated GIF (>= 2 frames, Game Boy screen size) in outputs")
sys.exit(1)
