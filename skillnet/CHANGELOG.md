## v2
- Building real ROMs and play-testing them in the emulator are now fully checked, including Game Boy Color builds and spotting a D-pad direction that doesn't work.
- Play-tests now say what the screen looks like at every step (its main colour, with and without the buttons held), so flat-colour test ROMs and "what does it show while I hold Right" questions get a direct answer.

## v1
- Start a game from 40 working examples for NES, Game Boy, Game Boy Color and Genesis/Mega Drive: platformer, shoot-'em-up, puzzle, sports and racing games, plus sprite, scrolling and music demos.
- Read each console's design guide (hardware limits, how drawing works, fixes for a blank screen).
- Edit, search and read the game's source code; your project is kept between steps and handed back as a zip you can resume later.
- Build real ROM files with each console's own compiler, with valid headers and checksums; build errors point at the exact file and line.
- Play-test any build or homebrew ROM with a script of button presses: screenshots after every step, an animated GIF, a check of whether each press changed the picture, and readings of the game's memory.
- The example list warns when an example is known not to play properly (the original Game Boy falling-block puzzle stops after Start) and points to one that does.
- Play-test GIFs now come out at the console's real screen size, and Genesis clips are no longer cropped.
- Play-tests now catch button presses whose effect is undone before the step ends (like walking into a pit and respawning), and say when a press landed while the game was pausing.
- Code search accepts up to 12 terms at once.
