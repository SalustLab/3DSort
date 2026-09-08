# Exact positions and badge collection editing

Shipped in v1.2.0 (2026-09-07) after the console validation recorded in
[BADGES_TESTING.md](BADGES_TESTING.md).

## Behavior

- Import preserves gaps. Moving an item into an empty cell leaves its source
  empty. Unrelated items never move as a side effect of a swap or folder change.
- A-Z/date presets reorder games only among their occupied cells, separately in
  each container. `Compact games` explicitly fills available cells in the current
  container while keeping NAND, cart, folders and badges fixed.
- GRID has a collapsible badge collection with search, set filter, stock and
  deferred images. Select/click or drag to place, drag to move, return to remove.
- Composite badges move as groups into free areas; single-cell items can swap.
  Folder membership and folder-icon decoration use separate actions. Emptying a
  folder retains its decoration; deleting it returns the decoration to stock.
- `compact_games(folder=-1, rows=4)` compacts the whole container after
  2026-09-07: every item (games, badges, and with a writable launcher the system
  apps, folder tiles and Game Card) moves in position order into the lowest free
  cells; aligned multi-piece badges move as a block, and the launcher is dirty
  only if a system/folder/cart item changed cell. `rows` is the HOME row setting
  used for block geometry. `sort_preset(preset, rows=4)` applies the same
  compaction with an explicit order per container: system apps, Game Card,
  folders (relative order kept), badges by name, then the games in preset order.
- `folder_create(name=None, decoration=None)`: the optional `decoration` is the
  catalog id of a single-piece badge, staged as the new folder's icon in the same
  change (undo removes both). Staged labels name the item and its 1-based cell.
- With no readable Launcher, unknown positions remain reserved and empty-position
  and cross-container editing is disabled. Known game swaps/presets still work.
- Real cards with badge extdata are editable since 2026-09-07 (`HARDWARE_VALIDATED`
  opened after the console cases in `docs/BADGES_TESTING.md`). The parser still
  fails closed on unknown records, and a card whose badge files changed between
  import and write is refused.

## Internal and public contracts

Snapshots add `game_pos`, `save_raw`, `folders_known`, `badge_source` and
`badge_layout`. Raw SaveData is snapshot-owned; badge collections use content
references into the private workdir, avoiding 16 MB copies in every undo snapshot.
`order` is derived from explicit positions and remains available for compatibility.

Existing entity keys remain unchanged; `b:<layout-slot>` identifies an occurrence,
while integer catalog IDs identify owned badge types. Empty cells have coordinates,
not entity keys. Catalog IDs, occurrence slots and image indices are distinct.

Both HTTP and js_api use positional arguments and return the full updated state:

| Operation | Positional arguments |
| --- | --- |
| Move to empty position | `move_to_position(key, folder, pos, rows=4)` |
| Compact games | `compact_games(folder=-1)` |
| Place owned badge | `place_badge(badge, folder, pos, rows=4)` |
| Place in first fitting area | `place_badge_in_folder(badge, folder, rows=4)` |
| Return badge/group | `remove_badge(key, rows=4)` |
| Set/remove folder decoration | `decorate_folder(fid, badge=None)` |
| Deferred images | `get_badge_images(ids)` (at most 32; returns ID-to-PNG map) |
| Recover an interrupted write | `recover_write("complete" | "restore")` |

`set_folder`, `folder_empty` and `folder_delete` accept an optional row count for
HOME composite geometry. Existing calls remain valid. `get_state` adds `badges`,
`spatialWritable`, `layoutErrors` and `recovery`.

## Writes and backups

Preparation uses a fresh card extract and rejects changed layouts/collections.
Theme grafting remains mandatory; failure to read the fresh base aborts. All
extdata and the optional Launcher payload are prepared before any import.

An automatic `.3dsl` backup stores the fresh HOME tree, NAND metadata, complete
`__badges__/` tree when present, and a version-2 `__layout__/manifest.json`.
Backups remain local personal data. Old archives without badges keep the current
collection. New namespaces are removed before importing HOME extdata. Use the
new app to restore backups containing badge data; older app versions do not know
how to separate the new archive namespaces.

The workdir's `transaction/journal.json` records card identity, prepared state,
backup ID, file hashes and completed steps. Each import is verified by reextraction,
including empty directories. Partial writes retain staging and the journal.
Recovery verifies its material and card identity, and requires an explicit action.
Writes and recovery recheck the mounted console even when its drive letter has
not changed; recovery startup rejects a different console before publishing scripts.
Starting the app never resumes a write automatically. Staging and card switching
are blocked while recovery is pending.

Multiple filesystem writes are not physically atomic. The journal and automatic
backup provide recovery, not a promise that power loss cannot interrupt a write.

## Automated checks

```powershell
python -m pytest tests -q
python app.py --serve --mock --mock-badges
```

`tools/test_spatial_ui.cjs` runs Playwright against its own mock server on port
8394. It checks positions, undo, single/composite badge moves, swaps, write/reload,
decoration, loaded images and horizontal fit. Set `PYTHON` to the interpreter and
`CHROMIUM_PATH` if using a preinstalled Chromium executable; install Playwright in
the development environment, not in runtime requirements.

The browser smoke artifact is `.cache/spatial-ui.png`. Release screenshots must
continue to use synthetic data exclusively.

Validation on 2026-09-07: 186 pytest checks passed; 9 were skipped (including
unavailable real sandbox/key integrations). The standalone Chromium UI flow and
the rebuilt executable's `--selftest` passed. The native WebView2 window was
verified the same day, twice: a source run with `webview.settings['REMOTE_DEBUGGING_PORT']`
set in-process (the `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` variable is ignored
because pywebview always sets `AdditionalBrowserArguments`), attached over CDP,
asserting `window.SERVE_MODE === undefined`, a live `pywebview.api` bridge, the
rendered grid and a staged badge placement; and a `PrintWindow` capture of the
frozen `dist/3DSort.exe --mock --mock-badges` window (the window belongs to the
onefile child process, not the bootloader). Both screenshots showed the GRID,
the empty-cell numbering and the spatial controls. Later the same day the badge
format was validated on the console (cases 01 to 18 in `docs/BADGES_TESTING.md`,
byte parity with HOME's own writes), `HARDWARE_VALIDATED` was opened, and the
full acceptance through the rebuilt exe passed: write with game + badge + folder
moves, inject, boot, restore of the automatic backup, and a badges-only write
that requested no injection. Suite: 198 passed, 3 skipped (201 collected).
