"""Engine helpers for Retro Game Forge.

The real work is done by the romdev tool server (WASM builds of cc65, SDCC/RGBDS and the SGDK m68k
gcc, plus the fceumm, gambatte and genesis_plus_gx libretro cores). It runs on Node 24 as a
loopback-only HTTP server; this module starts it once per sandbox, keeps it alive between calls,
and talks to it with plain JSON requests. Everything else here (ROM header checks, picture
analysis, project zips, safe paths) is plain Python.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from skillnet_sdk import ToolError

NODE = os.environ.get("RETROFORGE_NODE", "/opt/node24/bin/node")
ROMDEV_ROOT = Path(os.environ.get("RETROFORGE_ROMDEV", "/opt/romdev/node_modules/romdevtools"))
SERVER_JS = ROMDEV_ROOT / "src" / "mcp" / "server.js"
GUIDE_ROOT = ROMDEV_ROOT / "src" / "platforms"

PLATFORMS: dict[str, dict[str, Any]] = {
    "nes": {"label": "NES", "ext": ".nes", "core": "fceumm", "toolchain": "cc65 (C / 6502 asm)"},
    "gb": {"label": "Game Boy", "ext": ".gb", "core": "gambatte", "toolchain": "SDCC + RGBDS (C / SM83 asm)"},
    "gbc": {"label": "Game Boy Color", "ext": ".gbc", "core": "gambatte", "toolchain": "SDCC + RGBDS (C / SM83 asm)"},
    "genesis": {"label": "Genesis / Mega Drive", "ext": ".md", "core": "genesis_plus_gx",
                "toolchain": "SGDK m68k gcc (C / 68000 asm)"},
}

GUIDES = {
    "mental-model": "MENTAL_MODEL.md",
    "troubleshooting": "TROUBLESHOOTING.md",
    "upstream-sources": "UPSTREAM_SOURCES.md",
}

META_FILE = ".retroforge.json"
VENDOR_DIRS = ("vendor", "include")
STATE_PROJECT = "project"
STATE_META = "meta.json"
STATE_ROM_DIR = "rom"

# ---------------------------------------------------------------------------------------------
# The romdev server
# ---------------------------------------------------------------------------------------------

_lock = threading.Lock()
_proc: subprocess.Popen[bytes] | None = None
_port: int | None = None
_LOG = Path("/tmp/retroforge-romdev.log")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _alive(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/openapi.json", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _stop() -> None:
    global _proc, _port
    if _proc is not None:
        try:
            os.killpg(_proc.pid, signal.SIGTERM)
        except Exception:
            pass
        try:
            _proc.wait(timeout=5)
        except Exception:
            try:
                os.killpg(_proc.pid, signal.SIGKILL)
            except Exception:
                pass
    _proc = None
    _port = None


atexit.register(_stop)


def ensure_server() -> int:
    """Start the romdev server if it isn't running; return its port."""
    global _proc, _port
    with _lock:
        if _proc is not None and _proc.poll() is None and _port is not None and _alive(_port):
            return _port
        _stop()
        if not SERVER_JS.is_file() or not Path(NODE).is_file():
            raise ToolError(
                "engine_missing",
                "The game toolchain and emulator are not installed in this environment.",
                "This skill's environment is broken; report it to the skill owner.",
            )
        port = _free_port()
        env = {**os.environ, "PORT": str(port), "HOST": "127.0.0.1",
               "PATH": f"{Path(NODE).parent}:{os.environ.get('PATH', '')}"}
        log = _LOG.open("ab")
        _proc = subprocess.Popen(
            [NODE, str(SERVER_JS)], env=env, stdout=log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True, cwd="/tmp",
        )
        deadline = time.time() + 60
        while time.time() < deadline:
            if _proc.poll() is not None:
                break
            if _alive(port):
                _port = port
                return port
            time.sleep(0.2)
        _stop()
        raise ToolError(
            "engine_failed",
            "The game toolchain server did not start.",
            "Call the tool again once; if it fails again, report it to the skill owner.",
        )


