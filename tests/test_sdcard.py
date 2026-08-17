import sys
from pathlib import Path

import pytest

import core.sdcard
from core.sdcard import (default_sd_candidates, find_console, HOME_EXTDATA_IDS,
                        NAND_SAVE_IDS, Save3ds, id0_from_movable, list_3ds_roots)

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


def test_find_console_prefers_matching_id0(tmp_path):
    """A card used on more than one console (or console state) keeps several id0
    folders. Without a hint the first one wins, which may be a dead leftover, so
    the caller passes the id0 derived from the movable it holds."""
    dead, live = "1" * 32, "4" * 32
    make_sd(tmp_path, id0=dead)
    make_sd(tmp_path, id0=live)
    assert find_console(tmp_path, prefer_id0=live).id0 == live
    assert find_console(tmp_path, prefer_id0=dead).id0 == dead


def test_find_console_ignores_unknown_prefer_id0(tmp_path):
    """An id0 with no folder on the card falls back to the plain first match:
    reporting the mismatch is the caller's job (it knows where the key came from)."""
    make_sd(tmp_path, id0="a" * 32)
    assert find_console(tmp_path, prefer_id0="c" * 32).id0 == "a" * 32


def test_find_console_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        find_console(tmp_path)


def test_find_console_no_home_extdata(tmp_path):
    sd = make_sd(tmp_path, extdata_id="000002cd")  # theme extdata only
    with pytest.raises(FileNotFoundError):
        find_console(sd)


def test_list_3ds_roots_filters_candidates(tmp_path):
    a = tmp_path / "a"
    (a / "Nintendo 3DS").mkdir(parents=True)
    b = tmp_path / "b"
    b.mkdir()
    roots = list_3ds_roots([a, b, tmp_path / "missing"])
    assert roots == [a]


def test_default_candidates_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    roots = default_sd_candidates()
    assert len(roots) == 13
    assert roots[0] == Path("D:/") and roots[-1] == Path("P:/")


def test_default_candidates_linux(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    base = tmp_path / "media_user"
    (base / "sd1").mkdir(parents=True)
    (base / "sd2").mkdir()
    (base / "not-a-dir").write_bytes(b"x")
    roots = default_sd_candidates([base, tmp_path / "missing"])
    assert roots == [base / "sd1", base / "sd2"]  # file skipped, missing base ignored


def test_list_3ds_roots_uses_default_candidates(tmp_path, monkeypatch):
    mount = tmp_path / "mount"
    (mount / "Nintendo 3DS").mkdir(parents=True)
    monkeypatch.setattr(core.sdcard, "default_sd_candidates",
                        lambda: [mount, tmp_path / "other"])
    assert list_3ds_roots() == [mount]


def test_home_extdata_ids_cover_regions():
    assert set(HOME_EXTDATA_IDS.values()) == {"JPN", "USA", "EUR"}


@pytest.mark.skipif(not (SANDBOX / "keys" / "essential.exefs").exists(),
                    reason="real fixture missing")
def test_extract_movable_from_real_essential(tmp_path):
    out = tmp_path / "movable.sed"
    Save3ds.extract_movable(SANDBOX / "keys" / "essential.exefs", out)
    assert out.stat().st_size == 320


def test_save3ds_requires_resources(tmp_path):
    s = Save3ds(exe=tmp_path / "nope.exe", boot9=tmp_path / "nope1", movable=tmp_path / "nope2")
    with pytest.raises(FileNotFoundError):
        s.extract("000000000000008f", tmp_path / "sd", tmp_path / "out")


# ---- NAND channel (v1.1) ---------------------------------------------------

def test_id0_from_movable_known_vector():
    # KeyY = 16 zero bytes -> precomputed id0 (SHA-256[:16] as 4 u32 LE in hex)
    movable = bytes(0x110) + bytes(16) + bytes(0x20)
    assert id0_from_movable(movable) == "ff084737d59d71f775c89e9728d26cd5"


@pytest.mark.skipif(not (SANDBOX / "keys" / "movable.sed").exists(),
                    reason="real fixture missing")
def test_id0_from_real_movable_matches_console():
    """The derived id0 must name the actual folder on the card. The expected
    value is read from the sandbox rather than hardcoded: it identifies the
    developer's console and this repo is public."""
    movable = (SANDBOX / "keys" / "movable.sed").read_bytes()
    id0_dirs = [p.name for p in (SANDBOX / "sd" / "Nintendo 3DS").iterdir()
                if p.is_dir() and len(p.name) == 32]
    assert id0_from_movable(movable) in id0_dirs


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
