from pathlib import Path

import pytest

from core.sdcard import (find_console, HOME_EXTDATA_IDS, NAND_SAVE_IDS,
                         Save3ds, id0_from_movable)

SANDBOX = Path(__file__).parent.parent / "sandbox"


def make_sd(tmp_path, extdata_id="0000008f", id0="a" * 32, id1="b" * 32):
    d = tmp_path / "Nintendo 3DS" / id0 / id1 / "extdata" / "00000000" / extdata_id
    d.mkdir(parents=True)
    (d / "00000001").write_bytes(b"x")
    return tmp_path


def test_find_console_usa(tmp_path):
    c = find_console(make_sd(tmp_path))
    assert c.region == "USA"
    assert c.extdata_id == "000000000000008f"
    assert c.id0 == "a" * 32 and c.id1 == "b" * 32


def test_find_console_eur(tmp_path):
    c = find_console(make_sd(tmp_path, extdata_id="00000098"))
    assert c.region == "EUR"


def test_find_console_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        find_console(tmp_path)


def test_find_console_no_home_extdata(tmp_path):
    sd = make_sd(tmp_path, extdata_id="000002cd")  # so extdata de tema
    with pytest.raises(FileNotFoundError):
        find_console(sd)


def test_home_extdata_ids_cover_regions():
    assert set(HOME_EXTDATA_IDS.values()) == {"JPN", "USA", "EUR"}


@pytest.mark.skipif(not (SANDBOX / "keys" / "essential.exefs").exists(),
                    reason="fixture real ausente")
def test_extract_movable_from_real_essential(tmp_path):
    out = tmp_path / "movable.sed"
    Save3ds.extract_movable(SANDBOX / "keys" / "essential.exefs", out)
    assert out.stat().st_size == 320


def test_save3ds_requires_resources(tmp_path):
    s = Save3ds(exe=tmp_path / "nope.exe", boot9=tmp_path / "nope1", movable=tmp_path / "nope2")
    with pytest.raises(FileNotFoundError):
        s.extract("000000000000008f", tmp_path / "sd", tmp_path / "out")


# ---- canal NAND (v1.1) ----------------------------------------------------

def test_id0_from_movable_known_vector():
    # KeyY = 16 bytes zero -> id0 pre-computado (SHA-256[:16] como 4 u32 LE em hex)
    movable = bytes(0x110) + bytes(16) + bytes(0x20)
    assert id0_from_movable(movable) == "ff084737d59d71f775c89e9728d26cd5"


@pytest.mark.skipif(not (SANDBOX / "keys" / "movable.sed").exists(),
                    reason="fixture real ausente")
def test_id0_from_real_movable_matches_console():
    movable = (SANDBOX / "keys" / "movable.sed").read_bytes()
    assert id0_from_movable(movable) == "REDACTED-ID0"


def test_nand_save_ids_cover_regions():
    assert set(NAND_SAVE_IDS) == {"JPN", "USA", "EUR"}
    assert NAND_SAVE_IDS["USA"] == "0002008f"


def test_build_nand_tree_layout(tmp_path):
    movable = tmp_path / "movable.sed"
    movable.write_bytes(bytes(0x110) + bytes(16) + bytes(0x20))
    container = tmp_path / "homemenu_save.bin"
    container.write_bytes(b"DISA-fake")
    s = Save3ds(exe=tmp_path / "x.exe", boot9=tmp_path / "b9", movable=movable)
    nand = s.build_nand_tree(tmp_path / "work", container, "0002008f")
    assert (nand / "private" / "movable.sed").read_bytes() == movable.read_bytes()
    save = nand / "data" / "ff084737d59d71f775c89e9728d26cd5" / "sysdata" / "0002008f" / "00000000"
    assert save.read_bytes() == b"DISA-fake"
