"""The real-SD guard (CLAUDE.md section 3.1), in a module of its own.

It used to live in test_integration.py, whose pytestmark skips the WHOLE module
when sandbox/ and the real keys are absent - which is every checkout except the
maintainer's. The guard needs none of that: a drive letter and hashlib. Sitting
behind that skip, it silently protected nothing on any other machine.
"""
import hashlib
from pathlib import Path

import pytest


def test_real_sd_untouched_guard():
    """No test alters the real SD: the extdata hashes are compared at session
    start/end. Hashed per id0 AND extdata id, so swapping in another card (or a
    card carrying leftover id0 folders) reports 'unknown', never a false
    'modified' - and every known folder still gets checked.

    A region-changed card carries two HOME menu extdata under one id0, and the
    dead one is exactly what this branch teaches the app to read, so both are
    watched independently.

    Known limitation: a legitimate write from the APP also trips this (the guard
    cannot tell who wrote). When it fires, check the extdata timestamps against
    the backup history before assuming a test misbehaved, then re-register the
    baseline by deleting tests/.real_sd_hash."""
    from core.sdcard import HOME_EXTDATA_IDS, find_sd_drive
    drive = find_sd_drive()          # whatever letter Windows gave the card today
    if drive is None:
        pytest.skip("real SD not mounted")
    real = Path(drive) / "Nintendo 3DS"
    marker = Path(__file__).parent / ".real_sd_hash"
    known = dict(line.split(None, 1) for line in
                 marker.read_text().split("\n") if line.strip()) if marker.exists() else {}
    seen = {}
    exts = sorted(p for eid in HOME_EXTDATA_IDS
                  for p in real.glob(f"*/*/extdata/00000000/{eid}"))
    for ext in exts:
        h = hashlib.sha256()
        for p in sorted(ext.rglob("*")):
            if p.is_file():
                h.update(p.name.encode())
                h.update(p.read_bytes())
        key = "/".join((ext.relative_to(real).parts[0], ext.name))
        seen[key] = h.hexdigest()
        if key in known:
            assert known[key] == seen[key], f"REAL SD WAS MODIFIED by some test! ({key})"
    marker.write_text("\n".join(f"{k} {v}" for k, v in sorted({**known, **seen}.items())))


def test_the_guard_is_not_behind_a_module_skip():
    """Regression: the guard protected nothing on any checkout without sandbox/,
    because the module it lived in carried a skipif for the sandbox it does not
    need. Nothing may gate this module."""
    import sys
    assert not hasattr(sys.modules[__name__], "pytestmark")
