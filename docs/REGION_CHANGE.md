# Region-changed consoles (CTRTransfer)

A console whose region was changed with CTRTransfer showed the wrong HOME menu
layout in 3DSort: the pre-transfer game list, system apps all pinned, and no
folders. No error was reported anywhere.

## What a region change leaves behind

CTRTransfer swaps in the target region's HOME menu, but nothing removes the old
one's data. Afterwards:

- the SD card holds **two** HOME menu extdata sets under the **same** `id0`/`id1`
  — for example `00000082` (JPN) next to `0000008f` (USA);
- the NAND holds **two** HOME menu system saves — `00020082` and `0002008f`.

The pre-transfer pair is frozen at the moment of the transfer and never written
again. The new pair is the live one.

## Why upstream picked the dead pair

Two independent mechanisms, both landing on the wrong region:

1. **`find_console`** returned the first region in `HOME_EXTDATA_IDS` iteration
   order (JPN first) as soon as `prefer_id0` matched. `prefer_id0` exists to tell
   *consoles* apart on a shared card; after a region change both extdata sets sit
   under the same `id0`, so it matched the first region tested.
2. **`3DSort_dump.gm9`** chose the NAND save id from GodMode9's `$[REGION]`,
   which reads SecureInfo. A CTRTransfer does not rewrite SecureInfo, so it
   named the pre-transfer region. Both saves exist on the NAND, so the wrong one
   dumped cleanly.

The dumped container then failed its CMAC check under whichever save id the app
resolved, and `_read_launcher` discarded it silently, degrading to a read-only
layout. That degraded layout looks like a real one, which is what made the bug
hard to see.

## The fix

**Rank, then ask.** `find_consoles()` returns every HOME menu extdata candidate
ordered by (`id0` matches the card's `movable.sed`, newest write inside the
extdata). When the resolved `id0` has more than one candidate and no stored
answer, `import_sd` stops at a new `pick_region` setup stage instead of
proceeding on the ranking.

The picker lists each candidate with its games, folders and last write, and
marks the newest as suggested. The answer is stored per `id0` in
`settings.json` (`region_by_id0`) and can be changed from SYNC. A stored answer
whose extdata has disappeared is dropped and asked again.

**Dump everything, choose on the PC.** The dump script no longer consults
`$[REGION]`. It copies every HOME menu save present to
`0:/3DSort/homemenu_save_<saveid>.bin`. The app uses the one matching the
picked region and copies that pair onto `homemenu_save.bin(.sha)`, so the inject
script's gate 2 anchor keeps its single fixed path. Both files come from GM9's
own `cp --hash`, so no anchor is fabricated.

**Fail loudly.** A container that does not verify under the resolved save id is
reported through `launcherError` (a banner on SYNC) rather than hidden, and
`_write_launcher` refuses to build a NAND payload from it.

**No second opinions downstream.** Two more places re-derived the region:

- `WriteApi._connected_card_error` rebuilt the console with `find_console` and
  required it to equal the resolved one. Picking the *older* region — the case
  the picker exists for — made every write fail with "Card changed or
  disconnected". It now checks card identity only.
- Backups carried no region, so a snapshot of one layout could be restored into
  the other. Backups now record `extdataId`, and a mismatched restore is
  refused. Backups without the field stay restorable.

## Design decisions

**Why the write time and not icon counts.** The write time cannot invert: the
dead set stops being written at the transfer, however much either console state
was used. Icon counts can: a heavily used console transferred to a fresh region
leaves the *bigger* extdata behind. Counts are shown in the picker as evidence
and never used to decide.

**Why the user picks at all.** The write time is a strong signal but it is not
proof — a card copied or restored with a tool that does not preserve
timestamps flattens it. Picking wrong means editing a layout no console reads,
so an explicit answer, asked once, is worth the click.

**Why only the picked region is written.** The pre-transfer set stays
bit-identical. It is never read by the console, and leaving it untouched keeps
it as a clean fallback rather than putting both saves through the same write
path in the same run.

## Hardware validation

Reported by the contributor on a real console region-changed from JPN to USA:

- `find_consoles` ranked the live USA extdata first; the picker showed both
  candidates with correct counts and dates.
- The new dump script ran in GodMode9 and produced both
  `homemenu_save_00020082.bin` and `homemenu_save_0002008f.bin`; each
  CMAC-verifies under its own save id.
- Several SD-only layout writes through `write_sd`, each verified by
  re-extracting the extdata. The written layout survived a console boot and
  later CIA installs.
- The full launcher (NAND) cycle: `write_sd` with `launcherDirty`, then
  `3DSort_inject.gm9` in GodMode9 (all three sha gates passing), then a HOME
  menu boot showing the written layout. This is the path the earlier revision
  of this document listed as untested; the contributor had in fact run it and
  only omitted it from the write-up.

CHN/KOR/TWN remain untested as before: no console in any of those regions has
run 3DSort, region-changed or otherwise.

## Tests

`tests/test_api_region.py` covers region resolution against a synthetic
two-region card: ranking, the `pick_region` stage (and that it comes after the
keys stage), stored and stale answers, `set_region` and its guards, container
selection and promotion, `launcherError`, the card-identity check with a
non-suggested pick, and region-tagged backups. No console or real card needed.
