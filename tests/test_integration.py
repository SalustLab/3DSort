"""Integracao real: save3ds + chaves reais contra o SD SANDBOX (copia).
Nunca toca o SD real. Pulados se boot9/movable/sandbox nao existirem.
"""
import shutil
from pathlib import Path

import pytest

from core.savedata import SaveData
from core.sdcard import Save3ds, find_console

ROOT = Path(__file__).parent.parent
KEYS = ROOT / "sandbox" / "keys"
SD_SRC = ROOT / "sandbox" / "sd"

ready = all(p.exists() for p in
            [KEYS / "boot9.bin", KEYS / "movable.sed", SD_SRC,
             ROOT / "tools" / "save3ds" / "save3ds_fuse.exe"])
pytestmark = pytest.mark.skipif(not ready, reason="sandbox/chaves reais ausentes")


@pytest.fixture()
def sd(tmp_path):
    """Copia fresca do SD sandbox por teste — nem o sandbox original e alterado."""
    dst = tmp_path / "sd"
    shutil.copytree(SD_SRC, dst)
    return dst


@pytest.fixture()
def s3():
    return Save3ds(ROOT / "tools" / "save3ds" / "save3ds_fuse.exe",
                   KEYS / "boot9.bin", KEYS / "movable.sed")


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


def test_real_sd_untouched_guard():
    """Nenhum teste altera o SD real: hash do extdata em G: e comparado no inicio/fim da sessao."""
    real = Path("G:/Nintendo 3DS")
    if not real.exists():
        pytest.skip("SD real nao montado")
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
        assert marker.read_text() == digest, "SD REAL FOI MODIFICADO por algum teste!"
    else:
        marker.write_text(digest)
