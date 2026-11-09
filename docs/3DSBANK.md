# 3DSBank read-only browsing

3DSort integrates discovery and bank selection through its existing Api and both
positional transports. Ordinary cards keep the existing editing lifecycle.
The active directory is always `Nintendo 3DS`; INI metadata cannot establish its
slot number because upstream renames are unchecked and configuration has
intermediate states. The active bank therefore has an unknown slot identity.

## Selection and loading

GRID and SYNC share a bank selector. Selection changes only the viewed bank,
never the console's active bank. `get_state()` adds `banks` metadata and
`select_bank(bank_id, discard_staged=False)` accepts logical IDs (`active`,
`slot:N`), not filesystem paths. Inactive region previews are refused.

Inactive loading copies only the selected encrypted HOME extdata into a private
temporary `Nintendo 3DS/<ID0>/<ID1>/extdata/00000000/<HOME-ID>` tree. The existing
save3ds extraction wrapper reads that copy; decrypted output is separate.
Source paths and descendants reject symlinks/reparse points. Source hashes are
checked across extraction; temporary data is removed on success or failure.
No title library is copied and no setup scripts or NAND payloads are published.
Keys still must match ID0. Currently there must be exactly one compatible HOME
candidate: multiple regions or ID1 directories are explicitly rejected. Region
selection for ambiguous inactive banks remains future work.

The helper source selects the movable-derived ID0 and first ID1. The temporary
tree isolates the chosen candidate and retains crypto-relative extdata paths.
Synthetic path-sensitive helpers validate this application flow. Extraction with
the actual bundled helper and physical-console compatibility remain unverified;
no public encrypted fixture with suitable synthetic boot9 resources was added.

## Partial layout representation

Only the inactive bank's SaveData and title caches supply titles and positions.
Shared NAND Launcher is never paired with inactive data. Folder membership is
preserved; referenced folders are accessible as ?Unknown folder N?, with no
fabricated HOME tile positions or names. Folder rows are a display convention,
not a recovered console setting. Unknown gaps do not become inferred system apps.
NAND titles, cartridge position, badges and complete grid composition are unknown.
A visible partial-layout warning accompanies inactive browsing.

## Safety and restrictions

Inactive banks reject layout edits, sorting, badge changes, undo/redo/reset,
manual backups, restoration, SD writes, write recovery and NAND injection actions
at the serialized backend boundary. The commit boundary also guards mutations.
Preset library management remains available; applying a preset is blocked.
UI drag/drop and edit actions are disabled or report the restriction.

Bank changes require explicit staged-change discard confirmation. Interrupted
write journals and pending NAND injections block switching. Failed inactive loads
retain the prior session; successful changes start fresh undo/redo history.
Returning to active uses the existing import and write lifecycle. Directory
replacement/removal invalidates active editing until re-import. Changed inactive
sources are reported as a previously loaded snapshot; Import refreshes the view.
Session selections are not persisted. Changing cards while inactive requires
returning to the active bank first.

Inactive writing, restoration, NAND changes, slot management, naming, INI edits
and console bank switching are unsupported. A writing phase still needs bank-aware
identity/backup/recovery design, a shared-NAND policy and hardware validation.

## Validation

`tests/test_bank_integration.py` exercises path-sensitive extraction, distinct
collections, switching, backend mutation rejection, staging confirmation,
failed-load preservation, recovery, ordinary cards, incompatible saves, ambiguous
regions/ID1 directories, source changes and source-byte preservation.
`tools/test_3dsbank_ui.cjs` exercises the real API and rendered selector, switching,
confirmation cancellation/acceptance, read-only feedback and SYNC status.
Existing spatial, multiselect and RULES browser checks and resource selftest pass.
The previous Python UI-boot HTTP 503 disappears with localhost excluded from the
proxy (`NO_PROXY=localhost,127.0.0.1`). These results establish synthetic regression
coverage only, not physical-console compatibility.

Latest validation: 351 Python tests passed, 9 skipped; all four browser scripts
and `python app.py --selftest` passed. Browser screenshot: `.cache/3dsbank-ui.png`
(local artifact, not committed). README makes no new compatibility claim.
