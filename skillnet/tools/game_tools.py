"""Retro Game Forge tools: pick an example, fork it, edit it, build a real ROM, play-test it."""

from __future__ import annotations

import json
import math
import re
import shutil
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field

from skillnet_sdk import (
    FileConstraints,
    InputFile,
    OutputFile,
    ToolContext,
    ToolError,
    ToolInput,
    ToolOutput,
    ToolResult,
    tool,
)

from . import romdev as rd

STATE_VERSION = 1
PlatformName = Literal["nes", "gb", "gbc", "genesis"]
PLATFORM_WORDS = ("nes = NES/Famicom; gb = Game Boy; gbc = Game Boy Color; "
                  "genesis = Sega Genesis / Mega Drive")


# ---------------------------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------------------------


def _proj_root(ctx: ToolContext) -> Path:
    return ctx.state_dir / rd.STATE_PROJECT


def _read_meta(ctx: ToolContext) -> dict[str, Any]:
    p = ctx.state_dir / rd.STATE_META
    if p.is_file():
        try:
            m = json.loads(p.read_text())
            return m if isinstance(m, dict) else {}
        except Exception:
            return {}
    return {}


def _write_meta(ctx: ToolContext, meta: dict[str, Any]) -> None:
    (ctx.state_dir / rd.STATE_META).write_text(json.dumps(meta, indent=1))


def _wipe_state(ctx: ToolContext) -> None:
    for p in list(ctx.state_dir.iterdir()):
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
        else:
            p.unlink()


def _import_zip(ctx: ToolContext, zpath: Path, platform: str | None, name: str | None) -> tuple[dict[str, Any], list[str]]:
    uncertain: list[str] = []
    _wipe_state(ctx)
    root = _proj_root(ctx)
    meta = rd.unzip_project(zpath, root)
    if rd.main_source(root) is None:
        _wipe_state(ctx)
        raise ToolError(
            "unsupported_input",
            "The archive has no main.c, main.s or main.asm at its top level, so it is not a game project.",
            "Pass a project .zip returned by start_game_project or build_and_run_game, or start "
            "from an example with start_game_project.",
        )
    plat = platform or (meta.get("platform") if meta.get("platform") in rd.PLATFORMS else None)
    if plat is None:
        plat = rd.guess_platform(root)
        if plat is None:
            _wipe_state(ctx)
            raise ToolError(
                "unknown_platform",
                "Could not tell which console this project is for.",
                "Call again with platform set to nes, gb, gbc or genesis.",
            )
        uncertain.append(f"Console inferred as '{plat}' from the project's runtime files"
                         + (" (Game Boy and Game Boy Color projects look alike; pass platform='gbc' for Color)" if plat == "gb" else ""))
    nm = name or str(meta.get("name") or "game")
    nm = re.sub(r"[^A-Za-z0-9_]", "_", nm)[:24] or "game"
    m = {"platform": plat, "name": nm, "example": meta.get("example")}
    _write_meta(ctx, m)
    return m, uncertain


def _load_project(ctx: ToolContext, project_zip: Path | None, platform: str | None = None) -> tuple[Path, dict[str, Any], list[str]]:
    uncertain: list[str] = []
    if project_zip is not None:
        meta, uncertain = _import_zip(ctx, Path(project_zip), platform, None)
        return _proj_root(ctx), meta, uncertain
    root = _proj_root(ctx)
    meta = _read_meta(ctx)
    if not ctx.state_restored or not root.is_dir() or meta.get("platform") not in rd.PLATFORMS:
        raise ToolError(
            "no_project",
            "There is no game project in this call (no state_id from an earlier call and no project zip).",
            "Call start_game_project first (with an example id, or with project_zip to resume a saved "
            "project .zip) and pass the state_id it returns to this tool.",
        )
    return root, meta, uncertain


def _ext(platform: str) -> str:
    return str(rd.PLATFORMS[platform]["ext"])


# ---------------------------------------------------------------------------------------------
# list_game_examples
# ---------------------------------------------------------------------------------------------


class ListIn(ToolInput):
    platform: Literal["nes", "gb", "gbc", "genesis", "all"] = Field(
        default="all",
        description=f"Which console to list: {PLATFORM_WORDS}; 'all' lists every one. "
        "'Mega Drive' means genesis, 'Game Boy Color' means gbc.",
    )


class ExampleItem(ToolOutput):
    id: str = Field(description="Pass this to start_game_project, e.g. 'nes/platformer'.")
    platform: str
    kind: str = Field(description="'game' (a full genre game) or 'reference' (a minimal technique demo).")
    genre: str | None
    language: str
    players: str
    description: str


class ListOut(ToolOutput):
    examples: list[ExampleItem]
    guides: list[str] = Field(description="Guide names for read_platform_guide.")


def _language(example_id: str, platform: str) -> str:
    if example_id.endswith("/asm"):
        return "68000 assembly" if platform == "genesis" else "assembly"
    return "C"


# Seen in this skill's own play-tests with the bundled emulator (romdevtools 0.150.2).
KNOWN_ISSUES = {
    "gb/puzzle": "Known issue: freezes after Start in the bundled emulator (pieces never fall); "
    "fork gbc/puzzle for a falling-block puzzle.",
}


@tool(kind="inspect", title="List example games for a console", timeout_s=120,
      examples=[{"arguments": {"platform": "gb"}, "description": "Game Boy examples"}])
