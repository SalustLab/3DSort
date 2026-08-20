# Linux testing

3DSort ships a Linux x86_64 tar.gz built by GitHub Actions on Ubuntu 24.04
(glibc 2.39 or newer required). This checklist covers validating a release
build safely. The read path and the write/inject cycle are the same code
validated on real consoles from Windows and macOS; hardware validation from
Linux is recorded in the README and CLAUDE.md once completed.

## Build and UI smoke test

From the repository root, with Python 3.10+ and Rust installed, on a distro
with the GTK backend available (Debian/Ubuntu package names shown):

```sh
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 \
  gir1.2-webkit2-4.1 libwebkit2gtk-4.1-0 python3-tk
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements-dev.txt
bash tools/build_save3ds_macos.sh      # cross-platform despite the name
.venv/bin/python -m pytest tests -q
.venv/bin/python -m PyInstaller --clean --noconfirm 3DSort.linux.spec
dist/3DSort/3DSort --selftest
dist/3DSort/3DSort --mock
```

`--selftest` checks the bundled resources and exits 0. `--mock` opens the app
with synthetic data, so nothing can touch a mounted card. A smoke test only
counts with a screenshot of the rendered window: a live process with a window
title proves nothing.

To validate the actual release artifact, download the tar.gz from the release
page, extract it outside the repository, and repeat `--selftest` and `--mock`.

## Read test with a console card

1. Insert the card and confirm the mount under `/media/<user>` or
   `/run/media/<user>` is the intended card.
2. Launch `3DSort/3DSort` without `--mock`. On the first import, 3DSort
   publishes `gm9/scripts/3DSort_dump.gm9` to the card. That helper script is
   the only setup write.
3. Eject the card, boot the console into GodMode9, and run `3DSort_dump` from
   HOME, Scripts. It copies `movable.sed`, `boot9.bin` and the HOME menu save
   into `0:/3DSort/`.
4. Reinsert the card and import again. The app should identify the console
   region and show the real HOME layout.

## Write and inject

The write path is the same code validated on real consoles from Windows and
macOS, and every write takes an automatic backup first. Until a full
write/inject/restore cycle has been completed from Linux, prefer a card you
have separately backed up, and follow the INSTRUCTIONS tab in the app.

Never publish console keys, `movable.sed`, `boot9.bin`, HOME saves, or a card
image. Keep those files local.
