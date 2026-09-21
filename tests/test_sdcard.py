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


ALL_REGIONS = {"JPN", "USA", "EUR", "CHN", "KOR", "TWN"}


def test_home_extdata_ids_cover_regions():
    assert set(HOME_EXTDATA_IDS.values()) == ALL_REGIONS


def test_every_extdata_id_has_a_system_save_id():
    """The GM9 dump script reads the region off the console and looks the save id
    up here: an extdata id without its NAND counterpart would send GodMode9 to
    sysdata//00000000."""
    assert set(NAND_SAVE_IDS) == ALL_REGIONS
    for eid, region in HOME_EXTDATA_IDS.items():
        # same region number, 0002 prefix (holds on JPN/USA/EUR, all hardware-checked)
        assert NAND_SAVE_IDS[region] == "0002" + eid[4:], region


def test_find_console_accepts_an_uppercase_extdata_folder(tmp_path):
    """3dbrew and the hacks guide spell these ids in uppercase. Only 8f has a
    letter among the regions we had, so a case-sensitive lookup went unnoticed
    until CHN/KOR/TWN (a1/a9/b1) arrived."""
    c = find_console(make_sd(tmp_path, extdata_id="000000A1"))
    assert c.region == "CHN"
    assert c.extdata_id == "00000000000000a1"   # save3ds wants it lowercase


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


def test_nand_save_ids_hardware_checked_values():
    """Coverage lives in test_every_extdata_id_has_a_system_save_id. These three
    are the ones actually read off a console, so they are pinned literally."""
    assert NAND_SAVE_IDS["USA"] == "0002008f"
    assert NAND_SAVE_IDS["JPN"] == "00020082"
    assert NAND_SAVE_IDS["EUR"] == "00020098"


# ---- region change: two HOME menu extdata under one id0 --------------------

def add_extdata(sd, extdata_id, id0="a" * 32, id1="b" * 32, mtime=None):
    """Adds a second HOME menu extdata beside an existing one, optionally dated."""
    d = sd / "Nintendo 3DS" / id0 / id1 / "extdata" / "00000000" / extdata_id
    d.mkdir(parents=True, exist_ok=True)
    f = d / "00000001"
    f.write_bytes(b"x")
    if mtime is not None:
        import os
        os.utime(f, (mtime, mtime))
        os.utime(d, (mtime, mtime))
    return d


def test_find_consoles_ranks_newest_extdata_first(tmp_path):
    """After a CTRTransfer both regions sit under the SAME id0, so id0 cannot
    tell them apart. The dead one stops being written at the transfer; the live
    one is rewritten every time the HOME menu saves the layout."""
    from core.sdcard import find_consoles
    sd = make_sd(tmp_path, extdata_id="00000082")          # JPN, stale
    add_extdata(sd, "00000082", mtime=1_000_000)
    add_extdata(sd, "0000008f", mtime=2_000_000)           # USA, live
    regions = [c.region for c in find_consoles(sd, prefer_id0="a" * 32)]
    assert regions == ["USA", "JPN"]
    assert find_console(sd, prefer_id0="a" * 32).region == "USA"


def test_find_consoles_id0_beats_mtime(tmp_path):
    """A card used on two consoles: the movable-derived id0 still decides, even
    when the other console's extdata was written more recently."""
    from core.sdcard import find_consoles
    dead, live = "1" * 32, "4" * 32
    make_sd(tmp_path, id0=dead)
    add_extdata(tmp_path, "0000008f", id0=dead, mtime=9_000_000)
    make_sd(tmp_path, id0=live)
    add_extdata(tmp_path, "0000008f", id0=live, mtime=1_000_000)
    assert find_consoles(tmp_path, prefer_id0=live)[0].id0 == live


def test_find_consoles_single_region_unchanged(tmp_path):
    from core.sdcard import find_consoles
    cs = find_consoles(make_sd(tmp_path))
    assert len(cs) == 1 and cs[0].region == "USA"


def test_find_consoles_missing(tmp_path):
    from core.sdcard import find_consoles
    with pytest.raises(FileNotFoundError):
        find_consoles(tmp_path)


def test_extdata_mtime_of_missing_dir_is_zero(tmp_path):
    from core.sdcard import extdata_mtime
    assert extdata_mtime(tmp_path / "nope") == 0.0


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