def list_game_examples(args: ListIn, ctx: ToolContext) -> ToolResult[ListOut]:
    """Start here when the user describes a retro game they want (NES, Game Boy/Color, Genesis/Mega Drive): lists the bundled working example games (shmup, platformer, puzzle, sports, racing, plus music and sprite demos) with genre, players and what each shows, so you can fork the closest one with start_game_project. Also returns the design-guide names for read_platform_guide. Full mechanics/techniques per example are in the examples.json output."""
    plats = list(rd.PLATFORMS) if args.platform == "all" else [args.platform]
    eng = rd.Romdev(f"list-{ctx.call_id}")
    items: list[ExampleItem] = []
    full: list[dict[str, Any]] = []
    for p in plats:
        out = eng.checked("examples", {"op": "list", "platform": p}, "list the examples")
        for e in out.get("examples") or []:
            eid = str(e.get("example", ""))
            if not eid.startswith(p + "/"):
                continue
            full.append(e)
            players = str(e.get("players") or "1")
            desc = str(e.get("description") or "")
            if eid in KNOWN_ISSUES:
                desc = KNOWN_ISSUES[eid] + " " + desc
            items.append(ExampleItem(
                id=eid, platform=p, kind=str(e.get("kind") or "game"), genre=e.get("genre"),
                language=_language(eid, p), players=players.split(" (")[0].strip(),
                description=(desc[:157] + "...") if (len(desc) > 160 and args.platform == "all") else desc[:400],
            ))
    if not items:
        raise ToolError("engine_failed", "The example library returned no examples.",
                        "Call again; if it stays empty, report it to the skill owner.")
    items.sort(key=lambda i: (plats.index(i.platform), i.kind != "game", i.id))
    path = ctx.output_path("examples.json")
    path.write_text(json.dumps(full, indent=1))
    games = sum(1 for i in items if i.kind == "game")
    return ToolResult(
        data=ListOut(examples=items, guides=list(rd.GUIDES)),
        summary=f"{len(items)} examples ({games} genre games) for {', '.join(plats)}",
        outputs=[OutputFile(path, "Every example with its mechanics, hardware techniques and save support")],
        next_step="Pick the example whose core loop is closest to the user's game (no exact genre match: "
        "puzzle for board/card/RPG grids, platformer for action/beat-em-up, sports for ball games, shmup "
        "for anything with projectiles) and call start_game_project with its id.",
    )


# ---------------------------------------------------------------------------------------------
# read_platform_guide
# ---------------------------------------------------------------------------------------------


class GuideIn(ToolInput):
    platform: PlatformName = Field(description=f"Console: {PLATFORM_WORDS}.")
    name: str = Field(
        default="mental-model",
        description="Which guide: 'mental-model' (how the hardware works, limits, the APIs the examples "
        "use), 'troubleshooting' (blank screen, garbled sprites, crashes, input not working), "
        "'upstream-sources' (where the libraries come from).",
    )
    offset: int = Field(default=0, ge=0, description="Character offset to start reading from (to page through a long guide).")
    max_chars: int = Field(default=12000, ge=500, le=14000, description="How many characters to return inline (500-14000).")


class GuideOut(ToolOutput):
    platform: str
    name: str
    text: str
    offset: int
    total_chars: int
    truncated: bool
    next_offset: int | None


@tool(kind="inspect", title="Read a console's design guide", timeout_s=30,
      examples=[{"arguments": {"platform": "nes", "name": "troubleshooting"}}])
def read_platform_guide(args: GuideIn, ctx: ToolContext) -> ToolResult[GuideOut]:
    """Use before writing or fixing game code for a console, or when a build shows a blank/garbled screen: returns the console's design guide ('mental-model': hardware limits, sprite/tile rules, the runtime API; 'troubleshooting': renders-nothing traps and fixes). Pages long guides with offset; the whole guide is also returned as a .md file. Mentions of engine commands in the text (frame, memory, build...) map to this skill's build_and_run_game and play_game."""
    key = args.name.strip().lower().replace("_", "-").replace(" ", "-")
    if key not in rd.GUIDES:
        raise ToolError(
            "unknown_guide",
            f"There is no guide named '{args.name}'.",
            "Use one of: " + ", ".join(rd.GUIDES) + ".",
        )
    path = rd.GUIDE_ROOT / args.platform / rd.GUIDES[key]
    if not path.is_file():
        raise ToolError("unknown_guide", f"The {args.platform} {key} guide is not installed.",
                        "Use 'mental-model' or 'troubleshooting'.")
    text = path.read_text("utf-8", "replace")
    chunk = text[args.offset: args.offset + args.max_chars]
    end = args.offset + len(chunk)
    truncated = end < len(text)
    out = ctx.output_path(f"{args.platform}-{key}.md")
    out.write_text(text)
    ctx.mark_untrusted(f"{args.platform} {key} guide")
    return ToolResult(
        data=GuideOut(platform=args.platform, name=key, text=chunk, offset=args.offset, total_chars=len(text),
                      truncated=truncated, next_offset=end if truncated else None),
        summary=f"{rd.PLATFORMS[args.platform]['label']} {key} guide: {len(chunk)} of {len(text)} characters",
        outputs=[OutputFile(out, "The whole guide")],
        next_step=(f"More text remains: call again with offset={end} to keep reading." if truncated else None),
    )


# ---------------------------------------------------------------------------------------------
# start_game_project
# ---------------------------------------------------------------------------------------------


class StartIn(ToolInput):
    example: str | None = Field(
        default=None,
        description="Example id from list_game_examples, e.g. 'nes/platformer', 'gb/puzzle', 'genesis/shmup'. "
        "Leave empty when resuming from project_zip.",
    )
    name: str = Field(
        default="mygame", pattern=r"^[A-Za-z][A-Za-z0-9_]{0,23}$",
        description="Your game's name (letters, digits, underscore; starts with a letter; up to 24). "
        "Names the ROM and replaces the example's title where the example shows one.",
    )
    project_zip: Annotated[InputFile, FileConstraints(extensions=[".zip"])] | None = Field(
        default=None,
        description="Instead of an example: a project .zip from an earlier start_game_project / "
        "build_and_run_game result (or one the user kept), to continue that game.",
    )
    platform: PlatformName | None = Field(
        default=None, description="Only with project_zip, if the zip came from elsewhere: which console it targets.",
    )


class FileItem(ToolOutput):
    path: str
    bytes: int


class StartOut(ToolOutput):
    platform: str
    name: str
    example: str | None
    main_source: str | None = Field(description="The file holding the game loop; read it before editing.")
    files: list[FileItem] = Field(description="Your editable files (library/vendor folders not listed).")
    vendor_file_count: int


@tool(kind="create", title="Start a game project from an example", timeout_s=120, state_version=STATE_VERSION,
      examples=[{"arguments": {"example": "gb/platformer", "name": "skyjump"}}])
