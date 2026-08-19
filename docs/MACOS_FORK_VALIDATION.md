# macOS arm64 fork validation report

This report records the Apple Silicon port of 3DSort and the real-card read
test performed on 2026-08-19. It is intentionally detailed so a contributor
can reproduce the result without relying on the development conversation.

Published fork: [`appleforever11/3DSort`](https://github.com/appleforever11/3DSort),
branch [`macos-port`](https://github.com/appleforever11/3DSort/tree/macos-port).

## Executive result

The packaged app ran natively on an Apple Silicon Mac running macOS Tahoe
26.6.2. It read and decrypted the HOME menu data from a real USA New Nintendo
2DS XL card, loaded 68 HOME items, showed the same layout in the live preview
and editable grid, and reported zero staged changes.

The test stopped before `WRITE` and before `3DSort_inject`. No layout, NAND
save, or console state was modified by the macOS app.

## Test hardware

### Mac

| Field | Value |
| --- | --- |
| Operating system | macOS Tahoe 26.6.2, build 25G83 |
| Architecture | Apple Silicon / arm64 |
| Python used for the build | 3.13.14 |
| PyInstaller | 6.22.2 |
| App output | `dist/3DSort.app` |
| Native helper | Mach-O 64-bit executable, arm64 |
| Card connection | MacBook physical SD reader with microSD-to-SD adapter |

### Console and card

| Field | Value |
| --- | --- |
| Console | New Nintendo 2DS XL (2DS XL family) |
| Region detected by the dump | USA |
| Console software needed by the workflow | Luma3DS custom firmware and GodMode9 |
| Card volume name | `3DS` |
| macOS mount point | `/Volumes/3DS` |
| File system | FAT32 / DOS_FAT_32 |
| Card capacity reported by macOS | 255.8 GB |
| Allocation block size | 32,768 bytes |
| Used/free at validation | 99.7 GB used / approximately 156.0 GB free |

The console serial number, `movable.sed`, `boot9.bin`, id0, and card image were
not copied into the repository or published. The exact firmware version was
not needed for this read test and is intentionally not claimed here.

The Windows 11 build was available in Parallels as a reference environment.
The macOS validation itself was performed natively on the Mac against the card
through the physical reader.

## What changed in the fork

The upstream project was a Windows-first Python/pywebview application. The
macOS port adds:

1. A native Apple Silicon `save3ds_fuse` helper built from
   [wwylele/save3ds](https://github.com/wwylele/save3ds) with FUSE disabled.
2. A proper PyInstaller onedir `.app` bundle rather than a one-file executable
   nested inside an application bundle.
3. Apple Silicon packaging metadata with bundle identifier
   `com.salustlab.3dsort` and a macOS 14 minimum deployment target.
4. A stable `script/build_and_run.sh` workflow with `--verify`, `--debug`,
   `--logs` and `--mock` behavior.
5. A macOS packaging test that checks the native helper and application bundle.
6. A GodMode9 dump-script guard that creates `0:/3DSort` if it does not exist.
   This was caught before the real console run; the original script assumed the
   output directory already existed.
7. A public, reproducible macOS testing checklist in
   [`MACOS_TESTING.md`](MACOS_TESTING.md).

## Build and automated checks

The source environment was prepared with Python 3.13 and Rust. The native
helper was built with:

```sh
tools/build_save3ds_macos.sh
```

The full Python test suite produced:

```text
146 passed, 7 skipped
```

The packaged resource self-test produced:

```text
ok   ui/index.html
ok   tools/save3ds/save3ds_fuse
ok   core/titledates.json.gz
```

The packaged launch verification used:

```sh
./script/build_and_run.sh --verify
```

PyInstaller reported the target as `macOS-26.6.2-arm64-arm-64bit-Mach-O`,
created `dist/3DSort.app`, launched it successfully, and the launcher stopped
the verification instance afterward.

The local bundle is ad-hoc signed by the build tooling for development. It is
not represented as Developer ID signed or notarized; distribution signing is a
separate release task.

## GodMode9 dump and card evidence

The app first published the corrected `3DSort_dump.gm9` helper to:

```text
/Volumes/3DS/gm9/scripts/3DSort_dump.gm9
```

The card was removed from the Mac, the console was booted into GodMode9, and
the script was run from **HOME → Scripts...**. The script created the output
folder and produced these files:

| File | Size | Purpose |
| --- | ---: | --- |
| `3DSort/boot9.bin` | 65,536 bytes | Console crypto material used by save3ds |
| `3DSort/movable.sed` | 320 bytes | Console-specific key material used to identify/decrypt the card |
| `3DSort/homemenu_save.bin` | 65,536 bytes | USA HOME menu system save dump |
| `3DSort/homemenu_save.bin.sha` | 32 bytes | GodMode9 SHA-256 sidecar |

The sidecar was independently recomputed on the Mac and matched the HOME save
exactly. The key and save files were not uploaded, committed, or placed in the
fork.

## Real-card read/extract test

The first pass used the Python API with `sd_root=/Volumes/3DS` and disabled only
the automatic script-publish callback. That kept the pass read-only while
testing the actual card data. It returned:

```text
error = None
region = USA
item_count = 68
staged_count = 0
```

The packaged application was then launched explicitly against the same mount:

```sh
/usr/bin/open -n dist/3DSort.app --args --sd /Volumes/3DS
```

The real window displayed:

- `LIVE PREVIEW` of the imported HOME screen;
- the 68-title layout with folders and system entries;
- `SYNCED` in the Grid tab;
- `/Volumes/3DS` and `Nintendo 3DS folder found` in Sync;
- `99.7 GB used` and `1,190,458 blocks free`;
- `NOTHING STAGED`;
- the GodMode9 dump/inject instructions in the Instructions tab.

The app was closed after the read test. The dump files retained their original
timestamps and sizes. No `WRITE` button was activated, no backup was created by
the app, no `3DSort_inject.gm9` flow was run, and no HOME menu boot occurred
between a PC write and an inject because there was no PC write.

## Why this is a stronger macOS deliverable

The upstream README credits Claude and documents a successful Windows-first
project. This branch is a second engineering pass focused on the actual Mac
hardware in use. The improvements are concrete:

- the helper is compiled for the host CPU instead of relying on a Windows `.exe`;
- the app launches as a Finder-visible macOS bundle;
- the development launcher defaults to synthetic data so an accidental UI probe
  cannot inspect a mounted card;
- the real-card path accepts macOS `/Volumes` mounts and an explicit `--sd`
  override;
- the packaging test catches missing helper/resources before a user opens the
  app;
- the GodMode9 output-directory defect was caught and fixed before hardware
  validation;
- the card read was verified through both the API and the packaged UI;
- the report includes screenshots and exact observed values instead of only a
  successful build claim.

That is the meaningful macOS-versus-Windows advantage in this fork: the Mac
path is native to the machine, repeatable, and backed by a documented
read/extract test on the target console family. It does not require claiming
that every operating-system feature is universally better.

## Safety and privacy boundary

This validation deliberately did not test mutation. The following actions were
not performed on the card:

- pressing `WRITE`;
- running `3DSort_inject.gm9`;
- modifying the HOME layout;
- modifying the NAND system save;
- publishing console keys, saves, serials, id0, or a card image.

The next safe step for a release candidate would be a write/inject/restore test
against a separately backed-up card or image, with the same checksum gates and
automatic-backup behavior reviewed independently.
