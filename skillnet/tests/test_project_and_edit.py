"""start_game_project and edit_game_files: forking, resuming, editing, reading, path safety."""

from __future__ import annotations

import json
import zipfile

from conftest import env, out_path
from skillnet_sdk import call_tool

from tools.game_tools import edit_game_files, start_game_project


def test_fork_gives_editable_c_project(built):
    r = built["nes"]["start"]
    d = r["data"]
    assert d["platform"] == "nes" and d["example"] == "nes/platformer" and d["name"] == "testgame"
    paths = {f["path"] for f in d["files"]}
    assert d["main_source"] == "main.c" and "main.c" in paths and "nes_runtime.c" in paths
    z = zipfile.ZipFile(out_path(r, "testgame-project.zip"))
    names = set(z.namelist())
    assert "main.c" in names and ".retroforge.json" in names
    assert json.loads(z.read(".retroforge.json"))["platform"] == "nes"


def test_genesis_fork_hides_library_folders(built):
    d = built["genesis"]["start"]["data"]
    assert d["vendor_file_count"] > 50
    assert not any(f["path"].startswith(("vendor/", "include/")) for f in d["files"])


def test_unknown_example_lists_real_ids(tmp_path, out_root):
    r = env(call_tool(start_game_project, {"example": "nes/rpg"}, output_root=out_root, state_dir=tmp_path / "s"))
    assert r["status"] == "error" and r["error"]["code"] == "unknown_example"
    assert "nes/platformer" in r["next_step"]
    r = env(call_tool(start_game_project, {"example": "snes/platformer"}, output_root=out_root, state_dir=tmp_path / "s2"))
    assert r["error"]["code"] == "unknown_example"
    r = env(call_tool(start_game_project, {}, output_root=out_root, state_dir=tmp_path / "s3"))
    assert r["error"]["code"] == "invalid_arguments"


def test_bad_name_rejected(tmp_path, out_root):
    r = env(call_tool(start_game_project, {"example": "gb/puzzle", "name": "../x"}, output_root=out_root, state_dir=tmp_path / "s"))
    assert r["status"] == "error" and r["error"]["code"] == "invalid_arguments"


def test_resume_from_project_zip(built, tmp_path, out_root):
    z = out_path(built["gb"]["start"], "testgame-project.zip")
    st = tmp_path / "resumed"
    r = env(call_tool(start_game_project, {"project_zip": str(z)}, output_root=out_root, state_dir=st))
    assert r["status"] == "ok", r
    assert r["data"]["platform"] == "gb" and r["data"]["name"] == "testgame"
    assert (st / "project" / "main.c").read_bytes() == zipfile.ZipFile(z).read("main.c")


def test_zip_without_meta_infers_console(make_zip, tmp_path, out_root):
    z = make_zip("loose.zip", {"mygame/main.c": "void main(void){}\n", "mygame/nes_runtime.c": "", "mygame/x.cfg": ""})
    r = env(call_tool(start_game_project, {"project_zip": str(z)}, output_root=out_root, state_dir=tmp_path / "s"))
    assert r["status"] == "ok" and r["data"]["platform"] == "nes"
    assert any("inferred" in u for u in r["uncertain"])


def test_bad_zips_are_refused(make_zip, tmp_path, out_root):
    notzip = tmp_path / "fake.zip"
    notzip.write_text("not a zip")
    r = env(call_tool(start_game_project, {"project_zip": str(notzip)}, output_root=out_root, state_dir=tmp_path / "a"))
    assert r["error"]["code"] == "unsupported_input" and r["next_step"]
    nomain = make_zip("nomain.zip", {"readme.txt": "hi"})
    r = env(call_tool(start_game_project, {"project_zip": str(nomain)}, output_root=out_root, state_dir=tmp_path / "b"))
    assert r["error"]["code"] == "unsupported_input"


def test_zip_traversal_entries_are_skipped(make_zip, tmp_path, out_root):
    z = make_zip("evil.zip", {"main.c": "void main(void){}\n", "../escape.c": "x", "gb_crt0.s": ""})
    st = tmp_path / "s"
    r = env(call_tool(start_game_project, {"project_zip": str(z), "platform": "gb"}, output_root=out_root, state_dir=st))
    assert r["status"] == "ok"
    assert not (tmp_path / "escape.c").exists() and not (st / "escape.c").exists()


