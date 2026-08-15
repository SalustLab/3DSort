"""Launcher.dat (HOME menu system save on the NAND) - parse and surgical writes.

Format: 3dbrew /wiki/Home_Menu. Provides the positions/folders of NAND apps and
the folder definitions (name, position, rows), which do not exist on the SD.
The file lives inside the DISA container at nand:/data/<id0>/sysdata/<ID>/00000000
(ID per region: JPN 00020082, USA 0002008F, EUR 00020098), dumped via GodMode9
and edited on the PC via save3ds --nandsave (core/sdcard.py).

Same strategy as savedata.SaveData: the WHOLE buffer is preserved and only the
known arrays are rewritten. Byte-identical round-trip by construction.
Undocumented regions contain live data (cursor/UI at 0xB51-0xB5E,
statistics at 0x1D58+) - never touch them. One decoded exception from gate 0B
(2026-08-14): the "next folder number" counter (u32 @0xD80 + mirror byte
@0xD85), maintained by set_next_folder_number.
"""
import struct
from dataclasses import dataclass

SIZE = 0x2490
OFF_CART_POS = 0x2        # u16, position of the cartridge slot on the home grid
OFF_TID = 0x8             # u64[360] NAND titleIDs
OFF_POS = 0xD9A           # s16[360] linear position (space shared with the SD)
OFF_FOLDER = 0x106A       # s8[360], -1 = home grid
OFF_FOLDER_POS = 0x11DC   # s16[60], -1 = deleted folder
OFF_FOLDER_ROWS = 0x1434  # u8[60]
OFF_FOLDER_NAME = 0x1560  # 60 x 0x22 bytes UTF-16LE (16 units + guaranteed NUL)
OFF_NEXT_FOLDER_NUM = 0xD80         # u32: next folder baptism number (gate 0B)
OFF_NEXT_FOLDER_NUM_MIRROR = 0xD85  # u8: mirror of the counter (low byte)
SLOTS = 360
FOLDERS = 60
EMPTY_TIDS = (0, 0xFFFFFFFFFFFFFFFF)
NAME_BYTES = 0x22
NAME_MAX_PAYLOAD = 0x20   # 16 UTF-16 units; last 2 bytes always NUL


@dataclass
class NandEntry:
    slot: int
    tid: int
    pos: int
    folder: int


@dataclass
class Folder:
    id: int
    pos: int
    rows: int
    name: str


