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

`banks.warnings` keeps discovery diagnostics (configuration, enumeration, the
suggested-but-unverified active slot) for internal use; the header never shows
them. `banks.alerts` holds only what the user must act on (a viewed bank that
changed on the card, an active bank replaced since import) and is always shown.

Header messaging: the selector lists `Active bank` and each slot by its
configured name (`Slot N` otherwise). The active bank shows no status line unless
an alert exists; an inactive bank shows `Read-only · Some system items aren't
shown.` An info indicator (keyboard-focusable, labelled for assistive technology)
explains that switching only changes what 3DSort displays, not the console's
bank, and that inactive layouts may be incomplete. The selector row stays level
with the SD text in the same type; the status line hangs below it inside the
56 px header.

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

### Import of the active bank is not filesystem-read-only

Bank discovery and inactive loading never write to the card. Importing the
active bank (`import_sd`, including returning to `active` from an inactive bank)
still runs the ordinary import lifecycle, which publishes
`gm9/scripts/3DSort_dump.gm9` to the SD on every import (`Api._publish_dump_script`
in `app.py`), creating `gm9/scripts/` if needed. Viewing the active bank therefore
writes that one file even when nothing is edited. Test against a copy of the
card (for example under the ignored `sandbox/`) when the card must stay untouched.

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
confirmation cancellation/acceptance, read-only feedback and SYNC status. It also
checks the header at 929, 1280 and 1920 px for the active bank, an inactive
bank, an injected alert and an ordinary card without 3DSBank: every header item
stays inside the 56 px bar without overlap, SD information wraps to at most two
lines, the selected bank name is never truncated, the selector row is level with
the SD text, no internal diagnostics are shown and the page never scrolls
horizontally. It also checks the exact labels and messages, and that the
read-only lock on WRITE is lifted on returning to the active bank without a
reload (it used to persist until a page reload). Optional `PYTHON` and `CHROMIUM_PATH` work as in the
other browser scripts.

Real card (2026-11-09, browser transport against a copy of the card without
title contents): discovery found the active directory and `Slot1`; `Slot1`
stores its ID0 directly, with no `Nintendo 3DS` level. The active bank loaded
its full layout; `Slot1` loaded read-only with no titles (it holds only HOME
extdata), WRITE was refused, the slot files kept their hashes, and switching back
restored the active layout. Native WebView2 was not exercised.
Existing spatial, multiselect and RULES browser checks and resource selftest pass.
The previous Python UI-boot HTTP 503 disappears with localhost excluded from the
proxy (`NO_PROXY=localhost,127.0.0.1`). These results establish synthetic regression
coverage only, not physical-console compatibility.

Latest validation (2026-11-09): 360 Python tests passed, 3 skipped; all four
browser scripts and `python app.py --selftest` passed. `test_rules_ui.cjs` has no
`CHROMIUM_PATH` hook and was run through a wrapper that points Playwright at Edge. Browser screenshot: `.cache/3dsbank-ui.png`
(local artifact, not committed). README makes no new compatibility claim.
