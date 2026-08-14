import struct

import pytest

from core.launcher import (FOLDERS, OFF_FOLDER, OFF_FOLDER_NAME, OFF_FOLDER_POS,
                           OFF_FOLDER_ROWS, OFF_POS, OFF_TID, SIZE, SLOTS, parse)


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