def start_game_project(args: StartIn, ctx: ToolContext) -> ToolResult[StartOut]:
    """After picking an example with list_game_examples: copies that working game into a new editable project (it builds and runs before you change anything), or resumes a project .zip from an earlier run. Returns a state_id: pass it to edit_game_files, build_and_run_game and play_game. Also returns the project as a .zip to keep."""
    uncertain: list[str] = []
    if args.project_zip is not None:
        meta, uncertain = _import_zip(ctx, Path(args.project_zip), args.platform, args.name if args.name != "mygame" else None)
        root = _proj_root(ctx)
        how = "Resumed project from the zip"
    else:
        if not args.example:
            raise ToolError("invalid_arguments", "Neither an example nor a project zip was given.",
                            "Pass example (an id from list_game_examples such as 'nes/platformer') or project_zip.")
        ex = args.example.strip().lower()
        if "/" not in ex or ex.split("/")[0] not in rd.PLATFORMS:
            raise ToolError("unknown_example", f"'{args.example}' is not an example id.",
                            "Use an id like 'nes/platformer' from list_game_examples (consoles: nes, gb, gbc, genesis).")
        platform = ex.split("/")[0]
        _wipe_state(ctx)
        root = _proj_root(ctx)
        eng = rd.Romdev(f"start-{ctx.call_id}")
        out = eng.call("examples", {"op": "fork", "example": ex, "name": args.name, "path": str(root)}, timeout=120)
        if out.get("error") or not root.is_dir() or rd.main_source(root) is None:
            _wipe_state(ctx)
            listing = eng.call("examples", {"op": "list", "platform": platform})
            ids = [e.get("example") for e in listing.get("examples") or []]
            raise ToolError("unknown_example", f"'{args.example}' is not one of the {platform} examples.",
                            "Use one of: " + ", ".join(str(i) for i in ids) + ".")
        meta = {"platform": platform, "name": args.name, "example": ex}
        _write_meta(ctx, meta)
        how = f"Forked {ex}"
    files = rd.project_files(root)
    total = rd.count_all_files(root)
    zpath = rd.zip_project(root, ctx.output_path(f"{meta['name']}-project.zip"), meta)
    plat = meta["platform"]
    return ToolResult(
        data=StartOut(platform=plat, name=meta["name"], example=meta.get("example"), main_source=rd.main_source(root),
                      files=[FileItem(**f) for f in files[:60]], vendor_file_count=total - len(files)),
        summary=f"{how} as '{meta['name']}' for {rd.PLATFORMS[plat]['label']} ({len(files)} editable files)",
        outputs=[OutputFile(zpath, "The project source as a .zip (keep it to continue later)")],
        uncertain=uncertain,
        next_step="Build it once unchanged with build_and_run_game (pass this state_id) to see the starting "
        "point, then read main_source with edit_game_files (search for the constants or functions to change).",
    )


# ---------------------------------------------------------------------------------------------
# edit_game_files
# ---------------------------------------------------------------------------------------------


class WriteItem(ToolInput):
    path: str = Field(description="Project-relative path, e.g. 'main.c' or 'level.h'.")
    content: str = Field(description="The whole new file content.")


class ReplaceItem(ToolInput):
    path: str = Field(description="Project-relative path of the file to change.")
    find: str = Field(min_length=1, description="Exact text to find (copy it from a read; whitespace matters).")
    replace: str = Field(description="Text to put in its place.")
    all: bool = Field(default=False, description="Replace every occurrence; by default the text must occur exactly once.")


class ReadItem(ToolInput):
    path: str = Field(description="Project-relative path to read.")
    start_line: int = Field(default=1, ge=1, description="First line to return (1-based).")
    line_count: int = Field(default=200, ge=1, le=400, description="How many lines to return (max 400).")


class EditIn(ToolInput):
    writes: list[WriteItem] = Field(default_factory=list, max_length=20, description="Files to create or overwrite whole.")
    replacements: list[ReplaceItem] = Field(default_factory=list, max_length=50, description="Exact find/replace edits, applied in order after writes.")
    deletes: list[str] = Field(default_factory=list, max_length=20, description="Project-relative files to delete.")
    read: list[ReadItem] = Field(default_factory=list, max_length=6, description="Files (line ranges) to read back after the edits, with line numbers.")
    search: list[str] = Field(default_factory=list, max_length=12, description="Plain-text strings to find in the project's source files; returns file:line matches (to locate code in long files).")


class ReplaceResult(ToolOutput):
    path: str
    find: str
    applied: int
    problem: str | None


class ReadResult(ToolOutput):
    path: str
    start_line: int
    end_line: int
    total_lines: int
    text: str
    truncated: bool


class SearchHit(ToolOutput):
    term: str
    file: str
    line: int
    text: str


class EditOut(ToolOutput):
    platform: str
    written: list[str]
    deleted: list[str]
    replacements: list[ReplaceResult]
    not_applied: int
    reads: list[ReadResult]
    search_hits: list[SearchHit]
    files: list[FileItem]


_DATA_BUDGET = 15000


