import struct

import pytest

from core.savedata import SaveData, SIZE, OFF_TID, OFF_STATUS, OFF_POS, OFF_FOLDER


def build_fixture(entries, version=4):
    """entries: list of (slot, tid, pos, folder). Regioes desconhecidas com padrao 0xA5."""
    buf = bytearray(b"\xa5" * SIZE)
    buf[0] = version
    for i in range(360):
        struct.pack_into("<Q", buf, OFF_TID + i * 8, 0)
        struct.pack_into("<b", buf, OFF_STATUS + i, 0)
        struct.pack_into("<h", buf, OFF_POS + i * 2, -1)
        struct.pack_into("<b", buf, OFF_FOLDER + i, -1)
    for slot, tid, pos, folder in entries:
        struct.pack_into("<Q", buf, OFF_TID + slot * 8, tid)
        struct.pack_into("<b", buf, OFF_STATUS + slot, 1)
        struct.pack_into("<h", buf, OFF_POS + slot * 2, pos)
        struct.pack_into("<b", buf, OFF_FOLDER + slot, folder)
    return bytes(buf)


ENTRIES = [(0, 0x0004000000030800, 0, -1), (5, 0x0004000000064D00, 1, -1), (9, 0x00040000000EDF00, 2, 3)]


def test_roundtrip_identical_bytes():
    raw = build_fixture(ENTRIES)
    assert SaveData(raw).serialize() == raw


def test_parse_active_entries():
    sd = SaveData(build_fixture(ENTRIES))
    assert [(e.slot, e.tid, e.pos, e.folder) for e in sd.entries] == ENTRIES


def test_swap_positions_touches_only_pos_array():
    raw = build_fixture(ENTRIES)
    sd = SaveData(raw)
    sd.set_position(0, 2)
    sd.set_position(9, 0)
    out = sd.serialize()
    diffs = {i for i in range(SIZE) if out[i] != raw[i]}
    assert diffs <= set(range(OFF_POS, OFF_POS + 720))
    sd2 = SaveData(out)
    assert {e.slot: e.pos for e in sd2.entries} == {0: 2, 5: 1, 9: 0}


def test_apply_order_preserves_position_multiset_per_container():
    # home grid com lacunas (slots NAND): posicoes 13, 15 mantidas; pasta preserva a sua
    entries = [(0, 0x0004000000030800, 13, -1), (5, 0x0004000000064D00, 15, -1),
               (9, 0x00040000000EDF00, 2, 3)]
    sd = SaveData(build_fixture(entries))
    sd.apply_order([9, 5, 0])  # nova ordem por slot (9 esta na pasta 3)
    assert {e.slot: e.pos for e in sd.entries} == {5: 13, 0: 15, 9: 2}


def test_apply_order_keeps_dense_positions_dense():
    sd = SaveData(build_fixture(ENTRIES))  # home: slots 0,5 pos 0,1; pasta 3: slot 9 pos 2
    sd.apply_order([9, 5, 0])
    assert {e.slot: e.pos for e in sd.entries} == {5: 0, 0: 1, 9: 2}


def test_apply_order_respects_reserved_positions():
    # reserva explicita (apps NAND conhecidos via Launcher.dat)
    entries = [(0, 0x0004000000030800, 3, -1), (5, 0x0004000000064D00, 4, -1)]
    sd = SaveData(build_fixture(entries))
    sd.apply_order([5, 0], reserved={-1: {0, 1, 2, 4}})
    assert {e.slot: e.pos for e in sd.entries} == {5: 3, 0: 5}


def test_apply_order_new_folder_member_appends_after_reserved():
    # slot 5 acabou de entrar na pasta 2 (posicao 0 da pasta reservada a app NAND)
    entries = [(0, 0x0004000000030800, 0, -1), (5, 0x0004000000064D00, 1, 2)]
    sd = SaveData(build_fixture(entries))
    sd.apply_order([0, 5], reserved={2: {0}})
    assert {e.slot: e.pos for e in sd.entries} == {0: 0, 5: 1}


def test_apply_order_rejects_wrong_slot_set():
    sd = SaveData(build_fixture(ENTRIES))
    with pytest.raises(ValueError):
        sd.apply_order([9, 0])  # faltou slot 5


def test_set_folder():
    sd = SaveData(build_fixture(ENTRIES))
    sd.set_folder(0, 3)
    sd.set_folder(9, -1)
    sd2 = SaveData(sd.serialize())
    assert {e.slot: e.folder for e in sd2.entries} == {0: 3, 5: -1, 9: -1}


def test_titles_never_lost_on_operations():
    sd = SaveData(build_fixture(ENTRIES))
    before = {e.tid for e in sd.entries}
    sd.apply_order([5, 9, 0])
    sd.set_folder(5, 2)
    assert {e.tid for e in SaveData(sd.serialize()).entries} == before


def test_rejects_bad_size_and_version():
    with pytest.raises(ValueError):
        SaveData(b"\x00" * 10)
    with pytest.raises(ValueError):
        SaveData(build_fixture(ENTRIES, version=9))
