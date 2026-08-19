# macOS testing

This fork is intended for Apple Silicon Macs. The packaged app has been built
and launched on macOS Tahoe 26.6.2, but a real-card read/extract test is kept
separate from the safe synthetic-data smoke test.

## Safe build and UI smoke test

From the repository root:

```sh
python3.13 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
tools/build_save3ds_macos.sh
./script/build_and_run.sh --verify
```

The launcher passes `--mock` to the app. It exercises the packaged resources,
native arm64 `save3ds` helper, window startup, and the main Grid, Sync,
Instructions, and Settings screens without touching an SD card.

## Read/extract test with a console card

Use a complete backup or a duplicate card for this test. Do not press `WRITE`
on an original card while validating a new platform port.

1. Insert the card and confirm the mount is the intended card before launching
   the app. On macOS, the expected mount is normally under `/Volumes`.
2. Launch `dist/3DSort.app` without `--mock` and choose **Import from SD**.
   On the first import, 3DSort publishes `gm9/scripts/3DSort_dump.gm9` to the
   card. This helper is the only expected setup write before the GodMode9 step.
3. Eject the card, boot the console into GodMode9, and run the generated
   `3DSort_dump` script. It copies the console's current `movable.sed`,
   `boot9.bin`, and HOME menu system save into `0:/3DSort/`.
4. Reinsert the card and choose **Import from SD** again. A successful read test
   should identify the console region and show the existing HOME layout.
5. Stop there for a read-only port check. Leave **WRITE** and any inject flow
   untouched until the card has a separate backup and the platform test has
   been reviewed.

The app accepts the dumped files from either `/3DSort/` or `gm9/out/` on the
card. It validates that `movable.sed` belongs to the detected console before
attempting extraction. It does not require keys to be copied manually into the
Mac project.

## Current validation record

| Check | Result |
| --- | --- |
| macOS Tahoe 26.6.2 / arm64 package build | Passed |
| Bundled resource self-test | Passed |
| Native `save3ds_fuse` helper | Passed |
| Mock UI launch and navigation | Passed |
| Python test suite | 146 passed, 7 skipped |
| Real-card decrypt/extract | Pending a fresh GodMode9 dump |

Never publish console keys, `movable.sed`, `boot9.bin`, HOME saves, or a card
image. Keep those files local to the test machine.