def _fit_edit_data(hits: list[Any], reads: list[Any], files: list[dict[str, Any]], reps: list[Any]) -> tuple[list[Any], list[Any], int]:
    """Keep edit_game_files' inline data under the result size limit: drop search hits first, then read lines."""
    def size() -> int:
        return len(json.dumps({"h": [h.model_dump() for h in hits], "r": [r.model_dump() for r in reads],
                               "f": files[:60], "p": [r.model_dump() for r in reps]}))
    dropped = 0
    while hits and size() > _DATA_BUDGET:
        cut = max(1, len(hits) // 4)
        dropped += cut
        hits = hits[:-cut]
    while reads and size() > _DATA_BUDGET:
        r = reads[-1]
        lines = r.text.splitlines()
        if len(lines) <= 5:
            reads = reads[:-1]
            continue
        keep = lines[: max(5, int(len(lines) * 0.8))]
        reads[-1] = r.model_copy(update={"text": "\n".join(keep), "end_line": r.start_line + len(keep) - 1, "truncated": True})
    return hits, reads, dropped


_TEXT_EXT = {".c", ".h", ".s", ".asm", ".inc", ".i", ".cfg", ".ld", ".md", ".txt", ".json", ".js", ".z80", ".i80"}
_MAX_WRITE = 2_000_000
_READ_BUDGET = 11000


@tool(kind="edit", title="Edit, read or search game source files", timeout_s=60, state_version=STATE_VERSION,
      examples=[{"arguments": {"search": ["PLAYER_SPEED"], "read": [{"path": "main.c", "start_line": 1, "line_count": 120}]}}])
def edit_game_files(args: EditIn, ctx: ToolContext) -> ToolResult[EditOut]:
    """Use to change or inspect the game after start_game_project: write whole files, apply exact find/replace edits, delete files, read line ranges back (with line numbers) and search the sources for a name. Paths stay inside the project. Pass the state_id from the previous call; edits return a new state_id to pass on. Then rebuild with build_and_run_game."""
    root, meta, _ = _load_project(ctx, None)
    rr = root.resolve()
    written: list[str] = []
    deleted: list[str] = []
    reps: list[ReplaceResult] = []
    for w in args.writes:
        target = rd.safe_rel(rr, w.path)
        if len(w.content.encode()) > _MAX_WRITE:
            raise ToolError("too_large", f"{w.path} is over 2 MB.", "Split the data into smaller files.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(w.content)
        written.append(target.relative_to(rr).as_posix())
    for r in args.replacements:
        target = rd.safe_rel(rr, r.path)
        rel = target.relative_to(rr).as_posix()
        if not target.is_file():
            reps.append(ReplaceResult(path=rel, find=r.find[:80], applied=0, problem="file not found"))
            continue
        text = target.read_text("utf-8", "replace")
        n = text.count(r.find)
        if n == 0:
            near = ""
            first = r.find.strip().splitlines()[0].strip() if r.find.strip() else ""
            if first and first in text:
                ln = text[: text.index(first)].count("\n") + 1
                near = f"; its first line occurs at line {ln} (check whitespace/following lines)"
            reps.append(ReplaceResult(path=rel, find=r.find[:80], applied=0, problem="text not found" + near))
        elif n > 1 and not r.all:
            lines = []
            start = 0
            for _ in range(min(n, 5)):
                i = text.index(r.find, start)
                lines.append(str(text[:i].count("\n") + 1))
                start = i + 1
            reps.append(ReplaceResult(path=rel, find=r.find[:80], applied=0,
                                      problem=f"occurs {n} times (lines {', '.join(lines)}); add context or set all=true"))
        else:
            target.write_text(text.replace(r.find, r.replace))
            reps.append(ReplaceResult(path=rel, find=r.find[:80], applied=n, problem=None))
    for d in args.deletes:
        target = rd.safe_rel(rr, d)
        if target.is_file():
            target.unlink()
            deleted.append(target.relative_to(rr).as_posix())
    reads: list[ReadResult] = []
    budget = _READ_BUDGET
    for r in args.read:
        target = rd.safe_rel(rr, r.path)
        if not target.is_file():
            raise ToolError("file_not_found", f"{r.path} is not in the project.",
                            "Check the files list from start_game_project (or this result's files).")
        lines = target.read_text("utf-8", "replace").splitlines()
        s = r.start_line
        chunk: list[str] = []
        used = 0
        truncated = False
        for i in range(s - 1, min(len(lines), s - 1 + r.line_count)):
            ln = f"{i + 1:5d}| {lines[i]}"
            if used + len(ln) + 1 > budget:
                truncated = True
                break
            chunk.append(ln)
            used += len(ln) + 1
        budget -= used
        end = s - 1 + len(chunk)
        reads.append(ReadResult(path=target.relative_to(rr).as_posix(), start_line=s, end_line=end, total_lines=len(lines),
                                text="\n".join(chunk), truncated=truncated or end < min(len(lines), s - 1 + r.line_count)))
    hits: list[SearchHit] = []
    capped = 0
    if args.search:
        srcs = [p for p in sorted(rr.rglob("*")) if p.is_file() and p.suffix.lower() in {".c", ".h", ".s", ".asm", ".inc"}
                and p.relative_to(rr).as_posix().split("/")[0] not in rd.VENDOR_DIRS]
        for term in args.search:
            count = 0
            for p in srcs:
                for i, line in enumerate(p.read_text("utf-8", "replace").splitlines(), 1):
                    if term in line:
                        count += 1
                        if count <= 30:
                            hits.append(SearchHit(term=term, file=p.relative_to(rr).as_posix(), line=i, text=line.strip()[:160]))
            if count > 30:
                capped += count - 30
    if reads or hits:
        ctx.mark_untrusted("project source files")
    files = rd.project_files(rr)
    hits, reads, hits_dropped = _fit_edit_data(hits, reads, files, reps)
    hits_dropped += capped
    bad = sum(1 for r in reps if r.applied == 0)
    parts = []
    if written:
        parts.append(f"wrote {len(written)} file(s)")
    if reps:
        parts.append(f"{len(reps) - bad} of {len(reps)} replacements applied")
    if deleted:
        parts.append(f"deleted {len(deleted)}")
    if reads:
        parts.append(f"read {len(reads)} file range(s)")
    if hits or args.search:
        parts.append(f"{len(hits) + hits_dropped} search hit(s)")
    summary = ("Edited project: " if (written or reps or deleted) else "Project: ") + (", ".join(parts) or "no changes")
    changed = bool(written or deleted or any(r.applied for r in reps))
    return ToolResult(
        data=EditOut(platform=meta["platform"], written=written, deleted=deleted, replacements=reps, not_applied=bad,
                     reads=reads, search_hits=hits, files=[FileItem(**f) for f in files[:60]]),
        summary=summary,
        status="partial" if bad else "ok",
        uncertain=([f"{bad} replacement(s) were not applied; see replacements[].problem"] if bad else [])
        + ([f"{hits_dropped} more search hit(s) not shown (30 per term at most); search for a more specific term"] if hits_dropped else []),
        next_step=("Fix the replacements that were not applied (read the exact text first), then " if bad else "")
        + ("call build_and_run_game with the new state_id." if changed else "Make your edits, then call build_and_run_game."),
    )


# ---------------------------------------------------------------------------------------------
# build_and_run_game
# ---------------------------------------------------------------------------------------------


class BuildIn(ToolInput):
    frames: int = Field(default=180, ge=1, le=3600, description="Frames to run the ROM before the screenshot (60 = one second).")
    project_zip: Annotated[InputFile, FileConstraints(extensions=[".zip"])] | None = Field(
        default=None, description="A project .zip to build instead of the state_id's project (e.g. one the user kept).",
    )
    platform: PlatformName | None = Field(default=None, description="Only with a project_zip from elsewhere: its console.")


class BuildIssue(ToolOutput):
    file: str | None
    line: int | None
    col: int | None = None
    severity: str
    message: str
    stage: str | None = None


class Rendering(ToolOutput):
    blank: bool = Field(description="True when the picture is a single flat colour (nothing drawn).")
    unique_colors: int
    dominant_color: str
    dominant_pct: float
    non_dominant_pixels: int
    width: int
    height: int


class BuildOut(ToolOutput):
    built: bool
    platform: str
    rom: str | None
    rom_bytes: int | None
    rom_layout: str | None
    header_ok: bool | None
    header: dict[str, Any] | None
    frames_run: int | None
    rendering: Rendering | None
    engine_rendering_check: str | None
    errors: list[BuildIssue]
    warnings: list[BuildIssue]


@tool(kind="create", title="Build the ROM and run it", long_running=True, timeout_s=600, state_version=STATE_VERSION,
      examples=[{"arguments": {"frames": 180}}])
def build_and_run_game(args: BuildIn, ctx: ToolContext) -> ToolResult[BuildOut]:
    """Use after start_game_project or edit_game_files to compile the project with the console's real toolchain (cc65 for NES, SDCC/RGBDS for Game Boy, SGDK gcc for Genesis), check the ROM header and checksums, boot it in the emulator for some frames and screenshot it. Returns the .nes/.gb/.gbc/.md ROM, the screenshot, whether the screen is rendering, and compiler errors with file:line when the build fails (fix them with edit_game_files, then call again). Pass the state_id; returns a new one for play_game."""
    root, meta, uncertain = _load_project(ctx, args.project_zip, args.platform)
    platform = meta["platform"]
    name = meta["name"]
    work = Path("/tmp/retroforge") / ctx.call_id
    work.mkdir(parents=True, exist_ok=True)
    rom_tmp = work / f"{name}{_ext(platform)}"
    ctx.progress(5, f"compiling for {rd.PLATFORMS[platform]['label']}")
    eng = rd.Romdev(f"build-{ctx.call_id}")
    try:
        res = eng.call("build", {"output": "project", "platform": platform, "path": str(root.resolve()),
                                 "outputPath": str(rom_tmp)}, timeout=540)
        log = rd.strip_ansi(str(res.get("log") or res.get("logTail") or res.get("error") or ""))
        log_path = ctx.output_path("build.log")
        log_path.write_text(log)
        ctx.mark_untrusted("compiler output")
        raw_issues: list[dict[str, Any]] = []
        for it in res.get("issues") or []:
            if not isinstance(it, dict):
                continue
            raw_issues.append(dict(file=rd.clean_issue_path(it.get("file"), root.resolve()),
                                   line=it.get("line") if isinstance(it.get("line"), int) else None,
                                   col=it.get("col") if isinstance(it.get("col"), int) else None,
                                   severity=str(it.get("severity") or "error"),
                                   message=rd.strip_ansi(str(it.get("message") or ""))[:400],
                                   stage=str(it.get("stage")) if it.get("stage") else None))
        if not res.get("ok") and not any(i["severity"] == "error" for i in raw_issues):
            raw_issues += rd.parse_log_errors(log)
        rd.attribute_issue_files(log, raw_issues)
        issues = [BuildIssue(**i) for i in raw_issues]
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity != "error"]
        if not res.get("ok") or not rom_tmp.is_file():
            if not errors:
                errors = [BuildIssue(file=None, line=None, severity="error",
                                     message=(rd.strip_ansi(str(res.get("error") or "")) or log[-400:] or "build failed")[:400])]
            first = errors[0]
            where = f"{first.file}:{first.line}" if first.file and first.line else (first.file or "build")
            return ToolResult(
                data=BuildOut(built=False, platform=platform, rom=None, rom_bytes=None, rom_layout=None, header_ok=None,
                              header=None, frames_run=None, rendering=None, engine_rendering_check=None,
                              errors=errors[:25], warnings=warnings[:10]),
                summary=f"Build failed with {len(errors)} error(s); first at {where}: {first.message[:120]}",
                status="partial",
                outputs=[OutputFile(log_path, "Full compiler/linker log")],
                uncertain=uncertain + ["No ROM was produced"],
                next_step="Read the lines around each error with edit_game_files (read with start_line near the "
                "error line), fix them, and call build_and_run_game again with the new state_id. The first "
                "error is usually the real one; later ones often follow from it.",
            )
        ctx.progress(55, "checking the ROM header")
        data = rom_tmp.read_bytes()
        fixes: list[str] = []
        if platform in ("gb", "gbc"):
            data, fixes = rd.finish_gb_header(data, name)
            if fixes:
                rom_tmp.write_bytes(data)
        header = rd.check_header(platform, data)
        if fixes:
            header["finished_by_skill"] = fixes
        rom_dir = ctx.state_dir / rd.STATE_ROM_DIR
        if rom_dir.exists():
            shutil.rmtree(rom_dir)
        rom_dir.mkdir(parents=True)
        shutil.copy2(rom_tmp, rom_dir / rom_tmp.name)
        meta.update(last_rom=rom_tmp.name, rom_source_hash=rd.source_hash(root))
        _write_meta(ctx, meta)
        rom_out = ctx.output_path(rom_tmp.name)
        shutil.copy2(rom_tmp, rom_out)

        ctx.progress(65, "booting it in the emulator")
        eng.checked("loadMedia", {"platform": platform, "path": str(rom_tmp)}, "load the ROM")
        eng.checked("frame", {"op": "step", "frames": args.frames}, "run the ROM", timeout=300)
        shot = ctx.output_path("screenshot.png")
        eng.checked("frame", {"op": "screenshot", "path": str(shot)}, "take a screenshot")
        ver = eng.call("frame", {"op": "verify"})
        verdict = rd.rendering_verdict(rd.load_rgb(shot))
        engine_note = rd.strip_ansi(str(ver.get("note") or ""))[:300] or None
        zpath = rd.zip_project(root, ctx.output_path(f"{name}-project.zip"), meta)
    finally:
        eng.close()
        shutil.rmtree(work, ignore_errors=True)
    status = "ok"
    if not header["ok"]:
        uncertain.append("ROM header problems: " + "; ".join(header["problems"]))
        status = "partial"
    elif header["problems"]:
        uncertain.append("; ".join(header["problems"]))
    if verdict["blank"]:
        uncertain.append(f"The screen is a single flat colour ({verdict['dominant_color']}) after {args.frames} frames: "
                         "the game is not drawing anything yet")
        status = "partial"
    label = rd.PLATFORMS[platform]["label"]
    summary = (f"Built {rom_tmp.name} ({len(data)} bytes, header {'valid' if header['ok'] else 'INVALID'}); after "
               f"{args.frames} frames the screen {'is blank' if verdict['blank'] else 'shows ' + str(verdict['unique_colors']) + ' colours'}")
    return ToolResult(
        data=BuildOut(built=True, platform=platform, rom=rom_tmp.name, rom_bytes=len(data), rom_layout=res.get("romLayout"),
                      header_ok=header["ok"], header=header, frames_run=args.frames, rendering=Rendering(**verdict),
                      engine_rendering_check=engine_note, errors=[], warnings=warnings[:10]),
        summary=summary,
        status=status,  # type: ignore[arg-type]
        outputs=[OutputFile(rom_out, f"The {label} ROM (runs in any {label} emulator or flash cart)"),
                 OutputFile(shot, f"Screenshot after {args.frames} frames"),
                 OutputFile(log_path, "Compiler/linker log"),
                 OutputFile(zpath, "The project source as a .zip (keep it to continue later)")],
        uncertain=uncertain,
        next_step=("Look at the screenshot. If it is blank, read_platform_guide(name='troubleshooting'). "
                   if verdict["blank"] else "Look at the screenshot to confirm the scene, then ")
        + "call play_game with this state_id and button steps that exercise the controls the user asked for.",
    )


# ---------------------------------------------------------------------------------------------
# play_game
# ---------------------------------------------------------------------------------------------

Button = Literal["up", "down", "left", "right", "a", "b", "c", "start", "select"]

BUTTON_MAP: dict[str, dict[str, str]] = {
    "nes": {"up": "up", "down": "down", "left": "left", "right": "right", "a": "a", "b": "b", "start": "start", "select": "select"},
    "gb": {"up": "up", "down": "down", "left": "left", "right": "right", "a": "a", "b": "b", "start": "start", "select": "select"},
    "gbc": {"up": "up", "down": "down", "left": "left", "right": "right", "a": "a", "b": "b", "start": "start", "select": "select"},
    # genesis_plus_gx maps Genesis A/B/C onto libretro y/b/a.
    "genesis": {"up": "up", "down": "down", "left": "left", "right": "right", "a": "y", "b": "b", "c": "a", "start": "start"},
}


class Step(ToolInput):
    buttons: list[Button] = Field(default_factory=list, max_length=6,
                                  description="Buttons held for the whole step (empty = hands off). NES/Game Boy: up down left right a b start select. Genesis: up down left right a b c start.")
    frames: int = Field(default=60, ge=1, le=1800, description="How many frames to hold them (60 = one second).")


MemRegion = Literal["work_ram", "video_ram", "sprites", "palette", "save_ram"]

# Console-specific memory regions of the emulator cores (None = not exposed).
REGION_MAP: dict[str, dict[str, str | None]] = {
    "work_ram": {"nes": "system_ram", "gb": "system_ram", "gbc": "system_ram", "genesis": "system_ram"},
    "video_ram": {"nes": "nes_nametables", "gb": "gb_vram", "gbc": "gb_vram", "genesis": "video_ram"},
    "sprites": {"nes": "nes_oam", "gb": "gb_oam", "gbc": "gb_oam", "genesis": None},
    "palette": {"nes": "nes_palette", "gb": "gb_bgpdata", "gbc": "gb_bgpdata", "genesis": "genesis_cram"},
    "save_ram": {"nes": "save_ram", "gb": "save_ram", "gbc": "save_ram", "genesis": "save_ram"},
}


class MemRead(ToolInput):
    address: int | str = Field(description="For work_ram: the address as the CPU sees it, number or hex string: NES $0000-$07FF, "
                               "Game Boy $C000-$DFFF, Genesis $FF0000-$FFFFFF (e.g. '0xC0A0'). For other regions: the byte "
                               "offset inside that region (0 = its start).")
    length: int = Field(default=1, ge=1, le=256, description="Bytes to read (1-256).")
    region: MemRegion = Field(default="work_ram", description="Which memory: work_ram (game variables, default); video_ram "
                              "(NES nametables, Game Boy VRAM, Genesis VRAM); sprites (sprite table/OAM: NES 64 x [y, tile, "
                              "attr, x], Game Boy 40 x [y, x, tile, flags]; not on Genesis); palette (NES 32 bytes, Game Boy "
                              "Color BG palette data, Genesis CRAM); save_ram (battery save, if the game has one).")


DEFAULT_STEPS = [{"buttons": [], "frames": 120}, {"buttons": ["start"], "frames": 10}, {"buttons": [], "frames": 30},
                 {"buttons": ["right"], "frames": 60}, {"buttons": ["a"], "frames": 10}]


class PlayIn(ToolInput):
    rom: Annotated[InputFile, FileConstraints(extensions=[".nes", ".gb", ".gbc", ".md", ".gen", ".bin"])] | None = Field(
        default=None, description="A ROM file to test instead of the project's last build (an NES, Game Boy/Color or "
        "Genesis homebrew ROM the user has). Omit to play the ROM build_and_run_game made for this state_id.")
    platform: PlatformName | None = Field(default=None, description="Console of an uploaded rom, only if it can't be detected (e.g. a .bin).")
    steps: list[Step] = Field(default_factory=lambda: [Step(**s) for s in DEFAULT_STEPS], min_length=1, max_length=40,
                              description="The button script, run in order. Default: idle 120 frames, Start 10, idle 30, "
                              "Right 60, A 10. Most examples wait on a title screen: press start or a first.")
    player: Literal[1, 2] = Field(default=1, description="Which controller port the buttons go to (2 = second player).")
    read_memory: list[MemRead] = Field(default_factory=list, max_length=8,
                                       description="Optional work-RAM bytes to read after the last step (e.g. a score or player X you located in the source).")
    gif: bool = Field(default=True, description="Also make an animated GIF of the whole run.")


class StepResult(ToolOutput):
    index: int
    buttons: list[str]
    frames: int
    screenshot: str
    changed_pixels: int = Field(description="Pixels that differ from the end of the previous step.")
    input_effect_pixels: int | None = Field(description="Most pixels that differed, at any sampled point of the step, from the same frames run with no buttons held (null for idle steps). >0 means this input changed the picture.")
    input_effect_at_frame: int | None = Field(default=None, description="Frames into the step where that biggest difference was seen.")
    input_effect_end_pixels: int | None = Field(default=None, description="The difference on the step's last frame only. Much smaller than input_effect_pixels means the effect was undone (e.g. the player moved, then died and respawned).")
    effect_region: list[int] | None = Field(description="[x, y, w, h] box around the pixels the input changed, at input_effect_at_frame.")
    blank: bool


class MemResult(ToolOutput):
    region: str
    address: str
    hex: str


class PlayOut(ToolOutput):
    platform: str
    rom: str
    total_frames: int
    responsive_to_input: bool | None = Field(description="True when at least one button step changed the picture compared with not pressing it.")
    responsive_steps: list[int]
    steps: list[StepResult]
    final_rendering: Rendering
    gif_frames: int
    memory: list[MemResult]


def _mem_offset(platform: str, addr: int, length: int) -> int:
    if platform == "nes":
        if 0 <= addr < 0x2000:
            off = addr & 0x7FF
            if off + length <= 0x800:
                return off
    elif platform in ("gb", "gbc"):
        if 0xC000 <= addr and addr + length <= 0xE000:
            return addr - 0xC000
    elif platform == "genesis":
        a = addr & 0xFFFFFF
        if a >= 0xE00000:
            off = a & 0xFFFF
            if off + length <= 0x10000:
                return off
    ranges = {"nes": "$0000-$07FF", "gb": "$C000-$DFFF", "gbc": "$C000-$DFFF", "genesis": "$FF0000-$FFFFFF"}
    raise ToolError("invalid_address", f"Address {addr:#x} (+{length}) is outside {platform} work RAM.",
                    f"Use a work-RAM address in {ranges[platform]}.")


def _parse_addr(v: int | str) -> int:
    if isinstance(v, int):
        return v
    s = v.strip().lower().replace("$", "0x")
    try:
        return int(s, 0)
    except ValueError:
        raise ToolError("invalid_address", f"'{v}' is not an address.", "Pass a number or a hex string like '0xC0A0'.") from None


@tool(kind="check", title="Play-test a ROM with button presses", long_running=True, timeout_s=600, state_version=STATE_VERSION,
      examples=[{"arguments": {"steps": [{"buttons": [], "frames": 90}, {"buttons": ["a"], "frames": 10},
                                         {"buttons": ["right"], "frames": 90}, {"buttons": ["right", "a"], "frames": 30}]}}])
def play_game(args: PlayIn, ctx: ToolContext) -> ToolResult[PlayOut]:
    """Use to check a game actually plays, after build_and_run_game (pass its state_id) or on an uploaded NES/Game Boy/Genesis ROM: runs a button script in the emulator (e.g. hold Right 60 frames, press A), screenshots each step and makes an animated GIF. For every button step it replays the same frames with no buttons and reports how many pixels the input changed, so you can tell whether the controls work. Can read work-RAM bytes at the end."""
    uncertain: list[str] = []
    if args.rom is not None:
        rom_path = Path(args.rom)
        data = rom_path.read_bytes()
        by_signature = rd.detect_rom_platform(rom_path, data, None, signature_only=True)
        platform = args.platform or by_signature
        if platform is None:
            guess = rd.detect_rom_platform(rom_path, data, None)
            why = ("; ".join(rd.check_header(guess, data)["problems"]) if guess else "no NES, Game Boy or Genesis header found")
            raise ToolError("unsupported_input", f"{rom_path.name} is not a recognisable NES, Game Boy or Genesis ROM ({why}).",
                            "Pass a ROM this skill built (build_and_run_game), or another .nes/.gb/.gbc/.md homebrew ROM "
                            "with a valid header; set platform only if you are sure of its console.")
        if args.platform and by_signature and by_signature != args.platform and {by_signature, args.platform} != {"gb", "gbc"}:
            uncertain.append(f"The file's header looks like {by_signature}, but it was run as {args.platform} as asked")
        hdr = rd.check_header(platform, data)
        if not hdr["ok"]:
            uncertain.append(f"Header problems for {platform}: " + "; ".join(hdr["problems"]))
        rom_name = rom_path.name
    else:
        root, meta, _ = _load_project(ctx, None)
        platform = meta["platform"]
        last = meta.get("last_rom")
        rom_path = ctx.state_dir / rd.STATE_ROM_DIR / str(last) if last else Path("/nonexistent")
        if not last or not rom_path.is_file():
            raise ToolError("no_rom", "This project has not been built yet.",
                            "Call build_and_run_game with this state_id first, then play_game with the state_id it returns.")
        if meta.get("rom_source_hash") and meta["rom_source_hash"] != rd.source_hash(root):
            uncertain.append("The project was edited after this ROM was built; this run tests the older build")
        rom_name = rom_path.name
    bmap = BUTTON_MAP[platform]
    for st in args.steps:
        bad = [b for b in st.buttons if b not in bmap]
        if bad:
            raise ToolError("invalid_button", f"{rd.PLATFORMS[platform]['label']} has no {', '.join(bad)} button.",
                            "Use: " + ", ".join(bmap) + ".")
    total = sum(s.frames for s in args.steps)
    if total > 7200:
        raise ToolError("too_long", f"The script runs {total} frames; the limit is 7200 (2 minutes of game time).",
                        "Shorten or split the script into several play_game calls.")
    every = max(3, math.ceil(total / 240))
    port_idx = args.player - 1
    work = Path("/tmp/retroforge") / f"play-{ctx.call_id}"
    gif_dir = work / "gif"
    gif_dir.mkdir(parents=True, exist_ok=True)
    rom_local = work / ("rom" + (rom_path.suffix or _ext(platform)))
    shutil.copy2(rom_path, rom_local)
    eng = rd.Romdev(f"play-{ctx.call_id}")
    results: list[StepResult] = []
    gif_frames: list[Path] = []
    mem: list[MemResult] = []
    try:
        eng.checked("loadMedia", {"platform": platform, "path": str(rom_local)}, "load the ROM")
        first = gif_dir / "f00000.png"
        eng.checked("frame", {"op": "stepAndShot", "frames": 1, "path": str(first)}, "run the ROM")
        gif_frames.append(first)
        prev = rd.load_rgb(first)
        for idx, st in enumerate(args.steps, 1):
            ctx.progress(5 + 85 * (idx - 1) / len(args.steps), f"step {idx} of {len(args.steps)}")
            pressed = {bmap[b]: True for b in st.buttons}
            ports: list[dict[str, Any]] = [{}, {}] if port_idx == 1 else [{}]
            chunks: list[int] = []
            left = st.frames
            while left > 0:
                chunks.append(min(every, left))
                left -= chunks[-1]
            ctrl_frames: list[Any] = []
            if pressed:
                # The same frames with no buttons, sampled at the same points, so the input's effect is
                # measured all through the step (a player who walks, then falls back to the start, still counts).
                eng.checked("state", {"op": "save", "name": "pre"}, "save a state")
                eng.checked("input", {"op": "set", "ports": ports}, "release the buttons")
                for ci, n in enumerate(chunks):
                    cpath = work / f"ctrl{idx:02d}-{ci:04d}.png"
                    eng.checked("frame", {"op": "stepAndShot", "frames": n, "path": str(cpath)},
                                "run the control frames", timeout=300)
                    ctrl_frames.append(rd.load_rgb(cpath))
                eng.checked("state", {"op": "load", "name": "pre", "render": False}, "restore the state")
            ports[port_idx] = pressed
            eng.checked("input", {"op": "set", "ports": ports}, "press the buttons")
            last_shot: Path | None = None
            best = (-1, None, None)  # (pixels, frame offset, region)
            at = 0
            for ci, n in enumerate(chunks):
                at += n
                fp = gif_dir / f"f{len(gif_frames):05d}.png"
                eng.checked("frame", {"op": "stepAndShot", "frames": n, "path": str(fp)}, "run the ROM", timeout=300)
                gif_frames.append(fp)
                last_shot = fp
                if ctrl_frames:
                    arr = rd.load_rgb(fp)
                    px = rd.changed_pixels(ctrl_frames[ci], arr)
                    if px > best[0]:
                        best = (px, at, rd.changed_box(ctrl_frames[ci], arr))
            assert last_shot is not None
            shot_name = f"step{idx:02d}.png"
            shot_out = ctx.output_path(shot_name)
            shutil.copy2(last_shot, shot_out)
            cur = rd.load_rgb(last_shot)
            end_effect = rd.changed_pixels(ctrl_frames[-1], cur) if ctrl_frames else None
            results.append(StepResult(
                index=idx, buttons=list(st.buttons), frames=st.frames, screenshot=shot_name,
                changed_pixels=rd.changed_pixels(prev, cur),
                input_effect_pixels=best[0] if ctrl_frames else None,
                input_effect_at_frame=best[1] if ctrl_frames and best[0] > 0 else None,
                input_effect_end_pixels=end_effect,
                effect_region=best[2] if ctrl_frames else None,
                blank=rd.rendering_verdict(cur)["blank"]))
            prev = cur
        eng.call("input", {"op": "set", "ports": [{}]})
        for m in args.read_memory:
            addr = _parse_addr(m.address)
            core_region = REGION_MAP[m.region][platform]
            if core_region is None:
                raise ToolError("invalid_region", f"The {m.region} region is not readable on {rd.PLATFORMS[platform]['label']}.",
                                "Use work_ram, video_ram, palette or save_ram there.")
            off = _mem_offset(platform, addr, m.length) if m.region == "work_ram" else addr
            r = eng.call("memory", {"op": "read", "region": core_region, "offset": off, "length": m.length})
            if r.get("error") or not r.get("hex"):
                raise ToolError("invalid_address", f"Could not read {m.length} byte(s) of {m.region} at {addr:#x}: "
                                f"{rd.strip_ansi(str(r.get('error') or 'no data'))[:200]}",
                                "Check the offset is inside the region (save_ram exists only for battery-save games).")
            mem.append(MemResult(region=m.region, address=f"{addr:#06x}", hex=str(r.get("hex") or "")))
    finally:
        eng.close()
    final = rd.rendering_verdict(prev)
    outputs = [OutputFile(ctx.output_path(r.screenshot), f"Screen after step {r.index} ({'+'.join(r.buttons) or 'no buttons'}, {r.frames} frames)") for r in results]
    n_gif = 0
    if args.gif:
        ctx.progress(92, "making the GIF")
        gpath = ctx.output_path("play.gif")
        n_gif = rd.write_gif(gif_frames, gpath, int(every * 1000 / 60))
        outputs.insert(0, OutputFile(gpath, f"Animated run of the whole script at the console's screen size ({n_gif} frames, one per {every} game frames)"))
    shutil.rmtree(work, ignore_errors=True)
    btn_steps = [r for r in results if r.input_effect_pixels is not None]
    responsive = [r.index for r in btn_steps if (r.input_effect_pixels or 0) >= 4]
    resp: bool | None = (len(responsive) > 0) if btn_steps else None
    status = "ok"
    if resp is None:
        uncertain.append("No step pressed a button, so input response was not tested")
    elif not resp:
        uncertain.append("No button step changed the picture compared with not pressing it")
    if final["blank"]:
        uncertain.append("The final screen is a single flat colour")
        status = "partial"
    undone = [r.index for r in btn_steps if r.index in responsive and (r.input_effect_end_pixels or 0) * 4 < (r.input_effect_pixels or 0)]
    if undone:
        uncertain.append(f"In steps {', '.join(map(str, undone))} the input changed the picture mid-step but the last frame "
                         "looks almost like not pressing it (the effect was undone, e.g. the player died and respawned); "
                         "check the GIF around input_effect_at_frame")
    silent = [r.index for r in btn_steps if r.index not in responsive]
    if resp and silent:
        uncertain.append(f"Steps {', '.join(map(str, silent))} pressed buttons that changed nothing on screen "
                         "(fine for menus that wait or buttons the game ignores in that state; if it follows a step whose effect was "
                         "undone, the game may be pausing to respawn: add an idle step of ~60 frames before it and retry)")
    if args.rom is not None:
        ctx.mark_untrusted(rom_name)
    summary = (f"Played {rom_name} for {total} frames in {len(results)} steps; "
               + ("input changed the picture in steps " + ", ".join(map(str, responsive)) if responsive
                  else "no button input changed the picture" if btn_steps else "no buttons pressed"))
    return ToolResult(
        data=PlayOut(platform=platform, rom=rom_name, total_frames=total, responsive_to_input=resp,
                     responsive_steps=responsive, steps=results, final_rendering=Rendering(**final), gif_frames=n_gif, memory=mem),
        summary=summary,
        status=status,  # type: ignore[arg-type]
        outputs=outputs,
        uncertain=uncertain,
        next_step=("Look at the step screenshots/GIF to confirm the right thing moved (effect_region shows where). "
                   if resp else "If the game sits on a title screen, add a start or a press first; otherwise check the "
                   "input code (read_platform_guide troubleshooting). ")
        + "Then give the user the ROM, screenshots/GIF and project zip.",
    )
