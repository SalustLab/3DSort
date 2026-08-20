# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller app bundle for Apple Silicon macOS.

Build with:
    python -m PyInstaller --clean --noconfirm 3DSort.macos.spec

The native save3ds helper is built separately by
tools/build_save3ds_macos.sh. Console keys and SD-card data are never bundled.
"""

from pathlib import Path


# PyInstaller injects SPECPATH while executing a spec file.
ROOT = Path(SPECPATH).resolve()
SAVE3DS = ROOT / "tools" / "save3ds" / "save3ds_fuse"


a = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT)],
    binaries=[(str(SAVE3DS), "tools/save3ds")],
    datas=[
        (str(ROOT / "ui"), "ui"),
        (str(ROOT / "core" / "titledates.json.gz"), "core"),
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="3DSort",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="3DSort",
)

app = BUNDLE(
    coll,
    name="3DSort.app",
    bundle_identifier="com.salustlab.3dsort",
    info_plist={
        "CFBundleDisplayName": "3DSort",
        "CFBundleName": "3DSort",
        "LSMinimumSystemVersion": "14.0",
        "NSHighResolutionCapable": True,
    },
)
