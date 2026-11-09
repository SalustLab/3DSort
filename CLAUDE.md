# Repository Guidelines

## Project Structure & Module Organization

3DSort is a Python 3.10+ desktop application for editing Nintendo 3DS HOME menu layouts. `app.py` provides the application entry point and native/browser transports. `core/` contains layout editing, binary save formats, SD discovery, backups, icons, and badge handling. `ui/` holds plain JavaScript, HTML, CSS, fonts, and the application icon. Python tests live in `tests/`; browser checks and maintenance scripts live in `tools/`. Platform notes and screenshots are in `docs/`. Root-level `3DSort*.spec` files configure PyInstaller packaging.

## Build, Test, and Development Commands

Run commands from the repository root:

- `pip install -r requirements-dev.txt`: install runtime, pytest, and packaging dependencies; preferably use a virtual environment.
- `python app.py`: launch the native application with real SD card discovery.
- `python app.py --serve --mock --mock-badges`: develop in a browser using synthetic console and badge data.
- `python -m pytest tests -q`: run the Python suite; tests requiring unavailable console data skip automatically.
- `node tools/test_spatial_ui.cjs` and `node tools/test_multiselect_ui.cjs`: run headless browser checks; require Playwright and Chromium.
- `node tools/test_themes_ui.cjs`: check read-only theme browsing with generated packages.
- `pyinstaller 3DSort.spec`: build the Windows executable; validate with `dist\3DSort.exe --selftest`. Use the platform-specific specs and documentation for macOS/Linux.

## Coding Style & Naming Conventions

Follow surrounding code: four-space Python indentation, `snake_case` functions/modules, `PascalCase` classes, and uppercase constants. JavaScript uses two-space indentation, `camelCase` identifiers, and semicolons. Keep frontend changes in the existing plain JavaScript structure. No repository-wide formatter or linter configuration is present; keep changes focused and consistent with nearby code.

## Testing Guidelines

Use pytest files named `tests/test_*.py` with `test_*` functions. Add regression coverage for changed binary formats, API behavior, and layout operations; exercise UI interactions with the browser scripts when relevant. No numeric coverage threshold is configured. Use synthetic data or temporary directories. Preserve the real-SD guard and never let tests write to a real card.

## Commit & Pull Request Guidelines

Recent commits use concise, imperative subjects, sometimes prefixed with a component, such as `README: trim to the essentials`. Follow that pattern. Pull requests should explain the behavior change, include relevant test results, link related issues, and provide screenshots for visible UI changes. Identify affected platforms for packaging changes.

## Console Data Safety

Never commit console keys or personal dumps, including `boot9.bin`, `*.sed`, `essential.exefs`, `Launcher.dat`, or `sandbox/`. Preserve unknown binary bytes, backup-before-write behavior, and write validation when changing save handling.
## Technical references

Theme discovery and preview contracts: [THEMES](docs/THEMES.md). Theme browsing
must remain read-only and preserve `SaveData.graft_tail()` unchanged.

Before modifying binary formats, read [SAVE_FORMATS](docs/SAVE_FORMATS.md). Before SD writes, recovery or NAND injection, read [WRITE_SAFETY](docs/WRITE_SAFETY.md). Before badge changes, read [BADGES_TESTING](docs/BADGES_TESTING.md) and [SPATIAL_LAYOUT](docs/SPATIAL_LAYOUT.md). See [ARCHITECTURE](docs/ARCHITECTURE.md), [SORT_PRESETS](docs/SORT_PRESETS.md), and [HARDWARE_VALIDATION](docs/HARDWARE_VALIDATION.md). Preserve both positional API transports. Documentation and code remain English-only.
