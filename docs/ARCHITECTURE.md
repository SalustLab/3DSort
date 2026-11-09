# Architecture and engineering constraints

The shared `Api` in `app.py` exposes positional calls through pywebview and
browser `POST /api/<method>` with `{"args": [...]}`. Preserve both transports
and decorator signatures visible to pywebview. Python owns parsing and writes;
the plain JavaScript UI renders backend state. Hosted/browser-only designs were
historically rejected because SD access and console crypto require local tools.

SaveData owns SD title positions/membership; Launcher owns NAND titles, folder
definitions and Game Card position. Cache/CacheD supply names and icons.
`core/layout.py` validates occupancy; `core/layout_api.py` stages edits.
Snapshots include explicit game positions and raw save bytes; order is derived.
See [spatial contracts](SPATIAL_LAYOUT.md) and [sorting](SORT_PRESETS.md).

Positions are container-local, column-major: column = position // rows,
row = position % rows. HOME has 360 cells, folders 60. Unknown reservations
must survive. SD-only edits need no NAND injection unless NAND-owned state moves.
Undo/redo must include every affected entity, including badge sources.

Native pitfalls retained from main CLAUDE.md sections 7 and 12:
- Native boot waits for pywebviewready; only serve mode uses HTTP fallback.
- Windows missing WebView2 can fall back to MSHTML: keep the ES5 boot guard.
- GTK may have no localStorage: keep guarded preference access.
- Every dragstart must populate dataTransfer for WebKitGTK.
- Draggable tile images need pointer-events:none and -webkit-user-drag:none;
  headless Chromium does not reproduce the WebView2 native-image drag failure.
- Preserve pane scroll before FLIP calculations when replacing rendered HTML.

Platform procedures: [Linux](LINUX_TESTING.md), [macOS](MACOS_TESTING.md).
Do not accept contributor-built native helpers into the repository: helpers
receive console keys. Use the pinned source build and existing release workflows.
