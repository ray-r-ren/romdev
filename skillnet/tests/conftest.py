"""Shared fixtures: real forks and builds of the bundled examples (no network needed).

Each platform's example is forked and built once per test session; tests that change a project
work on a copy of its state directory.
"""

from __future__ import annotations

import pathlib
import shutil
import sys
import zipfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from skillnet_sdk import call_tool  # noqa: E402

from tools.game_tools import build_and_run_game, start_game_project  # noqa: E402

EXAMPLES = {"nes": "nes/platformer", "gb": "gb/platformer", "genesis": "genesis/platformer"}


def env(e) -> dict:
    return e.model_dump() if hasattr(e, "model_dump") else e


def out_path(result: dict, name: str) -> pathlib.Path:
    for o in result.get("outputs") or []:
        if o["name"] == name:
            return pathlib.Path(o["path"])
    raise AssertionError(f"no output named {name}: {[o['name'] for o in result.get('outputs') or []]}")


@pytest.fixture(scope="session")
def out_root(tmp_path_factory) -> pathlib.Path:
    return tmp_path_factory.mktemp("outputs")


@pytest.fixture(scope="session")
def built(tmp_path_factory, out_root):
    """{platform: {"state": Path, "start": envelope, "build": envelope}} for nes, gb and genesis."""
    res = {}
    for plat, ex in EXAMPLES.items():
        st = tmp_path_factory.mktemp(f"state-{plat}")
        start = env(call_tool(start_game_project, {"example": ex, "name": "testgame"}, output_root=out_root, state_dir=st))
        assert start["status"] == "ok", start
        build = env(call_tool(build_and_run_game, {"frames": 120}, output_root=out_root, state_dir=st))
        res[plat] = {"state": st, "start": start, "build": build}
    return res


@pytest.fixture
def state_copy(built, tmp_path):
    """Return a function giving a private copy of a platform's built state directory."""

    def make(plat: str) -> pathlib.Path:
        dst = tmp_path / f"state-{plat}"
        shutil.copytree(built[plat]["state"], dst)
        return dst

    return make


@pytest.fixture
def make_zip(tmp_path):
    def make(name: str, entries: dict[str, bytes | str]) -> pathlib.Path:
        p = tmp_path / name
        with zipfile.ZipFile(p, "w") as z:
            for k, v in entries.items():
                z.writestr(k, v)
        return p

    return make
