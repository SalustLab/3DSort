"""Zero-manual-copy flow: the dump script is published on every import and the
app resolves boot9/movable/container straight from the SD (3DSort_dump output)."""
from pathlib import Path

from app import Api, build_api, gm9_dump_script
from core.sdcard import Save3ds, find_console
from core.store import Backups

# synthetic movable with zero KeyY -> known id0 (same vector as test_sdcard)
MOVABLE = bytes(0x110) + bytes(16) + bytes(0x20)
ID0 = "ff084737d59d71f775c89e9728d26cd5"


def real_api(tmp_path, id0=ID0, **key_files):
    """Api with a REAL Save3ds (nonexistent fallback paths) + synthetic SD."""
    sd = tmp_path / "sd"
    (sd / "Nintendo 3DS" / id0 / ("b" * 32) / "extdata" / "00000000" /
     "0000008f").mkdir(parents=True)
    for rel, data in key_files.items():
        p = sd / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    s3 = Save3ds(tmp_path / "nope.exe", tmp_path / "no_boot9", tmp_path / "no_movable")
    api = Api(s3, sd, tmp_path / "work", Backups(tmp_path / "bk"))
    api.console = find_console(sd)
    return api, s3, sd


# ---- dump script contents ----------------------------------------------------

def test_dump_script_dumps_all_needed_files():
    txt = gm9_dump_script("a" * 32, "0002008f")
    assert "1:/private/movable.sed" in txt
    assert "0:/3DSort/movable.sed" in txt
    assert "M:/boot9.bin" in txt
    assert "0:/3DSort/boot9.bin" in txt
    assert "0:/3DSort/homemenu_save.bin" in txt
    assert "--hash" in txt  # container .sha anchor stays


# ---- script publishing on import (kills the chicken-and-egg) ----------------

def test_import_publishes_dump_script_mock():
    api = build_api(mock=True)
    api.get_state()  # triggers import_sd
    script = Path(api.sd_root) / "gm9" / "scripts" / "3DSort_dump.gm9"
    assert script.exists()
    txt = script.read_text(encoding="ascii")
    assert "movable.sed" in txt and "boot9.bin" in txt


def test_import_publishes_dump_script_even_without_keys(tmp_path):
    api, _, sd = real_api(tmp_path)
    r = api.import_sd()
    assert "3DSort_dump" in r["error"]  # friendly error, not a raw FileNotFoundError
    assert (sd / "gm9" / "scripts" / "3DSort_dump.gm9").exists()


# ---- key resolution via SD -----------------------------------------------------

def test_keys_resolved_from_sd_3dsort(tmp_path):
    api, s3, sd = real_api(tmp_path, **{"3DSort/boot9.bin": b"9",
                                        "3DSort/movable.sed": MOVABLE})
    assert api._resolve_keys() is None
    assert s3.boot9 == sd / "3DSort" / "boot9.bin"
    assert s3.movable == sd / "3DSort" / "movable.sed"


def test_keys_resolved_from_gm9_out_fallback(tmp_path):
    api, s3, sd = real_api(tmp_path, **{"gm9/out/boot9.bin": b"9",
                                        "gm9/out/movable.sed": MOVABLE})
    assert api._resolve_keys() is None
    assert s3.movable == sd / "gm9" / "out" / "movable.sed"


def test_sd_3dsort_beats_gm9_out(tmp_path):
    api, s3, sd = real_api(tmp_path, **{"3DSort/movable.sed": MOVABLE,
                                        "gm9/out/movable.sed": b"x" * 0x140,
                                        "3DSort/boot9.bin": b"9"})
    assert api._resolve_keys() is None
    assert s3.movable == sd / "3DSort" / "movable.sed"


def test_movable_from_other_console_state_rejected(tmp_path):
    # folder id0 does not match the id0 derived from the movable -> old-key trap
    api, _, _ = real_api(tmp_path, id0="a" * 32,
                         **{"3DSort/boot9.bin": b"9", "3DSort/movable.sed": MOVABLE})
    err = api._resolve_keys()
    assert err is not None and "3DSort_dump" in err


def test_mock_ignores_key_resolution():
    api = build_api(mock=True)
    api.console = None
    assert api._resolve_keys() is None  # FakeSave3ds uses no keys