def test_replace_then_read_back(state_copy, out_root):
    st = state_copy("nes")
    src = (st / "project" / "main.c").read_text()
    assert "void main(void) {" in src
    r = env(call_tool(edit_game_files, {"replacements": [{"path": "main.c", "find": "void main(void) {",
                                                          "replace": "/* edited */\nvoid main(void) {"}],
                                        "search": ["/* edited */"]}, output_root=out_root, state_dir=st))
    assert r["status"] == "ok" and r["data"]["replacements"][0]["applied"] == 1
    hit = r["data"]["search_hits"][0]
    assert hit["file"] == "main.c"
    r = env(call_tool(edit_game_files, {"read": [{"path": "main.c", "start_line": hit["line"], "line_count": 2}]},
                      output_root=out_root, state_dir=st))
    rd = r["data"]["reads"][0]
    assert rd["start_line"] == hit["line"] and rd["end_line"] == hit["line"] + 1
    assert "/* edited */" in rd["text"] and "void main(void)" in rd["text"]


def test_write_new_file_and_delete(state_copy, out_root):
    st = state_copy("gb")
    r = env(call_tool(edit_game_files, {"writes": [{"path": "levels/level1.h", "content": "#define LEVEL 1\n"}]},
                      output_root=out_root, state_dir=st))
    assert r["data"]["written"] == ["levels/level1.h"]
    assert (st / "project" / "levels" / "level1.h").read_text() == "#define LEVEL 1\n"
    r = env(call_tool(edit_game_files, {"deletes": ["levels/level1.h"]}, output_root=out_root, state_dir=st))
    assert r["data"]["deleted"] == ["levels/level1.h"]
    assert not (st / "project" / "levels" / "level1.h").exists()


def test_replacement_problems_are_reported(state_copy, out_root):
    st = state_copy("nes")
    r = env(call_tool(edit_game_files, {"replacements": [
        {"path": "main.c", "find": "NO_SUCH_TEXT_42", "replace": "x"},
        {"path": "main.c", "find": "uint8_t", "replace": "uint8_t"},
        {"path": "nope.c", "find": "a", "replace": "b"}]}, output_root=out_root, state_dir=st))
    assert r["status"] == "partial"
    probs = [x["problem"] for x in r["data"]["replacements"]]
    assert probs[0].startswith("text not found")
    assert "times" in probs[1] and "all=true" in probs[1]
    assert probs[2] == "file not found"
    assert r["data"]["not_applied"] == 3


def test_paths_cannot_leave_the_project(state_copy, out_root, tmp_path):
    st = state_copy("nes")
    for bad in ["../evil.c", "/etc/passwd", "a/../../b.c", "C:/x.c"]:
        r = env(call_tool(edit_game_files, {"writes": [{"path": bad, "content": "x"}]}, output_root=out_root, state_dir=st))
        assert r["status"] == "error" and r["error"]["code"] == "invalid_path", bad
    r = env(call_tool(edit_game_files, {"read": [{"path": "../meta.json"}]}, output_root=out_root, state_dir=st))
    assert r["error"]["code"] == "invalid_path"
    assert not (st / "evil.c").exists()


def test_edit_without_project_says_what_to_do(tmp_path, out_root):
    r = env(call_tool(edit_game_files, {"read": [{"path": "main.c"}]}, output_root=out_root, state_dir=tmp_path / "empty"))
    assert r["error"]["code"] == "no_project"
    assert "start_game_project" in r["next_step"]


def test_large_read_and_search_stay_inline(state_copy, out_root):
    st = state_copy("genesis")
    r = env(call_tool(edit_game_files, {"search": ["u16", "if", "{"],
                                        "read": [{"path": "main.c", "start_line": 1, "line_count": 400},
                                                 {"path": "main.c", "start_line": 401, "line_count": 400}]},
                      output_root=out_root, state_dir=st))
    assert r["status"] == "ok"
    assert len(json.dumps(r["data"])) < 16384
    assert r["data"]["reads"][0]["truncated"] is True
    assert any("not shown" in u for u in r["uncertain"])
