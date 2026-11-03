# Retro Game Forge

Describe a game and get a playable NES, Game Boy (Color) or Genesis/Mega Drive ROM, compiled with the
console's real toolchain and play-tested in an emulator with scripted button presses.

## Where to start

Call `list_game_examples` with the console the user asked for (`nes`, `gb`, `gbc`, `genesis`; "Mega Drive"
means `genesis`). If they didn't name one, use `gb`: its graphics are 4 shades and it has one controller,
so there is the least to get wrong. Read the `examples` list: `kind: "game"` entries are complete games
(title screen, play, game over, score, music); `kind: "reference"` entries are small technique demos
(hello_sprite, tile_engine, music_demo, two_plane_parallax…).

## Stages

1. **Pick** — `list_game_examples(platform)`. Choose the `game` example whose core loop is closest to the
   request: `platformer` (running/jumping/action), `shmup` (anything with projectiles), `puzzle` (grids,
   boards, matching, cards), `sports` (ball/paddle games, 2-player versus), `racing` (scrolling roads,
   dodging). Before big changes, call `read_platform_guide(platform, "mental-model")` once: it lists the
   hardware limits and the runtime functions the example uses.
2. **Fork** — `start_game_project(example="gb/platformer", name="mygame")`. Keep the returned `state_id`. Then
   call `build_and_run_game` once *unchanged* so you know the baseline builds and what it looks like.
3. **Read** — `edit_game_files` with `search` (function or constant names, e.g. `["SPEED", "joypad"]`)
   and `read` ranges (`start_line`, `line_count` ≤ 400). `main_source` (`main.c`) holds the game loop; it is
   20–50 KB, so never ask for it whole — search, then read the lines around the hits.
4. **Change** — `edit_game_files` with `replacements` (exact `find` text copied from a read, must occur
   once unless `all=true`) for targeted changes, or `writes` for new files/whole rewrites. Change one
   thing at a time and rebuild. Every call returns a new `state_id`: always pass the newest one.
5. **Build** — `build_and_run_game(frames=180)`.
   - `built: false` → fix `errors[0]` first (`file`, `line`, `message`; later errors often follow from
     it): read ~10 lines around it, fix, rebuild.
   - `built: true` but `rendering.blank: true` → the game draws nothing; call
     `read_platform_guide(platform, "troubleshooting")` and compare your init code with the example's.
   - Open `screenshot.png` and check it shows the intended scene.
6. **Play-test** — `play_game` with steps that exercise what the user asked for. Example games wait on a
   title screen: start with `{"buttons": [], "frames": 90}, {"buttons": ["start"], "frames": 10},
   {"buttons": [], "frames": 60}`, then the moves (`{"buttons": ["right"], "frames": 60}`, `["a"]` to jump
   or fire…). Check `responsive_to_input`, each button step's `input_effect_pixels` and `effect_region`,
   and look at the step PNGs or `play.gif`. To confirm a score, lives or position value, find its variable
   in the source and read it with `read_memory` (`region: "work_ram"`).
7. **Deliver** — give the user the download links from the last results: the ROM (`.nes`/`.gb`/`.gbc`/`.md`),
   `screenshot.png` and `play.gif` (native screen size: 256×224, 160×144 or 320×224), and the project
  `.zip` so they can continue later.

To continue a game in a later session, pass its project `.zip` (the user uploads it with `upload_file`, or
an https URL) to `start_game_project(project_zip=…)`; `build_and_run_game(project_zip=…)` also builds a zip
directly. To check an existing homebrew ROM, pass it to `play_game(rom=…)`.

## Pitfalls

- **NES (cc65) is C89.** Declare variables at the top of a block. `a++; uint8_t b = a;` fails with
  "Variable identifier expected". The examples use `uint8_t`/`uint16_t` variables; follow them.
- **Genesis (SGDK) has no `<stdint.h>`.** Use `#include <genesis.h>` and its `u8`/`u16`/`s16`/`u32`
  types. Its buttons are A, B, C and Start (no Select); NES and Game Boy have no C. A wrong button gives
  `invalid_button`.
- **Title screens swallow input.** A button step pressed before the game has started shows almost no
  `input_effect_pixels`. Press `start` (or `a`, depending on the title text in the screenshot), wait
  ~60 frames, then test the controls. Hold each button for at least 10 frames.
