# 3DSort

Rearrange your Nintendo 3DS HOME menu from your PC.

Organizing icons on the console itself is slow: one stylus drag at a time, page
by page. 3DSort edits the layout directly on the SD card instead. Put the card
in your computer, drag things around in a desktop app, check the live preview,
then write the result back and boot the console.

## What it does

- Swap any two tiles by dropping one onto the other: games, system apps,
  folder tiles, even the Game Card slot
- Move games and system apps in and out of folders
- Create, rename, empty and delete folders
- Sort presets (A to Z, Z to A)
- Live preview that reproduces the console screen exactly, for every view
  setting from 1x60 to 6x10
- Every change is staged in memory first, with undo, redo and reset. Nothing
  touches the card until you hit WRITE and confirm
- A backup of the current layout is taken automatically before every write,
  and any backup can be restored later
- Every write also unwraps gift-boxed icons in bulk (same mechanism as
  Cthulhu's "Unwrap all") and preserves the HOME menu theme you picked on the
  console, even when restoring an old backup

Moving system apps and folders needs one extra step, because their layout
lives in a NAND system save rather than on the card: dump it once with the
generated `3DSort_dump` GodMode9 script, edit freely on the PC, then run
`3DSort_inject` in GodMode9 after writing. The inject script verifies every
copy with SHA-256 gates and fixes the save CMAC, and it aborts rather than
write anything inconsistent. Without that dump, system apps simply stay
pinned and everything else keeps working.

One rule keeps that cycle smooth: do not boot the HOME menu between writing
and injecting. Every HOME boot touches the NAND save, so the inject script
will refuse a stale target. If it happens, run `3DSort_dump` again and retry;
nothing is lost.

## What you need

- A 3DS with custom firmware (Luma3DS) and GodMode9
- The console's `boot9.bin` and `movable.sed`, dumped with GodMode9
- A Windows PC with an SD card reader
- Python 3.10, for now. A standalone exe is planned.

One warning about keys: dump `movable.sed` fresh from SYSNAND CTRNAND with
GodMode9. Do not reuse one from an old NAND backup. If the console was
formatted or system-transferred since that backup, the old key will not
decrypt the current card, and the error messages are not obvious about why.

## Running from source

```
pip install pyctr Pillow pywebview pytest

python app.py                 # native window, real SD card
python app.py --serve         # same app in the browser at http://127.0.0.1:8347
python app.py --serve --mock  # synthetic data, no SD or keys needed
python -m pytest tests -q     # test suite
```

## How it works

The HOME menu layout lives in an encrypted extdata archive on the SD card.
3DSort uses [save3ds](https://github.com/wwylele/save3ds) to extract and
reimport that archive with your console's keys, then parses `SaveData.dat`
itself. Anything in the file it does not understand is preserved byte for
byte. Icons and names come from the console's own icon cache, so the grid
shows exactly what the console shows.

Folder definitions and system app positions live in `Launcher.dat`, inside a
system save on the NAND. 3DSort edits that file too, through the same save3ds
engine, but it can only reach the NAND with your help: a GodMode9 script dumps
the save container to the card, the app edits it, and another script injects
it back, hash-checked end to end. If the check fails the script aborts and the
original container stays on the card for recovery.

## Status

In development. The core is covered by tests, including round trips against a
copy of a real card, and the full cycle (write, NAND inject, restore) has been
validated end to end on real hardware. The app never writes without an
automatic backup and an explicit confirmation. Still, it has only been
exercised on one console so far, so treat it as beta and keep your own
backups. A standalone exe with guided onboarding is the next milestone.

## Credits

- [save3ds](https://github.com/wwylele/save3ds) by wwylele handles the 3DS
  crypto and filesystem, which is the genuinely hard part
- [3dbrew](https://www.3dbrew.org/wiki/Home_Menu) for the file format
  documentation
- [Cthulhu](https://github.com/Ryuzaki-MrL/Cthulhu) by Ryuzaki-MrL, whose
  "Unwrap all" feature revealed how the gift-wrap flags work
