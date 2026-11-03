#!/bin/bash
set -e
# Reference solution: drives the toolchain installed in the image directly (not the skill).
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
    finally:
        os.killpg(p.pid, signal.SIGKILL)


main()
PY
rm -rf /tmp/solve/proj
python3 /tmp/romsolve.py fork genesis/shmup crimson /tmp/solve/proj
# nebula checkerboard colours (0x0BGR): blue/plum -> two reds
sed -i "s/PAL_setColor(16 + 4, 0x0411)/PAL_setColor(16 + 4, 0x000A)/; s/PAL_setColor(16 + 5, 0x0204)/PAL_setColor(16 + 5, 0x0006)/" /tmp/solve/proj/main.c
python3 /tmp/romsolve.py build genesis /tmp/solve/proj /task/outputs/crimson.md
