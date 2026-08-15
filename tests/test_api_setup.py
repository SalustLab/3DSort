"""get_setup_state: the stage machine behind the first-run wizard."""
from pathlib import Path

import app as app_mod
from app import build_api

from test_api_keys import ID0, MOVABLE, real_api

BOOT9 = bytes(0x10000)


def test_setup_ready_mock():
    api = build_api(mock=True)
    assert api.get_setup_state() == {"stage": "ready", "detail": None}


def test_setup_ready_short_circuit():
    api = build_api(mock=True)
    api.get_state()                      # staging built
    assert api.get_setup_state()["stage"] == "ready"


def test_setup_no_sd(tmp_path, monkeypatch):
    api, _, _ = real_api(tmp_path)
    api.sd_root = tmp_path / "empty"     # no 'Nintendo 3DS' inside
    api.sd_root.mkdir()
    monkeypatch.setattr(app_mod, "find_sd_drive", lambda: None)
    r = api.get_setup_state()
    assert r["stage"] == "no_sd" and "not found" in r["detail"]


def test_setup_no_keys(tmp_path):
    api, _, sd = real_api(tmp_path)
    r = api.get_setup_state()
    assert r["stage"] == "no_keys" and "3DSort_dump" in r["detail"]
    # the wizard tells the user to run a script that import_sd already published
    assert (sd / "gm9" / "scripts" / "3DSort_dump.gm9").exists()


def test_setup_stale_keys(tmp_path):
    stale = bytes(0x110) + bytes(range(16)) + bytes(0x20)  # KeyY != zeros -> other id0
    api, _, _ = real_api(tmp_path, **{"3DSort/boot9.bin": BOOT9,
                                      "3DSort/movable.sed": stale})
    r = api.get_setup_state()
    assert r["stage"] == "stale_keys" and "does not match" in r["detail"]


def test_setup_keys_ok_reaches_extract(tmp_path):
    """Matching movable gets past key resolution: the failure that remains is the
    (fake) save3ds binary, which is an 'error' stage, not a key/SD stage."""
    api, _, _ = real_api(tmp_path, **{"3DSort/boot9.bin": BOOT9,
                                      "3DSort/movable.sed": MOVABLE})
    assert api.get_setup_state()["stage"] == "error"