class Romdev:
    """One tool call's conversation with the romdev server (its own emulator session)."""

    def __init__(self, session: str) -> None:
        self.session = re.sub(r"[^A-Za-z0-9_-]", "-", session)[:60] or "retroforge"
        self.port = ensure_server()

    def call(self, tool: str, args: dict[str, Any], timeout: float = 120) -> dict[str, Any]:
        body = json.dumps(args).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/tool/{tool}", data=body, method="POST",
            headers={"content-type": "application/json", "x-romdev-session": self.session},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raw = e.read()
        except (TimeoutError, socket.timeout):
            _stop()  # a hung engine is restarted on the next call
            raise ToolError(
                "timeout",
                f"The emulator/toolchain took longer than {int(timeout)} s and was stopped.",
                "Retry with fewer frames or a smaller change; if it keeps happening the game may "
                "be stuck in an endless loop at boot.",
            ) from None
        except urllib.error.URLError:
            _stop()
            raise ToolError(
                "engine_failed",
                "The game toolchain server stopped responding.",
                "Call the tool again; the server restarts automatically.",
            ) from None
        try:
            out = json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            out = {"error": raw.decode("utf-8", "replace")[:500]}
        if not isinstance(out, dict):
            out = {"value": out}
        return out

    def checked(self, tool: str, args: dict[str, Any], what: str, timeout: float = 120) -> dict[str, Any]:
        out = self.call(tool, args, timeout)
        if out.get("error") and len(out) <= 3:
            raise ToolError(
                "engine_failed",
                f"The emulator could not {what}: {strip_ansi(str(out['error']))[:300]}",
                "Check the ROM/project is for the right console; rebuild with build_and_run_game "
                "and try again.",
            )
        return out

    def close(self) -> None:
        try:
            self.call("host", {"op": "shutdown"}, timeout=15)
        except Exception:
            pass


# ---------------------------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------------------------

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def strip_ansi(s: str) -> str:
    return _ANSI.sub("", s)


def safe_rel(root: Path, rel: str) -> Path:
    """Resolve a project-relative path, refusing anything that leaves the project."""
    rel = (rel or "").strip().replace("\\", "/")
    if not rel or rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
        raise ToolError(
            "invalid_path",
            f"'{rel}' is not a project-relative path.",
            "Use paths relative to the project root, e.g. 'main.c' or 'src/level.h'.",
        )
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts) or not parts:
        raise ToolError(
            "invalid_path",
            f"'{rel}' points outside the project.",
            "Use paths inside the project, without '..'.",
        )
    if parts[0] in (META_FILE,):
        raise ToolError("invalid_path", f"'{rel}' is managed by the skill.", "Pick another file name.")
    target = (root / "/".join(parts)).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ToolError("invalid_path", f"'{rel}' points outside the project.", "Use paths inside the project.")
    return target


def project_files(root: Path, include_vendor: bool = False) -> list[dict[str, Any]]:
    files = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        rel = p.relative_to(root).as_posix()
        if rel == META_FILE:
            continue
        if not include_vendor and rel.split("/")[0] in VENDOR_DIRS and "/" in rel:
            continue
        files.append({"path": rel, "bytes": p.stat().st_size})
    return files


def count_all_files(root: Path) -> int:
    return sum(1 for p in root.rglob("*") if p.is_file() and p.name != META_FILE)


