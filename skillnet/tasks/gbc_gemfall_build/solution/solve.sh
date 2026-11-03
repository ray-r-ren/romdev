#!/bin/bash
set -e
# Reference solution: drives the toolchain and emulator installed in the image directly (not the skill).
set -euo pipefail
mkdir -p /task/outputs /tmp/solve
cat > /tmp/romsolve.py <<'PY'
"""Reference solver: drives the romdev toolchain server installed in the image directly (no skill)."""
import json, os, signal, socket, subprocess, sys, time, urllib.request
from pathlib import Path

NODE = "/opt/node24/bin/node"
SERVER_JS = "/opt/romdev/node_modules/romdevtools/src/mcp/server.js"


def server():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    env = {**os.environ, "PORT": str(port), "HOST": "127.0.0.1", "PATH": "/opt/node24/bin:" + os.environ.get("PATH", "")}
    p = subprocess.Popen([NODE, SERVER_JS], env=env, cwd="/tmp", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    for _ in range(300):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/openapi.json", timeout=2); return p, port
        except Exception:
            time.sleep(0.2)
    sys.exit("server did not start")


def call(port, tool, args):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/tool/{tool}", data=json.dumps(args).encode(), method="POST",
                                 headers={"content-type": "application/json", "x-romdev-session": "solve"})
    try:
        with urllib.request.urlopen(req, timeout=540) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()[:500]}


def gb_finish(path, title):
    b = bytearray(Path(path).read_bytes())
    b[0x134:0x13F] = title.upper().encode()[:11].ljust(11, b"\0")
    for i in range(0x13F, 0x143):
        if b[i] == 0xFF:
            b[i] = 0
    x = 0
    for v in b[0x134:0x14D]:
        x = (x - v - 1) & 0xFF
    b[0x14D] = x
    g = (sum(b) - b[0x14E] - b[0x14F]) & 0xFFFF
    b[0x14E], b[0x14F] = g >> 8, g & 0xFF
    Path(path).write_bytes(bytes(b))


def main():
    cmd = sys.argv[1]
    p, port = server()
    try:
        if cmd == "fork":  # fork <example> <name> <dir>
            r = call(port, "examples", {"op": "fork", "example": sys.argv[2], "name": sys.argv[3], "path": sys.argv[4]})
            if r.get("error"):
                sys.exit(f"fork failed: {r['error']}")
        elif cmd == "build":  # build <platform> <dir> <out.rom> [gb-title]
            r = call(port, "build", {"output": "project", "platform": sys.argv[2], "path": str(Path(sys.argv[3]).resolve()),
                                     "outputPath": str(Path(sys.argv[4]).resolve())})
            if not r.get("ok"):
                sys.exit("build failed: " + str(r.get("log") or r.get("logTail") or r.get("error"))[-2000:])
            if len(sys.argv) > 5:
                gb_finish(sys.argv[4], sys.argv[5])
        elif cmd == "shot":  # shot <platform> <rom> <out.png> <frames>
            call(port, "loadMedia", {"platform": sys.argv[2], "path": str(Path(sys.argv[3]).resolve())})
            call(port, "frame", {"op": "step", "frames": int(sys.argv[5])})
            call(port, "frame", {"op": "screenshot", "path": str(Path(sys.argv[4]).resolve())})
        elif cmd == "probe":  # probe <platform> <rom> <gif> : which of left/right move the player after Start
            import numpy as np
            from PIL import Image
            tmp = Path("/tmp/solve/probe"); tmp.mkdir(parents=True, exist_ok=True)
            frames = []
            def shot(name):
                p = tmp / (name + ".png")
                call(port, "frame", {"op": "screenshot", "path": str(p)})
                im = Image.open(p).convert("RGB"); frames.append(im.copy())
                return np.asarray(im).astype(int)
            def hold(buttons, n):
                call(port, "input", {"op": "set", "ports": [{b: True for b in buttons}]})
                for _ in range(n // 5):
                    call(port, "frame", {"op": "step", "frames": 5}); shot("f")
                call(port, "input", {"op": "set", "ports": [{}]})
            call(port, "loadMedia", {"platform": sys.argv[2], "path": str(Path(sys.argv[3]).resolve())})
            hold([], 60); hold(["start"], 10); hold([], 60)
            call(port, "state", {"op": "save", "name": "s"})
            hold([], 30); idle = shot("idle")
            res = {}
            for d in ("left", "right"):
                call(port, "state", {"op": "load", "name": "s", "render": False})
                hold([d], 30); held = shot(d)
                res[d] = int(np.any(np.abs(held - idle) > 24, axis=2).sum())
            frames[0].save(sys.argv[4], save_all=True, append_images=frames[1:], duration=80, loop=0)
            print(json.dumps(res))
    finally:
        os.killpg(p.pid, signal.SIGKILL)


main()
PY
rm -rf /tmp/solve/proj
python3 /tmp/romsolve.py fork gbc/puzzle gemfall /tmp/solve/proj
python3 /tmp/romsolve.py build gbc /tmp/solve/proj /task/outputs/gemfall.gbc GEMFALL
python3 /tmp/romsolve.py shot gbc /task/outputs/gemfall.gbc /task/outputs/gemfall-screenshot.png 180
echo "Here is GEMFALL for the Game Boy Color (gemfall.gbc) and a screenshot of its title screen running in the emulator." > /task/answer.txt
