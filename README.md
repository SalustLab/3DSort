<div align="center">

<img src="docs/images/logo.png" alt="3DSort" width="120">

# 3DSort

**Rearrange your Nintendo 3DS HOME menu from your PC.**

[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-4a3f35?style=flat-square)](#running-from-source)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776ab?style=flat-square&logo=python&logoColor=white)](#running-from-source)
[![Tests](https://img.shields.io/badge/tests-151%20passing-7ac70c?style=flat-square)](#tests)
[![Hardware validated](https://img.shields.io/badge/hardware-validated%20on%20a%20real%203DS-d31e40?style=flat-square)](#status)
[![License](https://img.shields.io/badge/license-GPL--3.0-blue?style=flat-square)](LICENSE)
[![Version](https://img.shields.io/badge/version-v1.1.0-d31e40?style=flat-square)](#status)

</div>

> [!NOTE]
> **Built with AI assistance.** Much of this code was written with Claude. The
> 3DS file formats were reverse engineered against real dumps, and every write
> path was validated on real consoles before release.

Organizing icons on the console itself is slow: one stylus drag at a time, page
by page. 3DSort edits the layout directly on the SD card instead. Put the card
in your computer, sort your games automatically by alphabetical order or release year, or manually drag things around and manage folders in a desktop app, check the live preview,
then write the result back and boot the console.

**[Download the latest release](https://github.com/SalustianCreativeLabs/3DSort/releases/latest)**
— a `.zip` with a single portable `.exe` for Windows, no installer and no Python needed.

![The GRID tab: live console preview on the left, drag-and-drop grid of real game icons on the right](docs/images/grid.png)

> [!IMPORTANT]
> Every write takes an automatic backup first, and nothing touches the card
> until you confirm. When you move system apps or folders, do not boot the HOME
> menu between writing on the PC and running the inject script on the console.

## What it does

- Swap any two tiles by dropping one onto the other: games, system apps,
  folder tiles, even the Game Card slot
- Move games and system apps in and out of folders
- Create, rename, empty and delete folders
- Sort presets (A to Z, Z to A, release date oldest or newest first)
- Live preview that reproduces the console screen exactly, for every view
  setting from 1x60 to 6x10
- Every change is staged in memory first, with undo, redo and reset. Nothing
  touches the card until you hit WRITE and confirm
- A backup of the current layout is taken automatically before every write,
  and any backup can be restored later
- Every write also unwraps gift-boxed icons in bulk (same mechanism as
  Cthulhu's "Unwrap all") and preserves the HOME menu theme you picked on the
  console, even when restoring an old backup

## Writing and backups

![The SYNC tab: SD card status, import and backup buttons, and a restorable history of every write](docs/images/sync.png)

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
- A PC with an SD card reader. On Windows also the WebView2 runtime, which
  ships with Windows 10 and 11 by default
- The console's `boot9.bin` and `movable.sed`. You do not copy these by hand:
  the app writes a `3DSort_dump` script to the card and that script dumps them
  for you, along with the HOME menu save

Regions: USA is supported and tested on real hardware. CHN, EUR, KOR, JPN, TWN are supported from documented ids but have never been run on a console,
so treat them as "it should work just fine" but remains untested. A region the app does not know refuses to dump rather
than guessing, and every write to the console NAND is gated by checksums that
abort on a mismatch.

<div align="center">
<img src="docs/images/wizard.png" alt="First-run setup: the app walks you through dumping the console data" width="720">
</div>

The first run walks you through it: pick the SD card, run `3DSort_dump` on the
console, press verify. Settings has a "Setup guide" entry that reopens the same
walkthrough at any time, and the INSTRUCTIONS tab keeps the whole procedure for
reference.

![The INSTRUCTIONS tab: entering GodMode9, running the scripts, troubleshooting](docs/images/instructions.png)

One warning about keys: always let `3DSort_dump` take `movable.sed` fresh from
the console. Do not reuse one from an old NAND backup. If the console was
formatted or system-transferred since that backup, the old key will not decrypt
the current card. The app checks for this and says so, rather than failing with
a cryptic error.

## Running from source

```
pip install -r requirements-dev.txt

python app.py                 # native window, real SD card
python app.py --serve         # same app in the browser at http://127.0.0.1:8347
python app.py --serve --mock  # synthetic data, no SD or keys needed
```

### Tests

```
python -m pytest tests -q     # 151 tests
```

The suite runs on any machine. Tests that need real console keys skip
themselves automatically, and a guard test fails if anything ever writes to a
real SD card.

## Building the portable exe (Windows)

```
pip install -r requirements-dev.txt
pyinstaller 3DSort.spec
dist\3DSort.exe --selftest    # verifies the bundled resources, exit code 0
```

The result is a single portable `dist\3DSort.exe` with no installer. The UI,
the fonts, the icon and the save3ds binary are bundled, so the app needs no
network access at runtime. The icon itself is generated: run
`python tools/make_icon.py` to redraw `ui/3dsort.ico` after changing it.

## Linux (run from source)

The app itself is portable. Two things need attention:

```
pip install -r requirements.txt
pip install pywebview[gtk]     # or pywebview[qt]
```

pywebview needs an explicit GUI backend on Linux. For GTK on Debian or Ubuntu:
`sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1`.
The folder picker falls back to tkinter in `--serve` mode only, which needs the
distro's `python3-tk` package.

The save3ds binary is Windows-only in the upstream releases, so build it once:

```
git clone https://github.com/wwylele/save3ds
cd save3ds/save3ds_fuse && cargo build --release --no-default-features
cp target/release/save3ds_fuse <3DSort>/tools/save3ds/save3ds_fuse
```

SD card auto-detection looks under `/media/<user>`, `/run/media/<user>`, `/mnt`
and `/Volumes`. Any other mount point can be picked in Settings.

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

Beta. The core is covered by 151 tests, including round trips against a copy of
a real card, and the full cycle (write, NAND inject, restore) has been validated
end to end on two different consoles from one region (N3DS, N3DSXL both USA). The app never writes without an automatic
backup and an explicit confirmation.

## License

[GPL-3.0](LICENSE). The bulk unwrap mechanism was reimplemented from
[Cthulhu](https://github.com/Ryuzaki-MrL/Cthulhu), which is GPL-3.0, so 3DSort
carries the same license.

## Credits

- [save3ds](https://github.com/wwylele/save3ds) by wwylele handles the 3DS
  crypto and filesystem, which is the genuinely hard part
- [3dbrew](https://www.3dbrew.org/wiki/Home_Menu) for the file format
  documentation
- [Cthulhu](https://github.com/Ryuzaki-MrL/Cthulhu) by Ryuzaki-MrL, whose
  "Unwrap all" feature revealed how the gift-wrap flags work
