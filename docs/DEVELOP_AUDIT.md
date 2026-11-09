# Develop regression audit

## Baseline and scope

Baseline: e12933b5c2dd74ce5b265133f810450d50c297e6 (origin/develop), compared
with main a4aef85b14f9380594c5766eca004599a95c4646 and documentation reduction
3e0a756. Audit date: 2026-11-09. Windows, Python 3.13.17, Node 26.13.0.

Inspected sorting comparison, folder scope, position reassignment and compaction,
configuration persistence, exact-ID catalog generation, occupancy validation,
transaction preparation/recovery and existing automated coverage. Browser checks
use synthetic mock cards. No actual NAND injection was invoked.

## Confirmed findings

### Medium: accepted RULES discard retained the unsaved draft

Reproduction: select a saved preset, change its name, leave RULES and accept
"Leave unsaved preset changes?", then return. The unsaved name reappeared.
Root cause: tab navigation confirmed discard but never reset ruleDraft.
Fix: restore ruleSaved and clear the editor error on accepted navigation;
rejected navigation still retains edits. The browser regression failed before
this fix and passed after it. It also checks invalid-name feedback, unchanged
persisted names and Cancel recovery. No layout mutation is involved.


### Medium: RULES regression check depends on host disk usage

Reproduction: run the browser checks while other processes allocate disk space.
The full get_state comparison fails with different sd.free_blocks/used_bytes,
even though layout and staging are unchanged. Observed in the baseline run.
Root cause: comparing live storage telemetry as part of preset mutation checks.
Fix: exclude the sd telemetry object, preserving comparisons of all other state.
The existing editing/deletion assertions remain the regression checks and passed
again after the change. Screenshot output now goes to .cache/rules-ui.png rather
than overwriting the tracked documentation image.

### Low: contradictory spatial documentation

The opening behavior list said compaction kept NAND/cart/folders/badges fixed,
contradicting both the later paragraph and _compact_container. Replaced that
obsolete description with the actual Launcher/no-Launcher distinction.

No critical/high product defect was confirmed in the inspected paths. This is
not proof of absence or a release-readiness claim.

## Validation

- Initial pytest: 305 passed, 9 skipped, 1 failed in 39.61s. The boot HTTP check
  received 503 from urllib when using ambient proxy configuration.
- Full suite rerun with NO_PROXY=localhost,127.0.0.1: 306 passed, 9 skipped in 38.83s.
- Spatial and multiselect Playwright scripts: passed.
- Initial RULES script: failed on disk telemetry; after correction: passed.
- Source app.py --selftest: all six resource checks passed.
- Continuation full suite: 311 passed, 9 skipped in 42.38s; five new sorting
  cases cover independent directions/three-key priority and no-Launcher cells.
- Packaging tests after adding catalog assertions for all specs: 7 passed.
- Expanded RULES checks, spatial and multiselect: passed.
- Windows PyInstaller 6.22.3 build succeeded in .cache/audit-dist, including a
  rebuild after the UI fix; final frozen --selftest exited 0.
- Local Markdown link targets in README, CLAUDE and docs all exist. New links
  use document targets without anchors. git diff --check passed.
- No new feature or public API was introduced.

## Documentation recovery ledger

| Original sections | Classification and disposition |
|---|---|
| 1-2 architecture | Current essentials in ARCHITECTURE; discard obsolete deferred-RULES scope |
| 3 safety | Current essentials in WRITE_SAFETY; clarify hash guard limitation |
| 4 commands | Current commands stay in CLAUDE; discard old suite counts |
| 5 formats/crypto | Current implementation plus historical observations in SAVE_FORMATS/WRITE_SAFETY |
| 5 regional diagnosis | Already documented; REGION_CHANGE remains canonical |
| 6 backend | Replace superseded order-only snapshots with explicit spatial contract links |
| 7 native/UI pitfalls | Preserve engineering constraints in ARCHITECTURE and platform guides |
| 8 tests | Retain layered evidence distinction; never infer hardware success |
| 9 local environment | Discard personal drive assumptions; retain portable native pitfalls |
| 10 hardware/roadmap | Preserve reports in HARDWARE_VALIDATION; discard obsolete feature roadmap |
| 11 agent rules | Concise CLAUDE links and mandatory technical consultation |
| 12 badges/spatial | Existing BADGES_TESTING/SPATIAL_LAYOUT remain canonical |

Hardware reports are historical, not independently reproduced. Exact source
provenance is main CLAUDE at a4aef85; private dumps were neither copied nor
committed. See HARDWARE_VALIDATION for remaining regional/native uncertainties.

## Remaining work and limitations

No physical-console acceptance, clean-machine Windows smoke or native macOS/Linux
build was performed. Windows frozen selftest validates resources, not a rendered
native window. PyInstaller warned about missing pycparser lextab/yacctab; build
and resource selftest succeeded, but this does not prove every native path.
Python 3.10 was not installed/tested here. Nine pytest skips remain unavailable
integration/hardware-data cases; passing synthetic tests is not hardware evidence.

Documentation source checks matched SaveData/Launcher offsets, region constants,
id0 derivation, exact-position staging and write transaction order against code.
The macOS checklist incorrectly still said write/inject had never been tested;
it now attributes the later main CLAUDE report explicitly. Linux's historical
GLib mismatch was retained as an unresolved platform observation, not a new fix.

## Coverage reviewed

| Behavior | Evidence |
|---|---|
| Four built-ins, mixed SD/TWL, folder isolation | test_api_spatial exact-order parametrizations |
| Lexicographic priorities, independent directions, missing dates, ties | test_sort_presets, including five added cases |
| Preset atomic failure/recovery, restart, immutability | test_sort_presets persistence and malformed-file cases |
| Catalog conflicts, exact IDs, deterministic offline generation | test_sort_presets and tools/build_titledates.py |
| UI editing, navigation rejection/discard, invalid save, GRID, history | expanded test_rules_ui.cjs |
| Badges, composites, decorations, geometry, reserved cells | test_api_spatial, test_badges and spatial browser checks |
| Import, regions, stale dumps and injection lifecycle | test_api_region, test_import_consistency, test_api_launcher_edit |
| Round-trip, theme graft, backups, journal failure/recovery | test_savedata, test_launcher, test_store, test_api_spatial |
| Native bridge/boot constraints | test_ui_boot; native acceptance remains pending |

The audit focused on concrete interactions and existing invariants. It does not
claim exhaustive coverage of all OS/native engine errors or all configurations.
Additional console behavior must be validated before changing format assumptions.
