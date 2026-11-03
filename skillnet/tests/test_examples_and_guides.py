"""list_game_examples and read_platform_guide against the installed example library."""

from __future__ import annotations

import json

import pytest
from conftest import env, out_path
from skillnet_sdk import call_tool

from tools.game_tools import list_game_examples, read_platform_guide


@pytest.mark.parametrize("plat", ["nes", "gb", "gbc", "genesis"])
def test_lists_genre_games_per_console(plat, out_root):
    r = env(call_tool(list_game_examples, {"platform": plat}, output_root=out_root))
    assert r["status"] == "ok"
    ex = r["data"]["examples"]
    games = [e for e in ex if e["kind"] == "game"]
    assert len(games) >= 5
    assert all(e["id"].startswith(plat + "/") and e["platform"] == plat for e in ex)
    genres = {e["genre"] for e in games}
    assert {"platformer", "shmup", "puzzle", "sports", "racing"} <= genres
    music = "genesis/xgm2_demo" if plat == "genesis" else f"{plat}/music_demo"
    assert music in {e["id"] for e in ex}
    assert r["data"]["guides"] == ["mental-model", "troubleshooting", "upstream-sources"]
    full = json.loads(out_path(r, "examples.json").read_text())
    assert len(full) == len(ex)


def test_all_consoles_and_data_size(out_root):
    r = env(call_tool(list_game_examples, {}, output_root=out_root))
    assert r["status"] == "ok"
    plats = {e["platform"] for e in r["data"]["examples"]}
    assert plats == {"nes", "gb", "gbc", "genesis"}
    assert len(r["data"]["examples"]) >= 30
    assert len(json.dumps(r["data"])) < 16000  # stays inline


def test_unknown_console_is_rejected(out_root):
    r = env(call_tool(list_game_examples, {"platform": "snes"}, output_root=out_root))
    assert r["status"] == "error"
    assert r["error"]["code"] == "invalid_arguments"


def test_guide_text_and_paging(out_root):
    r = env(call_tool(read_platform_guide, {"platform": "nes", "name": "mental-model", "max_chars": 2000}, output_root=out_root))
    assert r["status"] == "ok"
    d = r["data"]
    assert len(d["text"]) == 2000 and d["truncated"] and d["next_offset"] == 2000
    assert d["total_chars"] > 10000
    full = out_path(r, "nes-mental-model.md").read_text()
    assert len(full) == d["total_chars"] and full.startswith(d["text"])
    r2 = env(call_tool(read_platform_guide, {"platform": "nes", "name": "mental-model", "offset": d["total_chars"] - 100},
                       output_root=out_root))
    assert r2["data"]["truncated"] is False and r2["data"]["text"] == full[-100:]


def test_guide_name_is_forgiving_about_spelling(out_root):
    r = env(call_tool(read_platform_guide, {"platform": "genesis", "name": "Troubleshooting"}, output_root=out_root))
    assert r["status"] == "ok" and r["data"]["name"] == "troubleshooting"
    assert "sprite" in r["data"]["text"].lower()


def test_unknown_guide_lists_names(out_root):
    r = env(call_tool(read_platform_guide, {"platform": "gb", "name": "sound"}, output_root=out_root))
    assert r["status"] == "error"
    assert r["error"]["code"] == "unknown_guide"
    assert "mental-model" in r["next_step"] and "troubleshooting" in r["next_step"]


def test_known_broken_example_is_flagged(out_root):
    r = env(call_tool(list_game_examples, {"platform": "gb"}, output_root=out_root))
    puzzle = next(e for e in r["data"]["examples"] if e["id"] == "gb/puzzle")
    assert puzzle["description"].startswith("Known issue") and "gbc/puzzle" in puzzle["description"]