- **Effects that get undone.** `input_effect_pixels` is the biggest difference from the no-button run at
  any point in the step (`input_effect_at_frame`); `input_effect_end_pixels` is the last frame only. If
  the end value is much smaller, the action happened and was reversed (in `gb/platformer`, holding Right
  60 frames from the start walks the player into the first pit: the life counter drops and the player
  respawns). A button pressed right after that can show 0 because the game is pausing to respawn: add
  `{"buttons": [], "frames": 60}` before it. Open the step PNGs or the GIF before telling the user what happened.
- **`gb/puzzle` freezes after Start** in the bundled emulator (seen in testing: after Start, holding
  Right or Down changes 0 pixels). For a falling-block puzzle fork `gbc/puzzle`, which plays. The other
  genre examples for all three consoles react to the D-pad after Start.
- **Colours** (checked in testing): NES palette bytes are colour indexes (`0x01` dark blue, `0x1A`
  green, `0x21` sky blue, `0x0F` black). The backdrop byte is `palette[0]` *and* `palette[16]` (its
  mirror, written last), so change both or the sky won't change. Genesis `PAL_setColor(i, 0x0BGR)`:
  `0x000A` is red, `0x0A00` blue. Game Boy (`gb`) has 4 grey shades; use `gbc` for colour.
- **Edited but not rebuilt.** `play_game` with a `state_id` plays the *last built* ROM; if the sources
  changed since, `uncertain` says so. Rebuild first.
- **Replacements that don't apply** come back with `problem` ("text not found", "occurs 3 times (lines …)")
  and `status: partial`; nothing else in that call is rolled back. Re-read the exact text and retry.
- **Hardware limits are real.** NES: 64 sprites, at most 8 per scanline (more flicker or vanish).
  Game Boy: 40 sprites. Genesis: 20 sprites per scanline, 4 palettes × 16 colours. Keep to the example's
  patterns; the mental-model guide explains why each "HARDWARE IDIOM" comment in the source is there.
- **Screen sizes**: NES 256×224, Game Boy 160×144, Genesis 320×224 (what the screenshots measure).
  60 frames ≈ 1 second.
- **Library folders** (`vendor/`, `include/` in Genesis projects) are not listed or searched; leave them.
- **Guides mention engine calls** like `memory({...})` or `sprites({...})`: these map to `play_game`'s
  `read_memory` (`work_ram`, `video_ram`, `sprites`, `palette`, `save_ram`) and the screenshots.
- **Saved work expires** 7 days after its last use. The project `.zip` in each result is the durable copy.
- The Game Boy title in the ROM header is set from the project `name` (11 characters, upper case); the
  skill also fixes the header and global checksums (`header.finished_by_skill`).

## Evidence

- "It's a valid ROM": `built`, `header_ok`, `header` (iNES PRG/CHR size and mapper; Game Boy logo,
  title, checksums, colour support; Genesis `SEGA` string and checksum) and `rom_bytes`.
- "It renders": `screenshot.png` plus `rendering` (`blank`, `unique_colors`, `dominant_color`).
- "The controls work": `play_game` `responsive_to_input`, the button steps' `input_effect_pixels` (pixels
  that differ from the same frames with no buttons) and `effect_region`, with the step PNGs / `play.gif`.
  Say which step shows which action ("step 4, Right held 60 frames: the player moved right, region x 24–60").
- "What the screen looks like": each step's `dominant_color` / `dominant_pct` / `unique_colors` (last
  frame), and for button steps `no_button_dominant_color` (the same frame with nothing held). Quote these
  for "what does it show while X is held vs. nothing pressed" ("Right held: flat #fffbff; idle: flat #000000").
- Values: `memory[].hex` for variables you read; quote the address and what it holds.
- Report anything in `uncertain` to the user as-is; don't claim a feature works if no step showed it.

## Done when

- `build_and_run_game` returned `built: true`, `header_ok: true`, `rendering.blank: false`, and the
  screenshot shows the scene the user described;
- `play_game` on that build returned `responsive_to_input: true`, the steps for each requested control are
  in `responsive_steps`, and you looked at their screenshots to confirm the right thing happened;
- the user has the ROM, a screenshot or GIF, and the project `.zip`.

## Can't do

- Consoles other than NES, Game Boy/Color and Genesis/Mega Drive (no SNES, GBA, Atari, C64, N64,
  PlayStation…). Tell the user plainly that this skill can't build for that console, build nothing
  for another console unless they agree, and offer the closest of the three.
- Reverse engineering, disassembly, decompilation or recompilation of existing ROMs.
- Hacking or patching commercial ROMs: it only builds the user's own games.
- Live play in a window: play-testing is scripted button presses with screenshots; the user can play the
  ROM in any emulator.
- Making original pixel art or music from images or audio files: graphics and notes are written in code
  (tile bytes, note tables) by you.
