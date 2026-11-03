"""Independent checker for Retro Game Forge tasks.

Finds the ROM the agent delivered under /task/outputs, validates its cartridge header with plain
Python, then boots it in the emulator installed in the image (libretro cores driven by the romdev
server) and measures the picture: is something drawn, which colour dominates, does it react to
buttons. Exit 0 = pass. Prints one line per check."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

NODE = "/opt/node24/bin/node"
SERVER_JS = "/opt/romdev/node_modules/romdevtools/src/mcp/server.js"
EXTS = {"nes": [".nes"], "gb": [".gb", ".gbc"], "genesis": [".md", ".bin", ".gen", ".smd"]}
GB_LOGO = bytes.fromhex(
    "CEED6666CC0D000B03730083000C000D0008111F8889000EDCCC6EE6DDDDD999BBBB67636E0EECCCDDDC999FBBB9333E")


def fail(msg: str) -> None:
    print("FAIL:", msg)
    sys.exit(1)


def ok(msg: str) -> None:
    print("ok:", msg)


# ----------------------------------------------------------------------------------- headers
def header_problems(platform: str, b: bytes) -> list[str]:
    p: list[str] = []
    if platform == "nes":
        if len(b) < 16 + 16384 or b[:4] != b"NES\x1a":
            return ["no iNES header"]
        prg, chr_ = b[4] * 16384, b[5] * 8192
        if prg == 0 or len(b) < 16 + prg + chr_:
            p.append(f"file shorter than header says ({len(b)} < {16 + prg + chr_})")
    elif platform == "gb":
        if len(b) < 0x8000 or b[0x104:0x134] != GB_LOGO:
            return ["no Nintendo logo at 0x104"]
        x = 0
        for v in b[0x134:0x14D]:
            x = (x - v - 1) & 0xFF
        if b[0x14D] != x:
            p.append("header checksum wrong")
        g = (sum(b) - b[0x14E] - b[0x14F]) & 0xFFFF
        if ((b[0x14E] << 8) | b[0x14F]) != g:
            p.append("global checksum wrong")
    elif platform == "genesis":
        if len(b) < 0x200 or b[0x100:0x104] != b"SEGA" and b[0x101:0x105] != b"SEGA":
            return ["no SEGA signature at 0x100"]
        s = 0
        for i in range(0x200, len(b) - 1, 2):
            s = (s + ((b[i] << 8) | b[i + 1])) & 0xFFFF
        if int.from_bytes(b[0x18E:0x190], "big") != s:
            p.append("header checksum wrong")
    return p


def gb_title(b: bytes) -> str:
    return b[0x134:0x143].split(b"\x00")[0].decode("ascii", "replace")


# ----------------------------------------------------------------------------------- emulator
class Emu:
    def __init__(self) -> None:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        env = {**os.environ, "PORT": str(self.port), "HOST": "127.0.0.1",
               "PATH": "/opt/node24/bin:" + os.environ.get("PATH", "")}
        self.proc = subprocess.Popen([NODE, SERVER_JS], env=env, cwd="/tmp", stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True)
        for _ in range(300):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/openapi.json", timeout=2)
                return
            except Exception:
                time.sleep(0.2)
        self.close()
        fail("emulator server did not start")

    def call(self, tool: str, args: dict) -> dict:
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/tool/{tool}", data=json.dumps(args).encode(),
                                     method="POST", headers={"content-type": "application/json",
                                                             "x-romdev-session": "taskcheck"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                out = json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            out = {"error": e.read().decode("utf-8", "replace")[:300]}
        if isinstance(out, dict) and out.get("error") and len(out) <= 3:
            raise RuntimeError(f"{tool}: {out['error']}")
        return out if isinstance(out, dict) else {}

    def shot(self, path: Path) -> np.ndarray:
        self.call("frame", {"op": "screenshot", "path": str(path)})
        with Image.open(path) as im:
            return np.asarray(im.convert("RGB")).astype(int)

    def close(self) -> None:
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except Exception:
            pass


def diff(a: np.ndarray, b: np.ndarray) -> int:
    if a.shape != b.shape:
        return a.shape[0] * a.shape[1]
    return int(np.any(np.abs(a - b) > 24, axis=2).sum())


def colour_share(img: np.ndarray, colour: str) -> float:
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    if colour == "red":
        m = (r >= 60) & (r >= g + 40) & (r >= b + 40)
    elif colour == "darkblue":  # navy/dark blue; sky blue (g ~190) does not count
        m = (b >= 60) & (b >= r + 40) & (b >= g) & (g < 140)
    elif colour == "green":
        m = (g >= 60) & (g >= r + 40) & (g >= b + 40)
    else:
        raise ValueError(colour)
    return float(m.mean())


def play_checks(platform: str, rom: Path, need_input: bool, colour: str | None, tmp: Path) -> list[str]:
    emu = Emu()
    problems: list[str] = []
    try:
        local = tmp / ("rom" + rom.suffix)
        local.write_bytes(rom.read_bytes())
        emu.call("loadMedia", {"platform": platform, "path": str(local)})
        emu.call("frame", {"op": "step", "frames": 180})
        boot = emu.shot(tmp / "boot.png")
        colours = len({tuple(p) for p in boot.reshape(-1, 3)[:: 7]})
        if colours < 2:
            problems.append("screen is a single flat colour after 3 s")
        else:
            ok(f"renders {colours}+ colours after 180 frames")
        if colour:
            share = colour_share(boot, colour)
            if share < 0.35:
                problems.append(f"only {share:.0%} of the screen is {colour} (need >= 35%)")
            else:
                ok(f"{share:.0%} of the screen is {colour}")
        if need_input:
            moved = 0
            # try the D-pad straight away, then after Start, then after A (title screens)
            for prelude in ([], ["start"], ["a"], ["start"]):
                if prelude:
                    emu.call("input", {"op": "set", "ports": [{prelude[0]: True}]})
                    emu.call("frame", {"op": "step", "frames": 8})
                    emu.call("input", {"op": "set", "ports": [{}]})
                    emu.call("frame", {"op": "step", "frames": 60})
                emu.call("state", {"op": "save", "name": "chk"})
                emu.call("input", {"op": "set", "ports": [{}]})
                emu.call("frame", {"op": "step", "frames": 45})
                idle = emu.shot(tmp / "idle.png")
                for d in ("right", "left", "up", "down"):
                    emu.call("state", {"op": "load", "name": "chk", "render": False})
                    emu.call("input", {"op": "set", "ports": [{d: True}]})
                    emu.call("frame", {"op": "step", "frames": 45})
                    held = emu.shot(tmp / f"held-{d}.png")
                    moved = max(moved, diff(idle, held))
                emu.call("state", {"op": "load", "name": "chk", "render": False})
                emu.call("input", {"op": "set", "ports": [{}]})
                if moved >= 40:
                    break
            if moved < 40:
                problems.append(f"D-pad changes at most {moved} pixels vs. hands-off (need >= 40)")
            else:
                ok(f"D-pad input changes {moved} pixels vs. hands-off")
    except RuntimeError as e:
        problems.append(f"emulator error: {str(e)[:200]}")
    finally:
        emu.close()
    return problems


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", required=True, choices=sorted(EXTS))
    ap.add_argument("--outputs", default="/task/outputs")
    ap.add_argument("--need-input", action="store_true")
    ap.add_argument("--colour", choices=["red", "darkblue", "green"])
    ap.add_argument("--title", help="Game Boy header title must contain this (spaces ignored)")
    a = ap.parse_args()
    roms = sorted(p for p in Path(a.outputs).rglob("*") if p.is_file() and p.suffix.lower() in EXTS[a.platform])
    if not roms:
        fail(f"no {'/'.join(EXTS[a.platform])} ROM found in {a.outputs}")
    report: list[str] = []
    for rom in roms:
        b = rom.read_bytes()
        probs = header_problems(a.platform, b)
        if a.title and a.platform == "gb" and not probs:
            t = gb_title(b)
            if a.title.replace(" ", "").upper() not in t.replace(" ", "").upper():
                probs.append(f"header title is '{t}', expected '{a.title}'")
        if probs:
            report.append(f"{rom.name}: " + "; ".join(probs))
            continue
        ok(f"{rom.name}: header valid ({len(b)} bytes)")
        with tempfile.TemporaryDirectory() as td:
            probs = play_checks(a.platform, rom, a.need_input, a.colour, Path(td))
        if not probs:
            print("PASS:", rom.name)
            sys.exit(0)
        report.append(f"{rom.name}: " + "; ".join(probs))
    fail(" | ".join(report))


if __name__ == "__main__":
    main()
