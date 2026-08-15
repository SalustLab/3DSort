# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build: single portable 3DSort.exe, no installer.

    pyinstaller 3DSort.spec
    dist\\3DSort.exe --selftest     # verifies the bundled resources

The data files keep their repo-relative layout, so Path(__file__).parent in
app.py and core/titledates.py resolves inside the bundle with no code change.
sandbox/ is never bundled: it holds the developer console's private keys.
"""

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('ui', 'ui'),                                       # index.html, app.js, fonts
        ('tools/save3ds/save3ds_fuse.exe', 'tools/save3ds'),
        ('core/titledates.json.gz', 'core'),
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    # the tkinter folder-picker fallback only runs in --serve dev mode
    excludes=['tkinter', 'pytest'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='3DSort',
    icon='ui/3dsort.ico',       # regenerate with tools/make_icon.py
    debug=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
