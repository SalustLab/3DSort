"""Boot channel selection and setup-screen structure in ui/app.js.

Two regressions are guarded here, both found the hard way:

1. The native-window blank screen: app.js runs before pywebview injects its
   bridge, and pywebview's own HTTP server has no /api route (it answers 405),
   so falling through to fetch renders nothing at all.
2. Instruction text naming a button that is not on screen. The wizard used to
   render both the setup flow and the reference guide from one function with
   `review ? a : b` in the labels, so prose saying "press Verify below" sat
   under a button reading DONE. Button labels are consts now, and the two
   purposes are separate functions.

These are source-text assertions. They cannot prove the UI renders (only a
screenshot does that, see CLAUDE.md section 10), but they do pin the structural
choices that stop the bug class from coming back.
"""
import re
import threading
import urllib.request
from pathlib import Path

from app import build_api, serve

ROOT = Path(__file__).parent.parent
APP_JS = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")


def region(start, end):
    return APP_JS.split(start)[1].split(end)[0]


# ---- boot channel ----------------------------------------------------------

def test_boot_waits_for_bridge_unless_serve_mode():
    boot = region("async function boot()", "}\nboot();")
    guard = re.search(r"if \((.*?)\) \{\s*window\.addEventListener\(\"pywebviewready\"",
                      boot, re.S)
    assert guard, "boot() must wait for pywebviewready"
    cond = guard.group(1)
    # the flag decides; window.pywebview alone is undefined too early to trust
    assert "SERVE_MODE" in cond
    assert "pywebview.api" in cond


def test_serve_injects_the_flag_into_index_html():
    api = build_api(mock=True)
    port = 8399
    threading.Thread(target=serve, args=(api, port), daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    for path in ("/", "/index.html"):
        html = urllib.request.urlopen(base + path, timeout=10).read().decode("utf-8")
        assert "window.SERVE_MODE=true" in html, path
        assert "<title>3DSort</title>" in html          # still the real page
    js = urllib.request.urlopen(base + "/app.js", timeout=10).read()
    assert b"async function boot()" in js


def test_native_html_has_no_serve_flag():
    """The file on disk stays clean: the flag is added per response, so the
    native window (which loads the file directly) never sees it."""
    assert "SERVE_MODE" not in (ROOT / "ui" / "index.html").read_text(encoding="utf-8")


# ---- setup screens: doing vs reading ---------------------------------------

def test_wizard_and_guide_are_separate_functions():
    """One function serving both purposes is what produced the mismatched
    labels. The guide must not take the wizard's stage, and the wizard must not
    take a review flag."""
    assert "async function renderWizard(stage, detail)" in APP_JS
    assert "function renderGuide(page)" in APP_JS
    wizard = region("async function renderWizard(stage, detail)", "\nasync function wizAdvance")
    assert "review" not in wizard, "no mode flag inside the wizard"
    assert "P.wizStep" not in APP_JS, "the review cursor is gone"


def test_wizard_text_never_hardcodes_a_button_label():
    """Prose that names a button must interpolate the same const the button
    renders, so the two cannot drift."""
    wizard = region("async function renderWizard(stage, detail)", "\nasync function wizAdvance")
    assert "press Verify below" not in wizard
    assert "press ${esc(BTN_WIZ_VERIFY)} below" in wizard
    assert ">${esc(BTN_WIZ_VERIFY)}<" in wizard      # the button itself


def test_every_wizard_stage_has_a_screen():
    wizard = region("async function renderWizard(stage, detail)", "\nasync function wizAdvance")
    for stage in ("no_keys", "stale_keys", "error"):
        assert stage in wizard, f"{stage} needs its own branch"
    # no_sd is the final else, so assert on what that screen must offer
    assert "wizRescan" in wizard and "data-wizdrive" in wizard


def test_wizard_shows_the_backend_detail():
    """get_setup_state returns a precise message; dropping it left the user
    with a generic screen and no idea what failed."""
    wizard = region("async function renderWizard(stage, detail)", "\nasync function wizAdvance")
    assert wizard.count("wizDetail(detail)") >= 3, "every screen surfaces detail"


def test_picking_a_drive_uses_the_returned_state():
    """set_sd_root returns the full state (app.py). Discarding it and asking
    again re-ran the whole SD extraction, and its error branch stranded the user
    on the welcome screen instead of moving to the screen that explains the fix."""
    wizard = region("async function renderWizard(stage, detail)", "\nasync function wizAdvance")
    pick = region('document.querySelectorAll("[data-wizdrive]")', "$(\"wizRescan\")")
    assert "S = res" in pick, "use the state set_sd_root already returned"
    assert "wizAdvance()" in pick, "on failure move to the right screen"
    assert "wizError" not in wizard, "no dead-end error box"


def test_guide_has_no_action_buttons():
    guide = region("function renderGuide(page)", "\n// ---- the wizard")
    for action in ("set_sd_root", "get_setup_state", "import_sd", "BTN_WIZ_VERIFY"):
        assert action not in guide, f"the guide must not {action}"
    for nav in ("guidePrev", "guideNext", "guideClose"):
        assert nav in guide


def test_guide_and_instructions_tab_share_one_source():
    assert "const INSTRUCTION_PAGES = [" in APP_JS
    guide = region("function renderGuide(page)", "\n// ---- the wizard")
    assert "INSTRUCTION_PAGES[" in guide
    tab = region("function instructionsScreen()", "\nfunction settingsScreen")
    assert "INSTRUCTION_PAGES.map" in tab


def test_instruction_text_names_buttons_by_const():
    """"Import from SD" was never the button's label; it reads "Import layout
    from SD"."""
    assert 'const BTN_IMPORT = "Import layout from SD"' in APP_JS
    pages = region("const INSTRUCTION_PAGES = [", "];")
    assert "press Import from SD" not in pages
    assert "${BTN_IMPORT}" in pages