def source_hash(root: Path) -> str:
    h = hashlib.sha1()
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            h.update(p.relative_to(root).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def main_source(root: Path) -> str | None:
    for name in ("main.c", "main.s", "main.asm"):
        if (root / name).is_file():
            return name
    return None


def zip_project(root: Path, dest: Path, meta: dict[str, Any]) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(META_FILE, json.dumps({k: meta.get(k) for k in ("platform", "name", "example")}, indent=1))
        for p in sorted(root.rglob("*")):
            if p.is_file() and not p.is_symlink() and p.name != META_FILE:
                z.write(p, p.relative_to(root).as_posix())
    return dest


MAX_ZIP_FILES = 5000
MAX_ZIP_BYTES = 300 * 1024 * 1024


def unzip_project(zpath: Path, root: Path) -> dict[str, Any]:
    """Unpack an untrusted project zip safely. Returns its saved meta (may be empty)."""
    try:
        z = zipfile.ZipFile(zpath)
    except zipfile.BadZipFile:
        raise ToolError(
            "unsupported_input",
            "The project file is not a readable .zip archive.",
            "Pass the project .zip that start_game_project or build_and_run_game returned.",
        ) from None
    with z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        if len(infos) > MAX_ZIP_FILES or sum(i.file_size for i in infos) > MAX_ZIP_BYTES:
            raise ToolError(
                "unsupported_input",
                "The project archive is too large (over 5000 files or 300 MB unpacked).",
                "Pass a game project zip from this skill, not a whole disk or SDK.",
            )
        names = [i.filename.replace("\\", "/") for i in infos]
        prefix = ""
        tops = {n.split("/")[0] for n in names}
        if len(tops) == 1 and all("/" in n for n in names):
            prefix = next(iter(tops)) + "/"
        meta: dict[str, Any] = {}
        root.mkdir(parents=True, exist_ok=True)
        rr = root.resolve()
        for info, name in zip(infos, names):
            rel = name[len(prefix):] if prefix and name.startswith(prefix) else name
            if not rel or rel.startswith("/") or ".." in rel.split("/") or re.match(r"^[A-Za-z]:", rel):
                continue
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                continue  # symlink entries are skipped
            if rel == META_FILE:
                try:
                    meta = json.loads(z.read(info).decode("utf-8"))
                except Exception:
                    meta = {}
                continue
            target = (root / rel).resolve()
            if not target.is_relative_to(rr):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    return meta if isinstance(meta, dict) else {}


def guess_platform(root: Path) -> str | None:
    """Work out a project's console from its runtime files (for zips without saved meta)."""
    if (root / "nes_runtime.c").exists() or any(root.glob("*.cfg")):
        return "nes"
    if (root / "md.ld").exists() or (root / "sega.s").exists() or (root / "rom_header.c").exists():
        return "genesis"
    if (root / "gb_crt0.s").exists() or (root / "gb_hardware.h").exists():
        return "gb"  # Game Boy vs Color can't be told from the files; callers say so
    return None


# ---------------------------------------------------------------------------------------------
# ROM headers
# ---------------------------------------------------------------------------------------------

GB_LOGO = bytes.fromhex(
    "CEED6666CC0D000B03730083000C000D0008111F8889000EDCCC6EE6DDDDD999BBBB67636E0EECCCDDDC999FBBB9333E"
)


def check_header(platform: str, data: bytes) -> dict[str, Any]:
    """Validate the console header the hardware/emulators need. Returns {ok, problems, ...facts}."""
    problems: list[str] = []
    info: dict[str, Any] = {}
    if platform == "nes":
        if data[:4] != b"NES\x1a":
            problems.append("missing iNES signature 'NES\\x1a'")
        else:
            prg, chr_ = data[4], data[5]
            trainer = 512 if data[6] & 4 else 0
            mapper = (data[6] >> 4) | (data[7] & 0xF0)
            need = 16 + trainer + prg * 16384 + chr_ * 8192
            info.update(format="iNES", prg_rom_kb=prg * 16, chr_rom_kb=chr_ * 8, mapper=mapper)
            if prg == 0:
                problems.append("iNES header declares 0 PRG-ROM banks")
            if len(data) < need:
                problems.append(f"file is {len(data)} bytes, header needs {need}")
    elif platform in ("gb", "gbc"):
        if len(data) < 0x150:
            problems.append("file is smaller than a Game Boy header")
        else:
            if data[0x104:0x134] != GB_LOGO:
                problems.append("Nintendo logo bytes at $0104 are wrong (real hardware refuses to boot)")
            x = 0
            for b in data[0x134:0x14D]:
                x = (x - b - 1) & 0xFF
            if x != data[0x14D]:
                problems.append(f"header checksum $014D is {data[0x14D]:02X}, should be {x:02X}")
            g = (sum(data) - data[0x14E] - data[0x14F]) & 0xFFFF
            stored = (data[0x14E] << 8) | data[0x14F]
            cgb = data[0x143]
            info.update(
                title=data[0x134:0x143].split(b"\x00")[0].decode("ascii", "replace").strip(),
                cgb_flag=f"{cgb:02X}", color_support=("cgb-only" if cgb == 0xC0 else "cgb-enhanced" if cgb == 0x80 else "dmg"),
                cart_type=f"{data[0x147]:02X}", global_checksum_ok=(g == stored),
            )
            if g != stored:
                problems.append("global checksum mismatch (boot ROMs and emulators ignore it)")
    elif platform == "genesis":
        if len(data) < 0x200:
            problems.append("file is smaller than a Genesis header")
        else:
            if data[0x100:0x104] != b"SEGA":
                problems.append("no 'SEGA' system string at $100 (TMSS consoles refuse to boot)")
            body = data[0x200:]
            if len(body) % 2:
                body = body + b"\x00"
            s = 0
            for i in range(0, len(body), 2):
                s += (body[i] << 8) | body[i + 1]
            s &= 0xFFFF
            stored = (data[0x18E] << 8) | data[0x18F]
            info.update(
                system=data[0x100:0x110].decode("ascii", "replace").strip(),
                title=data[0x150:0x180].decode("ascii", "replace").strip(),
                checksum_ok=(s == stored),
            )
            if s != stored:
                problems.append(f"checksum at $18E is {stored:04X}, should be {s:04X}")
    ok = not [p for p in problems if "global checksum" not in p]
    return {"ok": ok, "problems": problems, **info}


def finish_gb_header(data: bytes, title: str) -> tuple[bytes, list[str]]:
    """Fill the Game Boy title and recompute both checksums, as rgbfix -t -v would.

    romdev's build leaves the title window at the linker's $FF padding and, for .gb, edits $0143
    after rgbfix ran, which leaves the global checksum stale. Only header-window bytes change."""
    if len(data) < 0x150 or data[0x104:0x134] != GB_LOGO:
        return data, []
    b = bytearray(data)
    fixed: list[str] = []
    want = re.sub(r"[^A-Z0-9 ]", "", title.upper().replace("_", " "))[:11].encode("ascii")
    if b[0x134:0x13F].rstrip(b"\x00") != want or any(x == 0xFF for x in b[0x134:0x143]):
        b[0x134:0x13F] = want.ljust(11, b"\x00")
        for i in range(0x13F, 0x143):
            if b[i] == 0xFF:
                b[i] = 0x00
        fixed.append(f"title set to '{want.decode()}'")
    x = 0
    for v in b[0x134:0x14D]:
        x = (x - v - 1) & 0xFF
    if b[0x14D] != x:
        b[0x14D] = x
        fixed.append("header checksum recomputed")
    g = (sum(b) - b[0x14E] - b[0x14F]) & 0xFFFF
    if ((b[0x14E] << 8) | b[0x14F]) != g:
        b[0x14E], b[0x14F] = g >> 8, g & 0xFF
        fixed.append("global checksum recomputed")
    return bytes(b), fixed


def detect_rom_platform(path: Path, data: bytes, hint: str | None, signature_only: bool = False) -> str | None:
    """Console of a ROM: the hint if given, else its header signature, else (unless signature_only) its extension."""
    if hint:
        return hint
    ext = path.suffix.lower()
    if data[:4] == b"NES\x1a":
        return "nes"
    if len(data) >= 0x134 and data[0x104:0x134] == GB_LOGO:
        if ext == ".gbc" or data[0x143] in (0x80, 0xC0):
            return "gbc"
        return "gb"
    if len(data) >= 0x104 and data[0x100:0x104] == b"SEGA":
        return "genesis"
    if signature_only:
        return None
    return {".nes": "nes", ".gb": "gb", ".gbc": "gbc", ".md": "genesis", ".gen": "genesis"}.get(ext)


# ---------------------------------------------------------------------------------------------
# Pictures
# ---------------------------------------------------------------------------------------------


def load_rgb(path: Path):  # -> numpy array
    import numpy as np
    from PIL import Image

    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"))


def rendering_verdict(arr) -> dict[str, Any]:
    import numpy as np

    h, w, _ = arr.shape
    flat = arr.reshape(-1, 3).astype(np.uint32)
    keys = (flat[:, 0] << 16) | (flat[:, 1] << 8) | flat[:, 2]
    vals, counts = np.unique(keys, return_counts=True)
    i = int(np.argmax(counts))
    dom = int(vals[i])
    dom_pct = round(float(counts[i]) * 100.0 / len(keys), 2)
    non_dom = int(len(keys) - counts[i])
    blank = len(vals) <= 1 or non_dom < 32
    return {
        "blank": bool(blank),
        "unique_colors": int(len(vals)),
        "dominant_color": f"#{dom:06x}",
        "dominant_pct": dom_pct,
        "non_dominant_pixels": non_dom,
        "width": int(w),
        "height": int(h),
    }


def changed_pixels(a, b) -> int:
    if a is None or b is None:
        return 0
    if a.shape != b.shape:
        return int(max(a.shape[0] * a.shape[1], b.shape[0] * b.shape[1]))
    return int((a != b).any(axis=2).sum())


def changed_box(a, b) -> list[int] | None:
    """Bounding box [x, y, w, h] of the pixels that differ."""
    import numpy as np

    if a is None or b is None or a.shape != b.shape:
        return None
    m = (a != b).any(axis=2)
    if not m.any():
        return None
    ys, xs = np.nonzero(m)
    return [int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)]


