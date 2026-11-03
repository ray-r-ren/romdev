"""play_game: scripted input in the real emulator cores, input-effect measurement, memory reads."""

from __future__ import annotations

import shutil

import pytest
from conftest import env, out_path
from PIL import Image
from skillnet_sdk import call_tool

from tools.game_tools import play_game, start_game_project

START_THEN_MOVE = [{"buttons": [], "frames": 90}, {"buttons": ["start"], "frames": 10}, {"buttons": [], "frames": 60},
                   {"buttons": ["right"], "frames": 60}, {"buttons": ["a"], "frames": 15}]


@pytest.mark.parametrize("plat", ["nes", "gb", "genesis"])
def test_platformer_reacts_to_controls(state_copy, out_root, plat):
    st = state_copy(plat)
    r = env(call_tool(play_game, {"steps": START_THEN_MOVE}, output_root=out_root, state_dir=st))
    assert r["status"] == "ok", r
    d = r["data"]
    assert d["platform"] == plat and d["total_frames"] == 235
    assert d["responsive_to_input"] is True
    assert 4 in d["responsive_steps"]  # holding Right moves the player
    step4 = d["steps"][3]
    assert step4["input_effect_pixels"] > 0 and step4["effect_region"] is not None
    assert d["steps"][0]["input_effect_pixels"] is None  # idle steps have no control run
    assert d["final_rendering"]["blank"] is False
    for s in d["steps"]:
        with Image.open(out_path(r, s["screenshot"])) as im:
            assert im.width >= 160
    native = {"nes": (256, 224), "gb": (160, 144), "genesis": (320, 224)}[plat]
    with Image.open(out_path(r, "play.gif")) as g:
        assert g.size == native  # the GIF is at the console's own screen size, never cropped
        # Pillow merges identical consecutive frames when saving, so the file can hold fewer
        assert 10 < g.n_frames <= d["gif_frames"]


def test_effect_that_gets_undone_is_still_seen(state_copy, out_root):
    # gb/platformer: holding Right from the start walks into the first pit; the player dies and respawns
    # at the same spot, so the last frame alone looks like Right did nothing.
    st = state_copy("gb")
    r = env(call_tool(play_game, {"steps": START_THEN_MOVE[:4] + [{"buttons": ["a"], "frames": 10}]},
                      output_root=out_root, state_dir=st))
    step4 = r["data"]["steps"][3]
    assert step4["input_effect_pixels"] > 1000  # the screen scrolled while Right was held
    assert step4["input_effect_end_pixels"] < 100 and step4["input_effect_at_frame"] is not None
    assert 4 in r["data"]["responsive_steps"]
    assert any("undone" in u for u in r["uncertain"])
    assert any("respawn" in u for u in r["uncertain"])  # the A press right after lands in the respawn pause


def test_same_script_gives_same_pictures(state_copy, out_root):
    st = state_copy("nes")
    steps = START_THEN_MOVE[:4]
    a = env(call_tool(play_game, {"steps": steps, "gif": False}, output_root=out_root, state_dir=st))
    b = env(call_tool(play_game, {"steps": steps, "gif": False}, output_root=out_root, state_dir=st))
    assert out_path(a, "step04.png").read_bytes() == out_path(b, "step04.png").read_bytes()
    assert "play.gif" not in [o["name"] for o in a["outputs"]]


def test_uploaded_rom_and_memory_read(built, tmp_path, out_root):
    rom = tmp_path / "upload.gb"
    shutil.copy(out_path(built["gb"]["build"], "testgame.gb"), rom)
    r = env(call_tool(play_game, {"rom": str(rom), "steps": [{"buttons": [], "frames": 60}],
                                  "read_memory": [{"address": "0xC000", "length": 16},
                                                  {"address": 0, "length": 8, "region": "sprites"}]},
                      output_root=out_root, state_dir=tmp_path / "s"))
    assert r["status"] == "ok", r
    d = r["data"]
    assert d["platform"] == "gb" and d["rom"] == "upload.gb"
    assert d["responsive_to_input"] is None  # nothing was pressed
    assert any("not tested" in u for u in r["uncertain"])
    assert [m["region"] for m in d["memory"]] == ["work_ram", "sprites"]
    assert len(bytes.fromhex(d["memory"][0]["hex"])) == 16 and len(bytes.fromhex(d["memory"][1]["hex"])) == 8


def test_non_rom_upload_is_refused(tmp_path, out_root):
    fake = tmp_path / "game.nes"
    fake.write_bytes(b"this is not a cartridge" * 10)
    r = env(call_tool(play_game, {"rom": str(fake)}, output_root=out_root, state_dir=tmp_path / "s"))
    assert r["status"] == "error" and r["error"]["code"] == "unsupported_input"
    assert r["next_step"]


def test_wrong_buttons_and_addresses(state_copy, out_root):
    st = state_copy("genesis")
    r = env(call_tool(play_game, {"steps": [{"buttons": ["select"], "frames": 10}]}, output_root=out_root, state_dir=st))
    assert r["error"]["code"] == "invalid_button" and "c" in r["next_step"]
    r = env(call_tool(play_game, {"steps": [{"buttons": [], "frames": 10}], "read_memory": [{"address": "0x1234"}]},
                      output_root=out_root, state_dir=st))
    assert r["error"]["code"] == "invalid_address" and "FF0000" in r["next_step"]
    r = env(call_tool(play_game, {"steps": [{"buttons": [], "frames": 10}],
                                  "read_memory": [{"address": 0, "region": "sprites"}]}, output_root=out_root, state_dir=st))
    assert r["error"]["code"] == "invalid_region"


def test_play_before_build(tmp_path, out_root):
    st = tmp_path / "s"
    call_tool(start_game_project, {"example": "gb/puzzle"}, output_root=out_root, state_dir=st)
    r = env(call_tool(play_game, {}, output_root=out_root, state_dir=st))
    assert r["error"]["code"] == "no_rom" and "build_and_run_game" in r["next_step"]


def test_script_length_limit(state_copy, out_root):
    st = state_copy("nes")
    r = env(call_tool(play_game, {"steps": [{"buttons": [], "frames": 1800}] * 5}, output_root=out_root, state_dir=st))
    assert r["error"]["code"] == "too_long"
