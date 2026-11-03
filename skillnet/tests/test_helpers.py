"""Pure-Python parts: header checks, Game Boy header finishing, error attribution, picture verdicts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import yaml

from tools import romdev as rd


def _gb_rom(title: bytes = b"\xff" * 11) -> bytes:
    b = bytearray(b"\xff" * 0x8000)
    b[0x104:0x134] = rd.GB_LOGO
    b[0x134:0x13F] = title
    b[0x143] = 0
    b[0x14D] = 0  # deliberately wrong header checksum
    return bytes(b)


def test_nes_header_checks():
    good = b"NES\x1a" + bytes([2, 1, 0, 0]) + bytes(8) + bytes(2 * 16384 + 8192)
    h = rd.check_header("nes", good)
    assert h["ok"] and h["prg_rom_kb"] == 32 and h["chr_rom_kb"] == 8 and h["mapper"] == 0
    assert not rd.check_header("nes", good[:1000])["ok"]
    assert not rd.check_header("nes", b"XXXX" + good[4:])["ok"]


def test_gb_header_finishing_fixes_title_and_checksums():
    raw = _gb_rom()
    before = rd.check_header("gb", raw)
    assert not before["ok"]  # header checksum is wrong
    fixed, notes = rd.finish_gb_header(raw, "space_frog!")
    after = rd.check_header("gb", fixed)
    assert after["ok"] and after["global_checksum_ok"] and after["problems"] == []
    assert after["title"] == "SPACE FROG"
    assert fixed[0x150:] == raw[0x150:]  # only header bytes change
    assert any("global" in n for n in notes)
    again, notes2 = rd.finish_gb_header(fixed, "space_frog!")
    assert again == fixed and notes2 == []


def test_genesis_checksum():
    b = bytearray(0x400)
    b[0x100:0x110] = b"SEGA MEGA DRIVE "
    b[0x200:0x204] = b"\x12\x34\x00\x01"
    assert not rd.check_header("genesis", bytes(b))["ok"]
    b[0x18E:0x190] = (0x1235).to_bytes(2, "big")
    assert rd.check_header("genesis", bytes(b))["ok"]


def test_rom_platform_detection():
    assert rd.detect_rom_platform(Path("x.bin"), b"NES\x1a" + bytes(20), None) == "nes"
    gb = _gb_rom()
    assert rd.detect_rom_platform(Path("x.gb"), gb, None) == "gb"
    assert rd.detect_rom_platform(Path("x.gbc"), gb, None) == "gbc"
    assert rd.detect_rom_platform(Path("x.md"), b"junk" * 10, None, signature_only=True) is None
    assert rd.detect_rom_platform(Path("x.md"), b"junk" * 10, None) == "genesis"


def test_issue_files_are_attributed_from_log_sections():
    log = ("--- cc65 (main.c) ---\n(ok)\n--- cc65 (level.c) ---\n/work/main.c:7: Error: ';' expected\n"
           "--- sdcc (enemy.c) ---\n--- mcpp ---\n/work/main.c:3: syntax error: token -> ';'\n")
    issues = [{"file": "main.c", "line": 7, "message": "';' expected"},
              {"file": "main.c", "line": 3, "message": "syntax error: token -> ';'"},
              {"file": "util.h", "line": 1, "message": "x"}]
    rd.attribute_issue_files(log, issues)
    assert [i["file"] for i in issues] == ["level.c", "enemy.c", "util.h"]
    parsed = rd.parse_log_errors("--- cc1 (probe.c) ---\n/work/main.c:1:10: fatal error: stdint.h: No such file\n")
    assert parsed[0]["line"] == 1 and parsed[0]["col"] == 10 and "stdint.h" in parsed[0]["message"]


def test_rendering_verdict_and_pixel_diff():
    flat = np.zeros((144, 160, 3), dtype=np.uint8)
    assert rd.rendering_verdict(flat)["blank"] is True
    drawn = flat.copy()
    drawn[10:30, 10:30] = 255
    v = rd.rendering_verdict(drawn)
    assert v["blank"] is False and v["unique_colors"] == 2 and v["non_dominant_pixels"] == 400
    assert rd.changed_pixels(flat, drawn) == 400
    assert rd.changed_box(flat, drawn) == [10, 10, 20, 20]


def test_manifest_matches_tools():
    out = subprocess.run([sys.executable, "-m", "skillnet_sdk", "manifest", "--package", "tools"],
                         cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=True)
    names = {t["name"] for t in json.loads(out.stdout)}
    assert names == {"list_game_examples", "read_platform_guide", "start_game_project", "edit_game_files",
                     "build_and_run_game", "play_game"}
    skill = yaml.safe_load((Path(__file__).resolve().parents[1] / "skill.yaml").read_text())
    assert {t["name"] for t in skill["tools"]} == names