class Launcher:
    """Whole buffer preserved; surgical mutations on the known arrays."""

    def __init__(self, raw: bytes):
        # real console (11.17 USA) produces 0x2558 bytes: extra fields at the end, same layout
        if len(raw) < SIZE:
            raise ValueError(f"Launcher.dat: expected >= {SIZE:#x} bytes, got {len(raw):#x}")
        self._buf = bytearray(raw)

    # ---- reads -------------------------------------------------------------
    @property
    def entries(self) -> list[NandEntry]:
        tids = struct.unpack_from(f"<{SLOTS}Q", self._buf, OFF_TID)
        pos = struct.unpack_from(f"<{SLOTS}h", self._buf, OFF_POS)
        folder = struct.unpack_from(f"<{SLOTS}b", self._buf, OFF_FOLDER)
        return [NandEntry(i, tids[i], pos[i], folder[i]) for i in range(SLOTS)
                if tids[i] not in EMPTY_TIDS and pos[i] >= 0]

    @property
    def folders(self) -> list[Folder]:
        fpos = struct.unpack_from(f"<{FOLDERS}h", self._buf, OFF_FOLDER_POS)
        frows = struct.unpack_from(f"<{FOLDERS}B", self._buf, OFF_FOLDER_ROWS)
        out = []
        for i in range(FOLDERS):
            if fpos[i] < 0:
                continue
            b = self._buf[OFF_FOLDER_NAME + i * NAME_BYTES:
                          OFF_FOLDER_NAME + (i + 1) * NAME_BYTES]
            out.append(Folder(i, fpos[i], frows[i],
                              bytes(b).decode("utf-16-le").split("\x00")[0]))
        return out

    @property
    def cart_pos(self) -> int | None:
        v = struct.unpack_from("<H", self._buf, OFF_CART_POS)[0]
        return None if v >= SLOTS else v

    # ---- mutations ---------------------------------------------------------
    def set_position(self, slot: int, pos: int):
        struct.pack_into("<h", self._buf, OFF_POS + slot * 2, pos)

    def set_folder(self, slot: int, folder: int):
        struct.pack_into("<b", self._buf, OFF_FOLDER + slot, folder)

    def set_folder_pos(self, fid: int, pos: int):
        struct.pack_into("<h", self._buf, OFF_FOLDER_POS + fid * 2, pos)

    def set_folder_rows(self, fid: int, rows: int):
        if rows < 1:
            raise ValueError(f"folder {fid}: rows must be >= 1, got {rows}")
        struct.pack_into("<B", self._buf, OFF_FOLDER_ROWS + fid, rows)

    def set_folder_name(self, fid: int, name: str):
        raw = name.encode("utf-16-le")
        if not name or len(raw) > NAME_MAX_PAYLOAD:
            raise ValueError(f"invalid folder name (1..16 characters): {name!r}")
        field = raw + b"\x00" * (NAME_BYTES - len(raw))
        self._buf[OFF_FOLDER_NAME + fid * NAME_BYTES:
                  OFF_FOLDER_NAME + (fid + 1) * NAME_BYTES] = field

    def set_cart_pos(self, pos: int | None):
        struct.pack_into("<H", self._buf, OFF_CART_POS, 0xFFFF if pos is None else pos)

    @property
    def next_folder_number(self) -> int:
        return struct.unpack_from("<I", self._buf, OFF_NEXT_FOLDER_NUM)[0]

    def set_next_folder_number(self, n: int):
        # the console duplicates the value in a byte @0xD85; exact semantics unknown,
        # we mirror the low byte (observed real values are small)
        struct.pack_into("<I", self._buf, OFF_NEXT_FOLDER_NUM, n)
        struct.pack_into("<B", self._buf, OFF_NEXT_FOLDER_NUM_MIRROR, n & 0xFF)

    def free_folder_ids(self) -> list[int]:
        """fids with pos < 0 and NO active NAND entry pointing at them.
        SD refs are checked at the Api layer (SaveData is not visible from here)."""
        fpos = struct.unpack_from(f"<{FOLDERS}h", self._buf, OFF_FOLDER_POS)
        referenced = {e.folder for e in self.entries}
        return [i for i in range(FOLDERS) if fpos[i] < 0 and i not in referenced]

    def create_folder(self, name: str, rows: int = 2) -> int:
        """Claims the smallest free fid; pos stays -1 until the caller places the tile."""
        free = self.free_folder_ids()
        if not free:
            raise ValueError("no free folder slot (60 in use)")
        fid = free[0]
        self.set_folder_name(fid, name)
        self.set_folder_rows(fid, rows)
        return fid

    def delete_folder(self, fid: int):
        members = [e.slot for e in self.entries if e.folder == fid]
        if members:
            raise ValueError(f"folder {fid} still has NAND members: {members}")
        self.set_folder_pos(fid, -1)
        struct.pack_into("<B", self._buf, OFF_FOLDER_ROWS + fid, 2)
        self._buf[OFF_FOLDER_NAME + fid * NAME_BYTES:
                  OFF_FOLDER_NAME + (fid + 1) * NAME_BYTES] = b"\x00" * NAME_BYTES

    # ---- invariants --------------------------------------------------------
    def validate(self, active_sd_refs: set = frozenset()):
        """Called before every write. Errors here never reach the console."""
        live = {f.id for f in self.folders}
        containers: dict[int, list[int]] = {}
        for e in self.entries:
            if e.folder != -1 and e.folder not in live:
                raise ValueError(f"NAND slot {e.slot} references dead folder {e.folder}")
            if not 0 <= e.pos < SLOTS:
                raise ValueError(f"NAND slot {e.slot} has position outside the grid: {e.pos}")
            containers.setdefault(e.folder, []).append(e.pos)
        for f in self.folders:
            if not 0 <= f.pos < SLOTS:
                raise ValueError(f"folder {f.id} has position outside the grid: {f.pos}")
            if f.rows < 1:
                raise ValueError(f"folder {f.id} has invalid rows: {f.rows}")
            containers.setdefault(-1, []).append(f.pos)
        if self.cart_pos is not None:
            containers.setdefault(-1, []).append(self.cart_pos)
        for cont, ps in containers.items():
            dup = {p for p in ps if ps.count(p) > 1}
            if dup:
                raise ValueError(f"duplicate positions in container {cont}: {sorted(dup)}")
        for ref in active_sd_refs:
            if ref != -1 and ref not in live:
                raise ValueError(f"SaveData references dead folder {ref}")

    def serialize(self) -> bytes:
        out = bytes(self._buf)
        if not out:  # CLAUDE.md 5.6: a zero-size file breaks the extdata/save on the console
            raise ValueError("serialize would produce an empty file")
        return out


def parse(raw: bytes) -> tuple[list[NandEntry], list[Folder], int | None]:
    """Compat wrapper: -> (NAND entries, folders, cartridge position or None)."""
    ln = Launcher(raw)
    return ln.entries, ln.folders, ln.cart_pos
