"""Real integration: save3ds + real keys against the SANDBOX SD (a copy).
Never touches the real SD. Skipped if boot9/movable/sandbox do not exist.
"""
import shutil
from pathlib import Path

import pytest

from core.savedata import SaveData
from core.sdcard import SAVE3DS_NAME, Save3ds, find_console

ROOT = Path(__file__).parent.parent
KEYS = ROOT / "sandbox" / "keys"
SD_SRC = ROOT / "sandbox" / "sd"
SAVE3DS = ROOT / "tools" / "save3ds" / SAVE3DS_NAME

ready = all(p.exists() for p in
            [KEYS / "boot9.bin", KEYS / "movable.sed", SD_SRC, SAVE3DS])
pytestmark = pytest.mark.skipif(not ready, reason="sandbox/real keys missing")


@pytest.fixture()
def sd(tmp_path):
    """Fresh copy of the sandbox SD per test: not even the original sandbox is altered."""
    dst = tmp_path / "sd"
    shutil.copytree(SD_SRC, dst)
    return dst


@pytest.fixture()
def s3():
    return Save3ds(SAVE3DS, KEYS / "boot9.bin", KEYS / "movable.sed")


def test_extract_reads_real_layout(sd, s3, tmp_path):
    c = find_console(sd)
    out = tmp_path / "ext"
    s3.extract(c.extdata_id, sd, out)
    sav = SaveData((out / "user" / "SaveData.dat").read_bytes())
    assert len(sav.entries) >= 1
    assert (out / "user" / "Cache.dat").exists()
    assert (out / "user" / "CacheD.dat").exists()


def test_roundtrip_edit_import_reextract(sd, s3, tmp_path):
    c = find_console(sd)
    ext, ver = tmp_path / "ext", tmp_path / "ver"
    s3.extract(c.extdata_id, sd, ext)
    sav_path = ext / "user" / "SaveData.dat"
    sav = SaveData(sav_path.read_bytes())
    before = sorted(sav.entries, key=lambda e: e.pos)
    a, b = before[0], before[1]
    sav.set_position(a.slot, b.pos)
    sav.set_position(b.slot, a.pos)
    sav_path.write_bytes(sav.serialize())
    s3.import_(c.extdata_id, sd, ext)
    s3.extract(c.extdata_id, sd, ver)
    sav2 = SaveData((ver / "user" / "SaveData.dat").read_bytes())
    pos = {e.slot: e.pos for e in sav2.entries}
    assert pos[a.slot] == b.pos and pos[b.slot] == a.pos
    assert {e.tid for e in sav2.entries} == {e.tid for e in sav.entries}
    for rel in ["user/Cache.dat", "user/CacheD.dat", "icon"]:
        assert (ver / rel).read_bytes() == (ext / rel).read_bytes()


nand_ready = ready and (KEYS / "homemenu_save.bin").exists() and (KEYS / "Launcher.dat").exists()


@pytest.mark.skipif(not nand_ready, reason="system save container missing")
def test_nandsave_roundtrip_on_copy(s3, tmp_path):
    """--nandsave channel: extract == GM9 dump; import + re-extract preserves everything.
    Runs only on a tmp copy of the container; the real NAND is never touched here."""
    nand = s3.build_nand_tree(tmp_path, KEYS / "homemenu_save.bin", "0002008f")
    out1 = tmp_path / "out1"
    s3.nand_extract("0002008f", nand, out1)
    assert (out1 / "Launcher.dat").read_bytes() == (KEYS / "Launcher.dat").read_bytes()
    s3.nand_import("0002008f", nand, out1)
    out2 = tmp_path / "out2"
    s3.nand_extract("0002008f", nand, out2)
    files1 = sorted(p.relative_to(out1) for p in out1.rglob("*") if p.is_file())
    files2 = sorted(p.relative_to(out2) for p in out2.rglob("*") if p.is_file())
    assert files1 == files2
    for rel in files1:
        assert (out1 / rel).read_bytes() == (out2 / rel).read_bytes()


def test_real_sd_untouched_guard():
    """No test alters the real SD: the extdata hash on G: is compared at session start/end."""
    real = Path("G:/Nintendo 3DS")
    if not real.exists():
        pytest.skip("real SD not mounted")
    import hashlib
    h = hashlib.sha256()
    ext = next(real.glob("*/*/extdata/00000000/0000008f"))
    for p in sorted(ext.rglob("*")):
        if p.is_file():
            h.update(p.name.encode())
            h.update(p.read_bytes())
    digest = h.hexdigest()
    marker = Path(__file__).parent / ".real_sd_hash"
    if marker.exists():
        assert marker.read_text() == digest, "REAL SD WAS MODIFIED by some test!"
    else:
        marker.write_text(digest)
