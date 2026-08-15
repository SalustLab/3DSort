import struct
from pathlib import Path

import pytest

from core.launcher import (FOLDERS, Launcher, OFF_CART_POS, OFF_FOLDER,
                           OFF_FOLDER_NAME, OFF_FOLDER_POS, OFF_FOLDER_ROWS,
                           OFF_NEXT_FOLDER_NUM, OFF_NEXT_FOLDER_NUM_MIRROR,
                           OFF_POS, OFF_TID, SIZE, SLOTS, parse)


def build_fixture(entries, folders=(), cart_pos=0xFFFF):
    """entries: (slot, tid, pos, folder). folders: (id, pos, rows, name)."""
    buf = bytearray(b"\xa5" * SIZE)
    struct.pack_into("<H", buf, 0x2, cart_pos)
    for i in range(SLOTS):
        struct.pack_into("<Q", buf, OFF_TID + i * 8, 0)
        struct.pack_into("<h", buf, OFF_POS + i * 2, -1)
        struct.pack_into("<b", buf, OFF_FOLDER + i, -1)
    for i in range(FOLDERS):
        struct.pack_into("<h", buf, OFF_FOLDER_POS + i * 2, -1)
        struct.pack_into("<B", buf, OFF_FOLDER_ROWS + i, 2)
        buf[OFF_FOLDER_NAME + i * 0x22: OFF_FOLDER_NAME + (i + 1) * 0x22] = b"\x00" * 0x22
    for slot, tid, pos, folder in entries:
        struct.pack_into("<Q", buf, OFF_TID + slot * 8, tid)
        struct.pack_into("<h", buf, OFF_POS + slot * 2, pos)
        struct.pack_into("<b", buf, OFF_FOLDER + slot, folder)
    for fid, pos, rows, name in folders:
        struct.pack_into("<h", buf, OFF_FOLDER_POS + fid * 2, pos)
        struct.pack_into("<B", buf, OFF_FOLDER_ROWS + fid, rows)
        raw = name.encode("utf-16-le")
        buf[OFF_FOLDER_NAME + fid * 0x22: OFF_FOLDER_NAME + fid * 0x22 + len(raw)] = raw
    return bytes(buf)


def test_parse_entries_and_folders():
    raw = build_fixture(
        [(0, 0x0004001000021000, 0, -1),   # System Settings
         (1, 0x0004001000021900, 5, 2),    # eShop dentro da pasta 2
         (2, 0xFFFFFFFFFFFFFFFF, 3, -1),   # slot vazio (tid sentinela)
         (3, 0x0004001000021700, -1, -1)], # inativo (pos -1)
        folders=[(2, 7, 3, "Sistema")], cart_pos=11)
    entries, folders, cart_pos = parse(raw)
    assert [(e.tid, e.pos, e.folder) for e in entries] == [
        (0x0004001000021000, 0, -1), (0x0004001000021900, 5, 2)]
    assert [(f.id, f.pos, f.rows, f.name) for f in folders] == [(2, 7, 3, "Sistema")]
    assert cart_pos == 11


def test_cart_position_invalid_is_none():
    assert parse(build_fixture([], cart_pos=0xFFFF))[2] is None


def test_rejects_bad_size():
    with pytest.raises(ValueError):
        parse(b"\x00" * 10)


# ---- classe Launcher (v1.1: escrita) ---------------------------------------

def diff_offsets(a: bytes, b: bytes) -> set:
    assert len(a) == len(b)
    return {i for i in range(len(a)) if a[i] != b[i]}


def test_roundtrip_identity_at_both_sizes():
    for extra in (0, 200):  # 3dbrew doc (0x2490) e console real (0x2558)
        raw = build_fixture([(0, 0x1000, 0, -1)]) + b"\xa5" * extra
        assert Launcher(raw).serialize() == raw


def test_entries_carry_slot_index():
    raw = build_fixture([(7, 0x1000, 3, -1), (9, 0x2000, 1, 0)],
                        folders=[(0, 0, 2, "F")])
    ln = Launcher(raw)
    assert [(e.slot, e.tid, e.pos, e.folder) for e in ln.entries] == [
        (7, 0x1000, 3, -1), (9, 0x2000, 1, 0)]


def test_mutations_touch_only_their_arrays():
    raw = build_fixture([(2, 0x1000, 0, -1)], folders=[(1, 5, 2, "AB")], cart_pos=3)
    cases = [
        (lambda l: l.set_position(2, 9), range(OFF_POS + 4, OFF_POS + 6)),
        (lambda l: l.set_folder(2, 1), range(OFF_FOLDER + 2, OFF_FOLDER + 3)),
        (lambda l: l.set_folder_pos(1, 8), range(OFF_FOLDER_POS + 2, OFF_FOLDER_POS + 4)),
        (lambda l: l.set_folder_rows(1, 3), range(OFF_FOLDER_ROWS + 1, OFF_FOLDER_ROWS + 2)),
        (lambda l: l.set_folder_name(1, "XY"),
         range(OFF_FOLDER_NAME + 0x22, OFF_FOLDER_NAME + 2 * 0x22)),
        (lambda l: l.set_cart_pos(7), range(OFF_CART_POS, OFF_CART_POS + 2)),
        (lambda l: l.set_cart_pos(None), range(OFF_CART_POS, OFF_CART_POS + 2)),
        (lambda l: l.set_next_folder_number(3),
         set(range(OFF_NEXT_FOLDER_NUM, OFF_NEXT_FOLDER_NUM + 4)) |
         {OFF_NEXT_FOLDER_NUM_MIRROR}),
    ]
    for mutate, allowed in cases:
        ln = Launcher(raw)
        mutate(ln)
        assert diff_offsets(ln.serialize(), raw) <= set(allowed), mutate


