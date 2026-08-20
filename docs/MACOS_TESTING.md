# macOS testing

3DSort runs on Apple Silicon Macs (macOS 14 or later). The read path was
validated on real hardware in August 2026: the packaged app imported and
decrypted the HOME layout of a USA New Nintendo 2DS XL from a card mounted at
`/Volumes/3DS`, showing 68 items with a matching live preview. The write and
inject cycle has not been hardware-tested from a Mac yet.

## Build and UI smoke test

From the repository root, with Python 3.10+ and Rust installed:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
tools/build_save3ds_macos.sh
.venv/bin/python -m PyInstaller --clean --noconfirm 3DSort.macos.spec
dist/3DSort.app/Contents/MacOS/3DSort --selftest
/usr/bin/open -n dist/3DSort.app --args --mock
```

`--selftest` checks the bundled resources and exits 0. `--mock` opens the app
with synthetic data, so nothing can touch a mounted card.

## Read test with a console card

1. Insert the card and confirm the mount under `/Volumes` is the intended card.
2. Launch `dist/3DSort.app` without `--mock`. On the first import, 3DSort
   publishes `gm9/scripts/3DSort_dump.gm9` to the card. That helper script is
   the only setup write.
3. Eject the card, boot the console into GodMode9, and run `3DSort_dump` from
   HOME, Scripts. It copies `movable.sed`, `boot9.bin` and the HOME menu save
   into `0:/3DSort/`.
4. Reinsert the card and import again. The app should identify the console
   region and show the real HOME layout.

## Write and inject

Not yet hardware-tested from a Mac. The write path is the same code validated
on real consoles from Windows, and every write takes an automatic backup
first. Still, until someone completes a write/inject/restore cycle from a Mac,
prefer a card you have separately backed up, and follow the INSTRUCTIONS tab
in the app.

Never publish console keys, `movable.sed`, `boot9.bin`, HOME saves, or a card
image. Keep those files local.
