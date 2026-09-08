# Badge layout hardware validation

Status: **hardware validated on 2026-09-07** (USA New 3DS, cases 01 to 18 below,
byte parity with HOME's own writes). `core/badges.py` has `HARDWARE_VALIDATED =
True`; real cards containing badge extdata are editable. The parser still fails
closed on any record it does not recognise, and `write_sd` refuses to write when
the badge files changed on the card between import and write. The complete
synthetic editor remains available with `python app.py --serve --mock --mock-badges`.
The app-side acceptance run on the console (import, edit, WRITE, inject, boot,
restore, badges-only write) passed the same day; see the end of this file.

## Prerequisites: getting badges onto a CFW console

Nintendo Badge Arcade cannot deliver badges any more: Nintendo ended the 3DS
online services in 2024 and the Badge Arcade service with them (the app now
shows an error on launch). Badges already in a console's collection keep
working on the HOME menu. A console that never had badges therefore gets them
only through homebrew, which is the situation this validation starts from.

Recommended route (CFW console with Luma3DS, the same setup 3DSort requires):

1. Install **GYTB** ("Give You This Badge", by MrCheeze) from Universal-Updater
   (search "GYTB", pick the `.cia` for HOME menu installation or the `.3dsx` for
   the Homebrew Launcher). GYTB creates the badge extdata `000014d1` itself, so
   running Badge Arcade first is NOT required.
2. Create a `badges` folder on the SD root and drop 64x64 PNG files in it (one
   badge each). A larger image whose sides are multiples of 64 (for example
   64x128 or 128x128) is split automatically into a composite badge, which the
   Composites case below needs. Name the file `Name.png`; a shortcut badge uses
   `Name.<TIDLow>.png` with the TIDLow of a system app of the console's region
   (Shortcuts case). Keep the folder under 1000 images and delete any stray
   `preview.png`.
3. Run GYTB once. It writes `BadgeData.dat` and `BadgeMngFile.dat` and exits.
   Each PNG becomes one badge type with a stock (quantity) of several copies.
4. On the HOME menu, open the badge tray at the top of the touch screen and drag
   badges onto the grid; the wrench icon offers "Attach Badge to Folder" for the
   Decoration case.

Use synthetic artwork you drew yourself; never install or redistribute Nintendo
badge images. Alternative tools with more control over quantities, sets and
shortcuts: **Simple Badge Injector** (console, dump/inject the two files) plus
**Advanced Badge Editor** (PC). Any of these installers writes the catalog part
of `BadgeMngFile.dat` itself, so its records may differ from what Nintendo's
server produced; HOME only writes the placement records when you drag badges.
For that reason the validation captures BOTH a `00-before` copy (no badge
extdata at all, or the untouched collection) AND a `01-installed` copy taken
right after the installer ran and before any badge is placed.

### Observed with GYTB on the dev console (2026-09-07, USA New 3DS)

- Opening GYTB once WITHOUT a `badges` folder creates the `000014d1` extdata with
  `icon` (14016 bytes), `boss/` and an EMPTY `user/`. The app treats that as "no
  collection" (`core/layout_api.py::_load_badges`), not as a read-only card;
  `write_sd` still re-extracts the extdata and refuses to write if it changed.
- GYTB does NOT write composite badges: a 128x128 PNG became four independent
  1x1 badges (distinct badgeId, `sub = 0`, same name). The Composites and View
  changes cases therefore need data with real sub-IDs (Advanced Badge Editor, or
  a collection produced by Nintendo). Multi-piece PNGs are still useful as
  repeated-name singles.
- Every GYTB badge has quantity 65535 (unlimited stock) in one set, id `0xEFBE`,
  while the header u32 at `0x4` (set count) stays 0. The Stock case
  needs a finite quantity, editable with Advanced Badge Editor.
- The shortcut badge stores the full title id `0004001000021000` twice, at
  catalog record offsets `+0x18` and `+0x20`.
- The placement table (`0xB2E8`, 360 x 0x18) is all zero bytes when nothing has
  ever been placed.

### Proven on the console (2026-09-07, USA New 3DS, HOME at 4 rows)

Case `02-single`: one badge (`AceAttorney`, catalog #0) dragged from the tray to
column 30, row 3 (1-based) of the HOME grid, console powered off, card copied.
Diff `01-installed` vs `02-single`, HOME extdata byte-identical, `BadgeData.dat`
byte-identical, `BadgeMngFile.dat`:

| Offset | Size | Before | After | Meaning |
| --- | --- | --- | --- | --- |
| `0xC` | u32 | 0 | 1 | placed total |
| `0x3E8 + 0*0x28 + 0x10` | u16 | 0 | 1 | per-badge placed count (catalog #0) |
| `0xB2E8 + 0*0x18` | 24 | zeros | catalog record bytes 0..15, u32 pos `0x76` (118), u32 folder `0xFFFFFFFF` | placement in layout slot 0 (first free) |
| `0xB2E8 + n*0x18`, n = 1..359 | 24 each | zeros | `00000000 ffffffff ffffffff ffff0000 ffffffff ffffffff` | HOME's free-record sentinel (`badges.EMPTY_RECORD`) |

pos 118 with 4 rows = column 118 div 4 = 29 (0-based) = 30 (1-based), row 118 mod
4 = 2 (0-based) = 3 (1-based): column-major, same rule as SaveData positions.
The parser's earlier sentinel guess (all zero or all 0xFF) was wrong and failed
closed on this file, as designed; it now accepts exactly `EMPTY_RECORD` and the
GYTB zero record, and writes `EMPTY_RECORD` for removed slots.
Case `03-moved`: the same badge dragged to column 31, row 2. The ONLY change in
the whole extdata pair was one byte: slot 0 pos `0x76` (118) to `0x79` (121) at
`0xB2F8`. The layout slot is kept on a move; SaveData.dat untouched (badge
positions never live in the HOME extdata). Matches `move_to_position` exactly.

Case `04-removed`: the badge returned to the tray. Changes: `0xC` 1 to 0, catalog
#0 `+0x10` 1 to 0, slot 0 back to `EMPTY_RECORD` (bytes 4..13 and 16..23 of the
record). Exactly what `remove_badge` serializes.

Case `05-folder`: the badge placed inside folder "APPS" (Launcher folder id 0,
3-row folder view) at column 5, row 2. Record: u32 folder = `0` (the Launcher
folder id, not a position), u32 pos = `0xD` (13) = (5-1)*3 + (2-1): positions are
LOCAL to the folder and column-major with the FOLDER's row setting, exactly like
game positions (CLAUDE.md §5.4). Still layout slot 0.

Case `06-decor`: folder "APPS" (id 0, HOME position 13) decorated with `Atlus`
(catalog #9). New record in layout slot 1: catalog bytes of #9, u32 pos = `0xD`
(13), u32 folder = `0xF0FF`. `0xC` went 1 to 2 (decorations count as placed),
catalog #9 `+0x10` = 1. SaveData.dat and the Launcher untouched. The folder
field IS the `0xF0FF` sentinel as assumed, but pos is NOT the folder id (that
would be 0): it equals the folder's HOME grid position (13). Case `07-decor2`
rules out the coincidence with the inner badge, which also sat at local
position 13.

Case `07-decor2`: folder "Virtual Console" (id 1, HOME position 12, no badges
inside) decorated with `Activision` (#1). New record in slot 2: pos = `0xC`
(12), folder = `0xF0FF`; `0xC` = 3. PROVEN: a decoration record references its
folder by the folder tile's HOME position. Consequences implemented: the file
layout keeps the position, staging keeps the folder id
(`LayoutApi._badge_layout_from_file/_to_file`), so moving a decorated folder tile
in 3DSort rewrites the badge record, and a decoration whose position matches no
known folder (no Launcher dump) leaves the card read-only with an explicit
message. Regressions: `tests/test_badges.py::test_decoration_record_is_folder_home_position`,
`tests/test_api_spatial.py::test_file_decoration_*`. Case `08-folder-moved`: the decorated folder "Virtual Console" dragged from HOME
position 12 to column 31, row 1 (position 120). The only change in the badge
files was one byte: slot 2 pos `0xC` to `0x78` at `0xB328`. HOME rewrites the
decoration record when the folder tile moves, which is exactly what the
fid-to-position mapping in `write_sd` produces (byte parity confirmed).

Case `09-decor-removed`: the Virtual Console decoration removed from the folder
settings. Slot 2 back to `EMPTY_RECORD`, `0xC` 3 to 2, catalog #1 `+0x10` 1 to 0;
the file is byte-identical to case 06. `decorate_folder(fid, None)` reproduces
it byte for byte.

Case `10a-temp-folder`: a NEW folder created at HOME position 122 (Launcher id 2,
SaveData baptism number 3 written at `0x12D0`, consistent with CLAUDE.md §5.7),
`Flat2D` (#15) placed inside it, `Stereo3D` (#18) set as its decoration. Records:
slot 2 = #15, pos 0, folder 2; slot 3 = #18, pos 122, folder `0xF0FF`. Our
serializer reproduces the file except ONE unknown header field: u32 at `0x14`
went 0 to 7 on this step only (not when badges entered folder 0 or when
decorations were applied earlier). 7 = bits 0..2 with folders 0, 1, 2 existing,
so it looks like a folder bitmask the console refreshes lazily; the app
preserves whatever value the file has and the console regenerates it.

Case `10b-badge-out`: `Flat2D` dragged out of the new folder to HOME column 30,
row 4 (position 119). Slot 2: pos 0 to 119, folder 2 to `0xFFFFFFFF`; same slot,
nothing else changed. Byte parity with `set_folder`/`move_to_position`. Also
observed: HOME REFUSES to delete a folder that still contains anything, a badge
included; 3DSort's `folder_delete` is a superset (it returns members home first).

Case `10c-folder-deleted`: the empty, still decorated folder deleted. HOME cleared
the decoration record (slot 3 back to `EMPTY_RECORD`), `0xC` 4 to 3, catalog #18
`+0x10` 1 to 0; header `0x14` stayed 7 (not refreshed on delete); SaveData.dat
unchanged (the orphan baptism number, CLAUDE.md §5.7). Byte parity with
`folder_delete`, which drops the folder's decoration. Decoration case CLOSED
(apply, remove, folder moved, folder deleted; rename never touches this file).

Case `11-repeated`: `Apps` (#5) placed twice on HOME (121 and 126). Two records
with the SAME 16 identity bytes in the next free slots (3 and 4), catalog #5
`+0x10` = 2, `0xC` = 5: a layout slot is an occurrence, the catalog id is the
type, quantity is not decremented (still 65535). Byte parity with two
`place_badge` calls except the header u32 at `0x14`, which went 7 to 2 here
without any folder change: it is NOT a folder bitmask. Values seen so far: 0
(cases 01-09), 7 (10a-10c), 2 (11). Treated as volatile console state
(cursor/tray-like); the app preserves the file's value. SaveData note: the
orphan baptism number left by the folder deletion (10c) was cleared by the
console in this later HOME session (`0x12D0` 3 to 0), so the SaveData is byte-
identical to its pre-folder state again.

Case `12-shortcut`: the `Settings` badge (#17, catalog shortcut field
`0004001000021000` at `+0x18`/`+0x20`) placed at HOME 118 and tapped: System
Settings opened. Its placement record is an ordinary one (identity + pos +
folder); the shortcut lives only in the catalog, which the app never rewrites.
Byte parity except the volatile `0x14` (2 to 7 again).

Case `13-theme`: HOME theme changed on the console. Badge files byte-identical;
SaveData.dat changed 2 bytes, both inside `0x13B8..0x13BD`, i.e. the region
`write_sd` grafts from the fresh card copy (CLAUDE.md §5.4). Console half of
Preservation proven; the app-write half (an edit after a theme change keeps the
theme) needs the write gate open on this card.

Case `14-composite-installed`: synthesized entries (scratchpad tool over the
13-theme copy: `Mega2x2` = 4 records, badgeId `0x18`, subs `0x1100/0x1101/0x1110/
0x1111`, quantity 2, artwork = the GYTB Big2x2 quadrants; `LastCopy` = quantity 1;
header `0x8` 23 to 28, used bitfield bits 23..27, set `+0x1C` 23 to 28) injected
with Simple Badge Injector 1.4.2. After a HOME boot the card's files equal the
injected pair byte for byte except the volatile `0x14`; the parser accepts the
28 entries and `pieces(23)` returns the four pieces. HOME shows the mega badge
in the tray. Side observation for CLAUDE.md §5.4: installing the injector CIA
added one title to SaveData.dat at the lowest free HOME position (12) and HOME
re-indexed EVERY slot (136 of 136 slots changed) while preserving all
(tid, pos, folder) tuples; a fresh import absorbs that. Also: GYTB slices a big
image column-major (x=0,y=0; x=0,y=1; x=1,y=0; x=1,y=1).

Cases `14b`, `15`, `15c` (composites, three injections with Simple Badge Injector
1.4.2): a 2x2 badge synthesized as four catalog entries sharing badgeId and setId
with sub-IDs `0x1100/0x1110/0x1101/0x1111` (3dbrew formula, same as Advanced
Badge Editor's `.prb` import and `tasken/3ds-badge-minter`) ALWAYS shows in the
HOME tray as four separate pieces, whatever the variant: sequential image
indices, row-major image indices (`3ds-badge-minter` layout), BadgeInfo `+0x14` =
`0x0202`, or a shared non-zero BadgeIdentifier `+0x0`. Dragging one piece placed
only that piece (ordinary record: identity incl. sub `0x1100`, pos 128, folder
HOME, per-piece count 1). This is retail behaviour, not a data defect: the
Nintendo Badge Arcade documentation states that mega badges "are broken down into
pieces" on the HOME menu and the player arranges (or swaps) the pieces by hand.
The HOME menu has NO composite concept at placement level. Community research
(GBAtemp, ABE thread) identifies BadgeInfo `+0x14` as the badge PIN offset
(cosmetic) and BadgeIdentifier `+0x0` as a hash carried from the `.prb`; neither
affects layout. Consequence in 3DSort: piece grouping is an app convenience only;
scattered or swapped pieces are handled as single badges
(`tests/test_api_spatial.py::test_composite_pieces_are_independent_badges_like_on_the_console`).
"View changes" is therefore moot for the file: the row setting only changes how
the same positions render.

Case `18-stock`: `LastCopy` (quantity 1) placed once at HOME 122 and a piece with
quantity 2 (#33) placed a second time at 156. Records: two ordinary placements in
the next free slots; catalog `+0x10` placed counts 1 and 2; `quantity` fields
UNCHANGED (1 and 2); header `0x18` (total inventory) unchanged. Quantity is the
TOTAL owned, availability = quantity minus placed, exactly `Badges.validate`
(`count > quantity` refused) and the UI's "available" counter. Byte parity except
the two volatile header words `0x10` (selected badge set: 0 to `0xFFFFFFFF`, the
user switched the tray back to "All badges") and `0x14` (selected column), both
documented by 3dbrew as UI state; the app preserves them.

Case `17-rows`: HOME switched to 3 rows, nothing touched. `BadgeMngFile.dat` and
`BadgeData.dat` byte-identical to case 18 (same hashes); SaveData.dat unchanged
too. Positions are stored independently of the view. The tray also REFUSED a
second `LastCopy` and a third copy of the quantity-2 piece (user-observed),
matching `Badges.validate`.

Status of the ten cases after 2026-09-07: Empty layout, Single badge, Folder
member, Decoration, Repeated copies, Shortcuts and Stock PROVEN with byte parity;
Composites resolved (no composite semantics on the console, pieces are
independent badges, case 15/15c); View changes moot for the file (case 17
confirms the table does not change with the row setting); Preservation proven
on the console side (theme bytes confined to the grafted region), app-write side
pending the gate. Composites, View changes
and Stock need badge data with real sub-IDs / finite quantities (Advanced Badge
Editor), which GYTB does not produce.

Byte parity: feeding each "before" file to `Badges.serialize` with the layout the
user produced on the console reproduces HOME's own "after" file byte for byte
for all four transitions (01 place at 118 = 02; 02 move to 121 = 03; 03 remove
= 04; 04 place in folder 0 at 13 = 05). The serializer also normalizes GYTB's zero records to `EMPTY_RECORD`, as
HOME does on its first write.
Regression: `tests/test_badges.py::test_home_written_empty_records_and_first_placement`;
the real file round-trips byte-identically through
`tests/test_integration.py::test_badge_reader_roundtrip_on_real_sandbox`.

## Capture controlled before/after cases

All console actions and real-card writes are performed manually by the owner.
Never run tests or experiments against `G:`. Keep original card copies and keys
under the ignored `sandbox/` directory; do not publish these files or reports.

The `3DSort_dump.gm9` script copies only the HOME container, `movable.sed` and
`boot9.bin` into `0:/3DSort/`; it does NOT copy badge extdata. Every snapshot is
therefore a copy made from the PC with the SD card mounted. A partial copy is
enough because the CTR derives from the path relative to the id1 folder: copy
`Nintendo 3DS/<id0>/<id1>/extdata/00000000/<HOME extdata id>` and
`.../00000000/000014d1` (about 16 MB) plus `<sd>/3DSort/` (keys and container),
keeping the same relative paths under `sandbox/badge-validation/NN-<case>/sd/`.

1. Back up the complete SD card. In GodMode9 run the existing 3DSort dump script
   to obtain the fresh HOME container and keys. Boot HOME and choose a fixed row
   setting. Record the setting and the exact action for each case.
2. Capture a baseline card copy under `sandbox/badge-validation/00-before/sd/`.
   After each single action below, shut down normally and make another copy.
   Preserve the matching fresh GodMode9 HOME container for cases involving folders.
3. Extract both the regional HOME extdata and badge extdata from each **copy**,
   using the existing save3ds helper and that copy's keys. Badge extdata ID is
   `00000000000014d1`; its extracted tree contains `user/BadgeData.dat` and
   `user/BadgeMngFile.dat`, plus `icon` and `boss/`. Preserve the complete tree.
   The extraction call is the same one `core/layout_api.py::_load_badges` makes:
   `Save3ds.extract("00000000000014d1", <copy root>, <out dir>)` with that
   copy's `boot9.bin` and `movable.sed`.
4. Compare the extracted badge trees with:

   ```powershell
   python tools/inspect_badge_dumps.py sandbox/badge-validation/00-before/badges sandbox/badge-validation/01-after/badges
   ```

   This command only reads files and prints a structural report. It does not
   extract, import, copy keys, or write to the card.

Required individual cases. The first group (Empty layout, Single badge, Folder
member, Composites, Preservation) establishes which cells a badge occupies and is
what unblocks ordinary layout writes on a card that has badge extdata; the second
group (Repeated copies, Stock, Decoration, View changes, Shortcuts) is needed
before real badge writes are enabled.

| Case | Action and evidence |
| --- | --- |
| Installed collection | Capture right after the installer ran, before placing anything; confirm the parser accepts installer-written catalog records and the placement table is empty. |
| Empty layout | Remove all placed badges without deleting the collection; identify every empty-record sentinel. |
| Single badge | Place one, move it to a gap, then remove it; record changed counters and positions. |
| Repeated copies | Place two copies of the same badge, remove the first, then place it again; distinguish layout slot from catalog index. |
| Stock | Place the last available copy and return it; establish whether quantity is total or remaining. |
| Folder member | Move a badge HOME → folder → HOME; establish local positions and folder encoding. |
| Decoration | Apply, replace and remove a folder decoration; move and rename the decorated folder, then delete it. PROVEN (06/07): the record identifies the folder by the folder tile's HOME position, folder field `0xF0FF`. Move/remove/delete still to capture. |
| Composites | Test 2×1, 1×2 and 2×2, including repeated copies, first/last rows, page edges and moving between HOME and folders. |
| View changes | Change row settings after placing a composite, then move/remove it. Establish how occurrence grouping survives the change. |
| Shortcuts | Move a badge that launches a system app; verify its shortcut still works. |
| Preservation | Change theme independently; ensure layout edits and restore preserve the current theme and collection. |

The current implementation models composite membership by identifier plus
relative piece positions. It rejects ambiguous or misaligned pieces rather than
guessing. The folder-decoration mapping, free-record encoding, alpha orientation,
stock semantics and composite grouping still need the cases above. These are
documented assumptions, not empirical discoveries.

## Validate the implementation against those cases

- Record exact offsets, sizes, byte diffs and proof in CLAUDE.md after review.
- Reproduce each case with synthetic fixtures. No real artwork, identifiers,
  account data, containers or keys belong in tests or screenshots.
- For every unedited real input, require byte-identical parser/serializer output.
- Generate edited trees on copies, reimport with real save3ds **on sandbox copies**,
  reextract and compare. Preserve all directories and unrelated bytes.
- Enable the real writer only after correcting and testing every ambiguous field.
  No environment variable or UI setting currently bypasses this gate.

## Manual console acceptance after the gate is satisfied

Rebuild the executable; never use an old `dist/3DSort.exe`. Start with a restorable
card backup. Validate import → stage → WRITE → inject when requested → boot →
reimport for spaces, stock, composites, folder members and decorations. Badges-only
edits must not request a NAND injection. Check shortcuts and themes too.

Test restoring a new backup and an old backup without badges. Old backups retain
the current collection and can expose collisions that must be resolved before
WRITE. Undo/redo must restore both positions and the selected collection source.

An interrupted write must remain visible in SYNC. **Complete write** reapplies the
prepared snapshot; **Restore pre-write backup** reinstates the saved base. These
are explicit write actions. Do not boot HOME or inject a partial payload before
recovering. To test failures, use fault injection in the mock tests, not deliberate
card removal during a real write.

If an injection includes a badge layout, cancellation is blocked: new badge
positions may conflict with the old NAND layout. Complete/verify the injection
first, then restore the desired backup through staging.

## Acceptance run through the app, 2026-09-07 (USA New 3DS, dev card)

All steps through `dist/3DSort.exe --sd H:\` (rebuilt after the gate opened,
`--selftest` 0, native window captured), console actions by the owner, results
verified on decrypted copies (`sandbox/badge-validation/20..23`):

| Step | Result |
| --- | --- |
| Fresh `3DSort_dump`, import | 137 titles, 2 folders, 36 badges, 11 placed, no layout errors (a stale dump correctly showed one collision first) |
| Stage: game to an empty cell, badge to an empty cell, decorated-free folder tile to an empty cell; WRITE | Automatic backup; SaveData: only that game moved (18 to 123), theme region identical, status zeroed; badge file: only that record moved (122 to 125); Launcher payload: folder 120 to 124 |
| `3DSort_inject`, boot HOME | Positions as staged on the console; post-boot capture byte-identical to what the app wrote (SaveData and badge file) |
| Restore the automatic backup, WRITE, inject, boot | SaveData and badge file byte-identical to the pre-write state; payload Launcher back to 120; GM9 receipt matched the payload; next app start promoted it and removed the inject script |
| Badges-only edit (badge moved 122 to 130, Virtual Console decorated with a badge), WRITE | No inject requested, no post-write warning, no marker; new decoration record pos 120 (the folder tile position), folder `0xF0FF`; SaveData untouched; console showed both |

The app numbers empty cells from 1 in the UI; the file positions are 0-based.

## Format references

- [3dbrew HOME Menu badge format](https://www.3dbrew.org/wiki/Home_Menu#Home_Menu_badge_SD_ExtData)
- [Anemone3DS badge implementation](https://github.com/astronautlevel2/Anemone3DS/blob/master/source/badges.c)

The reader/writer is a new implementation; the references establish documented
fields but do not replace hardware verification of layout edits.