def test_next_folder_number_roundtrip_and_mirror():
    # gate 0B: contador "proximo nº de pasta" u32 @0xD80 + byte espelho @0xD85
    raw = bytearray(build_fixture([]))
    struct.pack_into("<I", raw, OFF_NEXT_FOLDER_NUM, 2)
    raw[OFF_NEXT_FOLDER_NUM_MIRROR] = 2
    ln = Launcher(bytes(raw))
    assert ln.next_folder_number == 2
    ln.set_next_folder_number(3)
    out = ln.serialize()
    assert struct.unpack_from("<I", out, OFF_NEXT_FOLDER_NUM)[0] == 3
    assert out[OFF_NEXT_FOLDER_NUM_MIRROR] == 3
    assert Launcher(out).next_folder_number == 3


def test_cart_pos_none_writes_sentinel():
    ln = Launcher(build_fixture([], cart_pos=3))
    ln.set_cart_pos(None)
    assert ln.cart_pos is None
    assert struct.unpack_from("<H", ln.serialize(), OFF_CART_POS)[0] == 0xFFFF


def test_folder_name_validation():
    ln = Launcher(build_fixture([], folders=[(0, 1, 2, "A")]))
    ln.set_folder_name(0, "X" * 16)  # 16 unidades UTF-16 = 0x20 bytes, cabe
    assert ln.folders[0].name == "X" * 16
    with pytest.raises(ValueError):
        ln.set_folder_name(0, "X" * 17)
    with pytest.raises(ValueError):
        ln.set_folder_name(0, "")


def test_create_folder_picks_lowest_free_fid():
    raw = build_fixture([(0, 0x1000, 0, 3)], folders=[(0, 1, 2, "A")])
    ln = Launcher(raw)
    # fid 0 ocupado (pos>=0); fid 3 referenciado por entrada ativa; menor livre = 1
    assert ln.create_folder("New") == 1
    assert [(f.id, f.name) for f in ln.folders if f.id == 1] == []  # pos ainda -1
    ln.set_folder_pos(1, 4)
    assert [(f.id, f.pos, f.rows, f.name) for f in ln.folders] == [
        (0, 1, 2, "A"), (1, 4, 2, "New")]


def test_delete_folder_requires_empty_and_clears_definition():
    raw = build_fixture([(0, 0x1000, 0, 1)], folders=[(1, 2, 3, "Full")])
    ln = Launcher(raw)
    with pytest.raises(ValueError):
        ln.delete_folder(1)
    ln.set_folder(0, -1)
    ln.delete_folder(1)
    assert ln.folders == []
    s = ln.serialize()
    assert struct.unpack_from("<h", s, OFF_FOLDER_POS + 2)[0] == -1
    assert s[OFF_FOLDER_NAME + 0x22: OFF_FOLDER_NAME + 2 * 0x22] == b"\x00" * 0x22


def test_validate_catches_duplicates_and_dead_refs():
    # duplicata no home: entrada NAND pos 5 + tile de pasta pos 5
    ln = Launcher(build_fixture([(0, 0x1000, 5, -1)], folders=[(0, 5, 2, "A")]))
    with pytest.raises(ValueError):
        ln.validate()
    # duplicata dentro de pasta
    ln = Launcher(build_fixture([(0, 0x1000, 2, 0), (1, 0x2000, 2, 0)],
                                folders=[(0, 0, 2, "A")]))
    with pytest.raises(ValueError):
        ln.validate()
    # ref de entrada NAND a pasta morta
    ln = Launcher(build_fixture([(0, 0x1000, 0, 9)]))
    with pytest.raises(ValueError):
        ln.validate()
    # ref SD (vinda do SaveData) a pasta morta
    ln = Launcher(build_fixture([]))
    with pytest.raises(ValueError):
        ln.validate(active_sd_refs={9})
    # cart duplicado com entrada do home
    ln = Launcher(build_fixture([(0, 0x1000, 3, -1)], cart_pos=3))
    with pytest.raises(ValueError):
        ln.validate()
    # estado do console real e valido
    ok = Launcher(build_fixture([(0, 0x1000, 0, -1), (1, 0x2000, 6, 0)],
                                folders=[(0, 12, 2, "Homebrew")], cart_pos=11))
    ok.validate(active_sd_refs={0, -1})


REAL = Path(__file__).parent.parent / "sandbox" / "keys" / "Launcher.dat"


@pytest.mark.skipif(not REAL.exists(), reason="dump real ausente")
def test_real_dump_roundtrips_and_validates():
    raw = REAL.read_bytes()
    ln = Launcher(raw)
    assert ln.serialize() == raw
    ln.validate()  # o estado real do console e, por definicao, valido
