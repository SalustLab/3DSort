from pathlib import Path

import pytest

from core.sdcard import find_console, HOME_EXTDATA_IDS, Save3ds

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
