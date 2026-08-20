"""Zero-manual-copy flow: the dump script is published on every import and the
app resolves boot9/movable/container straight from the SD (3DSort_dump output)."""
from pathlib import Path

from app import Api, build_api, gm9_dump_script
from core.sdcard import NAND_SAVE_IDS, Save3ds, find_console
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
    txt = gm9_dump_script()
    assert "1:/private/movable.sed" in txt
    assert "0:/3DSort/movable.sed" in txt
    assert "M:/boot9.bin" in txt
    assert "0:/3DSort/boot9.bin" in txt
    assert "0:/3DSort/homemenu_save.bin" in txt
    assert "--hash" in txt  # container .sha anchor stays


def test_dump_script_resolves_console_itself():
    """The script asks GodMode9 for the console it is running on, so the same file
    works on any console and can never point at a stale id0."""
    txt = gm9_dump_script()
    assert "$[SYSID0]" in txt
    for region, save_id in NAND_SAVE_IDS.items():
        assert f'chk $[REGION] "{region}"' in txt
        assert save_id in txt


def test_dump_script_reports_unsupported_region():
    """A region outside the map (AUS, or an unreadable SecureInfo) must say so
    instead of silently building 'sysdata//00000000' and blaming the console."""
    txt = gm9_dump_script()
    assert "else\n" in txt
    assert "not supported" in txt


# ---- script publishing on import (kills the chicken-and-egg) ----------------

def test_import_publishes_dump_script_mock():
    api = build_api(mock=True)
    api.get_state()  # triggers import_sd
    script = Path(api.sd_root) / "gm9" / "scripts" / "3DSort_dump.gm9"
    assert script.exists()
    txt = script.read_text(encoding="ascii")
    assert "movable.sed" in txt and "boot9.bin" in txt
    assert "if not find 0:/3DSort NULL" in txt
    assert "mkdir 0:/3DSort" in txt


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


# ---- multi-console cards: the movable picks the id0 -------------------------

def test_import_picks_id0_matching_the_movable(tmp_path):
    """Real bug: a card carrying a leftover id0 from an older console state made
    import pick the dead folder, and the generated dump script pointed GodMode9 at
    a NAND path that does not exist."""
    api, _, sd = real_api(tmp_path, id0="0" * 32,  # leftover folder, sorts first
                          **{"3DSort/boot9.bin": b"9", "3DSort/movable.sed": MOVABLE})
    (sd / "Nintendo 3DS" / ID0 / ("b" * 32) / "extdata" / "00000000" /
     "0000008f").mkdir(parents=True)  # the live folder for this movable
    api.console = None
    try:
        api.import_sd()  # stops later at the missing save3ds binary; irrelevant here
    except FileNotFoundError:
        pass
    assert api.console.id0 == ID0
    script = (sd / "gm9" / "scripts" / "3DSort_dump.gm9").read_text(encoding="ascii")
    assert "0" * 32 not in script  # dead folder never reaches GodMode9


def test_import_reports_movable_without_folder(tmp_path):
    """The key may be fresh and the console simply new to this card, so the message
    offers booting the HOME menu as well as re-dumping the key."""
    api, _, _ = real_api(tmp_path, id0="a" * 32,
                         **{"3DSort/boot9.bin": b"9", "3DSort/movable.sed": MOVABLE})
    api.console = None
    err = api.import_sd()["error"]
    assert "boot the HOME menu once" in err and "3DSort_dump" in err


def test_mock_ignores_key_resolution():
    api = build_api(mock=True)
    api.console = None
    assert api._resolve_keys() is None  # FakeSave3ds uses no keys
