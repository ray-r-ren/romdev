"""build_and_run_game with the real toolchains and emulator cores; headers checked independently."""

from __future__ import annotations

import pytest
from conftest import env, out_path
from PIL import Image
from skillnet_sdk import call_tool

from tools.game_tools import build_and_run_game, edit_game_files, start_game_project

NINTENDO_LOGO = bytes.fromhex(
    "CEED6666CC0D000B03730083000C000D0008111F8889000EDCCC6EE6DDDDD999BBBB67636E0EECCCDDDC999FBBB9333E")


def _distinct_colours(png) -> int:
    with Image.open(png) as im:
        return len(set(im.convert("RGB").getdata()))


@pytest.mark.parametrize("plat,ext", [("nes", ".nes"), ("gb", ".gb"), ("genesis", ".md")])
def test_builds_valid_rom_that_renders(built, plat, ext):
    r = built[plat]["build"]
    assert r["status"] == "ok", r
    d = r["data"]
    assert d["built"] and d["header_ok"] and d["errors"] == []
    rom = out_path(r, f"testgame{ext}").read_bytes()
    assert len(rom) == d["rom_bytes"]
    if plat == "nes":
        assert rom[:4] == b"NES\x1a"
        assert len(rom) >= 16 + rom[4] * 16384 + rom[5] * 8192
    elif plat == "gb":
        assert rom[0x104:0x134] == NINTENDO_LOGO
        x = 0
        for b in rom[0x134:0x14D]:
            x = (x - b - 1) & 0xFF
        assert rom[0x14D] == x
        assert ((rom[0x14E] << 8) | rom[0x14F]) == (sum(rom) - rom[0x14E] - rom[0x14F]) & 0xFFFF
        assert rom[0x134:0x13D] == b"TESTGAME\x00"
        assert rom[0x143] == 0x00  # plain Game Boy, not Color-only
    else:
        assert rom[0x100:0x104] == b"SEGA"
        body = rom[0x200:]
        s = sum((body[i] << 8) | body[i + 1] for i in range(0, len(body) - 1, 2)) & 0xFFFF
        assert ((rom[0x18E] << 8) | rom[0x18F]) == s
    shot = out_path(r, "screenshot.png")
    size = {"nes": (256, 224), "gb": (160, 144), "genesis": (320, 224)}[plat]
    with Image.open(shot) as im:
        assert im.size == size
    assert _distinct_colours(shot) >= 2
    assert d["rendering"]["blank"] is False
    assert out_path(r, "testgame-project.zip").stat().st_size > 1000


def test_syntax_error_reports_file_and_line(state_copy, out_root):
    st = state_copy("gb")
    src = (st / "project" / "main.c").read_text()
    line = src[: src.index("void main(void)")].count("\n") + 1
    r = env(call_tool(edit_game_files, {"replacements": [{"path": "main.c", "find": "void main(void)",
                                                          "replace": "int broken = ;\nvoid main(void)"}]},
                      output_root=out_root, state_dir=st))
    assert r["status"] == "ok"
    r = env(call_tool(build_and_run_game, {}, output_root=out_root, state_dir=st))
    assert r["status"] == "partial"
    d = r["data"]
    assert d["built"] is False and d["rom"] is None
    first = d["errors"][0]
    assert first["file"] == "main.c" and first["line"] == line
    assert "main.c:" in r["summary"]
    assert "build.log" in [o["name"] for o in r["outputs"]]
    assert not any(o["name"].endswith(".gb") for o in r["outputs"])


@pytest.mark.parametrize("plat,code,line", [
    ("nes", "#include <stdint.h>\nvoid probe(void) { uint8_t a = 1; a++; uint8_t b = a; }\n", 2),
    ("genesis", "#include <genesis.h>\n\nvoid probe(void) { u16 a = ; }\n", 3),
])
def test_errors_in_other_files_name_that_file(state_copy, out_root, plat, code, line):
    st = state_copy(plat)
    call_tool(edit_game_files, {"writes": [{"path": "probe.c", "content": code}]}, output_root=out_root, state_dir=st)
    r = env(call_tool(build_and_run_game, {}, output_root=out_root, state_dir=st))
    d = r["data"]
    assert d["built"] is False
    assert d["errors"][0]["file"] == "probe.c" and d["errors"][0]["line"] == line


def test_build_straight_from_zip(built, tmp_path, out_root):
    z = out_path(built["nes"]["start"], "testgame-project.zip")
    r = env(call_tool(build_and_run_game, {"project_zip": str(z), "frames": 60}, output_root=out_root,
                      state_dir=tmp_path / "fresh"))
    assert r["status"] == "ok" and r["data"]["built"] and r["data"]["platform"] == "nes"
    assert r["data"]["frames_run"] == 60


def test_blank_screen_is_flagged(state_copy, out_root):
    st = state_copy("nes")
    # Hang before anything is drawn: the ROM builds and boots but never turns the picture on.
    decl = "  uint8_t player_y;\n"  # last declaration in main(); cc65 wants statements after it
    r = env(call_tool(edit_game_files, {"replacements": [{"path": "main.c", "find": decl,
                                                          "replace": decl + "  for (;;) {}\n"}]},
                      output_root=out_root, state_dir=st))
    assert r["data"]["replacements"][0]["applied"] == 1, r
    r = env(call_tool(build_and_run_game, {"frames": 60}, output_root=out_root, state_dir=st))
    d = r["data"]
    assert d["built"] is True
    assert d["rendering"]["blank"] is True
    assert r["status"] == "partial"
    assert any("flat colour" in u for u in r["uncertain"])


def test_build_without_project(tmp_path, out_root):
    r = env(call_tool(build_and_run_game, {}, output_root=out_root, state_dir=tmp_path / "none"))
    assert r["status"] == "error" and r["error"]["code"] == "no_project"
    assert "start_game_project" in r["next_step"]


def test_game_boy_color_build_is_colour_rom(tmp_path, out_root):
    st = tmp_path / "state-gbc"
    start = env(call_tool(start_game_project, {"example": "gbc/puzzle", "name": "gemfall"}, output_root=out_root,
                          state_dir=st))
    assert start["status"] == "ok" and start["data"]["platform"] == "gbc", start
    r = env(call_tool(build_and_run_game, {"frames": 180}, output_root=out_root, state_dir=st))
    assert r["status"] == "ok", r
    d = r["data"]
    assert d["built"] and d["header_ok"] and d["rom"] == "gemfall.gbc"
    rom = out_path(r, "gemfall.gbc").read_bytes()
    assert rom[0x104:0x134] == NINTENDO_LOGO
    assert rom[0x143] in (0x80, 0xC0)  # Game Boy Color flag
    assert rom[0x134:0x13B] == b"GEMFALL"
    assert ((rom[0x14E] << 8) | rom[0x14F]) == (sum(rom) - rom[0x14E] - rom[0x14F]) & 0xFFFF
    shot = out_path(r, "screenshot.png")
    with Image.open(shot) as im:
        assert im.size == (160, 144)
        px = list(im.convert("RGB").getdata())
    saturated = sum(1 for c in px if max(c) - min(c) >= 60) / len(px)
    assert saturated > 0.05  # really drawn in colour, not four greys
    assert d["rendering"]["blank"] is False and d["rendering"]["unique_colors"] > 4