def write_gif(frames: list[Path], dest: Path, frame_ms: int, scale: int = 1) -> int:
    """Animated GIF at the console's native screen size. Frames of another size (a boot frame drawn
    in a different video mode) are fitted to the most common size so nothing is cropped."""
    from collections import Counter

    from PIL import Image

    rgbs = []
    for p in frames:
        with Image.open(p) as im:
            rgbs.append(im.convert("RGB"))
    if not rgbs:
        return 0
    w, h = Counter(im.size for im in rgbs).most_common(1)[0][0]
    ims = []
    for rgb in rgbs:
        if rgb.size != (w, h):
            rgb = rgb.resize((w, h), Image.Resampling.NEAREST)
        if scale > 1:
            rgb = rgb.resize((w * scale, h * scale), Image.Resampling.NEAREST)
        ims.append(rgb.quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE))
    ims[0].save(dest, save_all=True, append_images=ims[1:], duration=max(20, frame_ms), loop=0, optimize=False)
    return len(ims)


# ---------------------------------------------------------------------------------------------
# Build issue parsing
# ---------------------------------------------------------------------------------------------


def clean_issue_path(f: str | None, project_root: Path | None = None) -> str | None:
    if not f:
        return f
    f = str(f)
    for pre in ("/work/", str(project_root) + "/" if project_root else None):
        if pre and f.startswith(pre):
            return f[len(pre):]
    return Path(f).name if f.startswith("/") else f


