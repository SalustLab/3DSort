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
not proof of absence; the complete requested audit is not yet finished.

## Validation

- Initial pytest: 305 passed, 9 skipped, 1 failed in 39.61s. The boot HTTP check
  received 503 from urllib when using ambient proxy configuration.
- Full suite rerun with NO_PROXY=localhost,127.0.0.1: 306 passed, 9 skipped in 38.83s.
- Spatial and multiselect Playwright scripts: passed.
- Initial RULES script: failed on disk telemetry; after correction: passed.
- Source app.py --selftest: all six resource checks passed.
- No new product behavior or public API was introduced.

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

The full section-by-section source verification, exhaustive UI unsaved/error
paths, additional targeted sorting tests, link/anchor sweep and packaging builds
remain outstanding. No packaging or physical-console acceptance was performed.
Automated successes do not establish release readiness. Future work must complete
these items before claiming the original acceptance criteria are met.
