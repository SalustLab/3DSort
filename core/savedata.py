"""SaveData.dat (v4) of the HOME menu - icon order and each icon's folder.

Format: 3dbrew /wiki/Home_Menu. Undocumented regions are preserved byte by
byte: the parser keeps the original buffer and only rewrites the known
arrays when serializing.
"""
import struct
from dataclasses import dataclass

SIZE = 0x2DA0
OFF_TID = 0x8       # u64[360]
OFF_STATUS = 0xB48  # s8[360], 1 = active icon
OFF_POS = 0xCB0     # s16[360], linear position on the grid
OFF_FOLDER = 0xF80  # s8[360], folder index (-1 = home grid)
OFF_FOLDER_NUM = 0x12C8  # u32[60] fid-indexed: folder baptism number (gate 0B 2026-08-14)
OFF_THEMES = 0x13B8      # from here to the end: themes/shuffle (not slot-indexed)
SLOTS = 360
EMPTY_TIDS = (0, 0xFFFFFFFFFFFFFFFF)


@dataclass
class Entry:
    slot: int
    tid: int
    pos: int
    folder: int


class SaveData:
    def __init__(self, raw: bytes):
        if len(raw) != SIZE:
            raise ValueError(f"SaveData.dat: expected {SIZE:#x} bytes, got {len(raw):#x}")
        if raw[0] != 4:
            raise ValueError(f"SaveData.dat: version {raw[0]} not supported (expected 4)")
        self._buf = bytearray(raw)

    @property
    def entries(self) -> list[Entry]:
        tids = struct.unpack_from(f"<{SLOTS}Q", self._buf, OFF_TID)
        pos = struct.unpack_from(f"<{SLOTS}h", self._buf, OFF_POS)
        folder = struct.unpack_from(f"<{SLOTS}b", self._buf, OFF_FOLDER)
        # active criterion = valid tid + pos >= 0, same as the Launcher (3dbrew).
        # status does NOT filter: never-opened games have status 0 and the console
        # shows them (gate 0C, real console). The byte is preserved, semantics unclear.
        return [Entry(i, tids[i], pos[i], folder[i]) for i in range(SLOTS)
                if tids[i] not in EMPTY_TIDS and pos[i] >= 0]

    def set_position(self, slot: int, pos: int):
        struct.pack_into("<h", self._buf, OFF_POS + slot * 2, pos)

    def set_folder(self, slot: int, folder: int):
        struct.pack_into("<b", self._buf, OFF_FOLDER + slot, folder)

    def set_folder_number(self, fid: int, n: int):
        struct.pack_into("<I", self._buf, OFF_FOLDER_NUM + fid * 4, n)

    def set_all_status(self, v: int):
        # 0 = unwrapped (mechanism of Cthulhu's Unwrap all, GPL-3)
        self._buf[OFF_STATUS:OFF_STATUS + SLOTS] = bytes([v]) * SLOTS

    def graft_tail(self, other: bytes):
        """Copies the themes/configs region (0x13B8+) from another SaveData: the write
        uses the CURRENT card version so a theme changed on the console never regresses."""
        if len(other) != SIZE:
            raise ValueError(f"graft_tail: expected {SIZE:#x} bytes, got {len(other):#x}")
        self._buf[OFF_THEMES:] = other[OFF_THEMES:]

    def apply_order(self, slots_in_order: list[int], reserved: dict | None = None):
        """Reassigns positions PER CONTAINER (home grid = -1, each folder) in the given order.

        Positions are local to the container (validated on a real Launcher.dat
        dump: a folder item restarts at 0). `reserved` ({folder: {pos,...}}) marks
        the slots that can never be occupied (NAND apps, folder tiles, gaps);
        when None, it is derived from the file's own current gaps - only valid
        if folders did NOT change (with set_folder beforehand, the derived gaps
        would mix old position with new folder: pass the reserved of the
        original state). New members of a container take the smallest free
        positions. Uses each slot's CURRENT folder. Requires all active slots.
        """
        entries = self.entries
        active = {e.slot for e in entries}
        if set(slots_in_order) != active or len(slots_in_order) != len(active):
            raise ValueError("apply_order: slot set does not match the active icons")
        if reserved is None:
            reserved = merge_reserved({e.slot: (e.folder, e.pos) for e in entries}, None)
        for slot, pos in assign_positions(
                slots_in_order, {e.slot: e.folder for e in entries}, reserved).items():
            self.set_position(slot, pos)

    def serialize(self) -> bytes:
        return bytes(self._buf)


def merge_reserved(current: dict, extra: dict | None) -> dict:
    """Reservations per container: current gaps ([0..max] minus occupied positions)
    united with the explicit ones. `current`: {slot: (folder, pos)}."""
    held = {}
    for folder, pos in current.values():
        held.setdefault(folder, set()).add(pos)
    reserved = {f: set(range(max(ps) + 1)) - ps for f, ps in held.items()}
    for f, ps in (extra or {}).items():
        reserved.setdefault(f, set()).update(ps)
    return reserved


def assign_positions(slots_in_order: list[int], folder_of: dict,
                     reserved: dict) -> dict:
    """Smallest free positions of each container, in the given order, skipping reservations."""
    out, nxt = {}, {}
    for slot in slots_in_order:
        c = folder_of[slot]
        p = nxt.get(c, 0)
        res = reserved.get(c, ())
        while p in res:
            p += 1
        out[slot] = p
        nxt[c] = p + 1
    return out