def parse_log_errors(log: str) -> list[dict[str, Any]]:
    """Fallback: pull file:line: error lines out of a raw build log."""
    out = []
    for m in re.finditer(r"([\w./-]+\.(?:c|h|s|asm|inc))[:(](\d+)(?:[:,](\d+))?\)?:?\s*(?:fatal )?(error|Error)[:\s]+(.+)", log):
        out.append({"file": clean_issue_path(m.group(1)), "line": int(m.group(2)),
                    "col": int(m.group(3)) if m.group(3) else None, "severity": "error",
                    "message": m.group(5).strip()[:300], "stage": None})
        if len(out) >= 20:
            break
    return out


_SECTION = re.compile(r"^--- ([\w.+-]+)[^()]*?(?: \(([^)]+?)(?: \u2192 [^)]*)?\))? ---\s*$")
_FAILED_TU = re.compile(r"FAILED on TU '([^']+)'")


def attribute_issue_files(log: str, issues: list[dict[str, Any]]) -> None:
    """Fix file names in build issues, in place.

    The WASM compilers compile every translation unit as /work/main.c, so an error in level.c is
    reported as main.c. The build log brackets each unit with '--- cc65 (level.c) ---' style
    headers; use them to put the real file name back."""
    cur: str | None = None
    entries: list[tuple[str | None, str]] = []
    for raw in log.splitlines():
        line = raw.strip()
        m = _SECTION.match(line)
        if m:
            if m.group(2):
                cur = m.group(2).strip()
            continue
        f = _FAILED_TU.search(line)
        if f:
            cur = f.group(1)
        entries.append((cur, raw))
    used: set[int] = set()
    for it in issues:
        if it.get("file") != "main.c" or not it.get("line"):
            continue
        key = f"main.c:{it['line']}:"
        msg = str(it.get("message") or "")[:30]
        hit = None
        for strict in (True, False):
            for idx, (_, txt) in enumerate(entries):
                if idx in used or key not in txt:
                    continue
                if strict and msg and msg not in txt:
                    continue
                hit = idx
                break
            if hit is not None:
                break
        if hit is None:
            continue
        used.add(hit)
        real = entries[hit][0]
        if real and real != "main.c" and re.search(r"\.c$", real):
            it["file"] = real
