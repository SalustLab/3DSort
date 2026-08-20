"""The resources the frozen exe needs are present and loadable."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_selftest_exits_zero():
    r = subprocess.run([sys.executable, str(ROOT / "app.py"), "--selftest"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_spec_lists_every_bundled_resource():
    spec = (ROOT / "3DSort.spec").read_text(encoding="utf-8")
    for entry in ("('ui', 'ui')", "save3ds_fuse.exe", "titledates.json.gz"):
        assert entry in spec
    assert "sandbox" not in spec.split('"""')[2]  # never bundle the console keys


def test_icon_is_wired_into_the_build():
    ico = ROOT / "ui" / "3dsort.ico"
    assert ico.is_file() and ico.stat().st_size > 1000
    assert ico.read_bytes()[:4] == b"\x00\x00\x01\x00"   # ICO magic
    assert "icon='ui/3dsort.ico'" in (ROOT / "3DSort.spec").read_text(encoding="utf-8")


def test_fonts_are_vendored():
    fonts = ROOT / "ui" / "fonts"
    assert (fonts / "nunito-var.woff2").is_file()
    assert (fonts / "dotgothic16-400.woff2").is_file()
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    assert "fonts.googleapis.com" not in html  # offline-correct typography


def test_macos_spec_uses_native_helper_and_app_bundle():
    spec = (ROOT / "3DSort.macos.spec").read_text(encoding="utf-8")
    assert '"tools" / "save3ds" / "save3ds_fuse"' in spec
    assert 'name="3DSort.app"' in spec
    assert 'bundle_identifier="com.salustlab.3dsort"' in spec
    assert "BUNDLE(" in spec
    assert "sandbox" not in spec  # never bundle the console keys


def test_linux_spec_uses_native_helper_and_onedir():
    spec = (ROOT / "3DSort.linux.spec").read_text(encoding="utf-8")
    assert '"tools" / "save3ds" / "save3ds_fuse"' in spec
    assert 'name="3DSort"' in spec
    assert "COLLECT(" in spec
    assert "BUNDLE(" not in spec  # onedir tarball, not an app bundle
    assert "sandbox" not in spec  # never bundle the console keys
