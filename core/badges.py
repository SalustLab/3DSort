"""Preserving reader for HOME badge extdata; writes are hardware-gated.

Format reference: https://www.3dbrew.org/wiki/Home_Menu#BadgeMngFile.dat
The layout writer is exercised on synthetic data only until the procedure in
docs/BADGES_TESTING.md establishes the layout sentinels and folder encoding.
"""
import base64
import io
import struct
from collections import Counter

from core.icons import MORTON

EXTDATA_ID = "00000000000014d1"
DATA_SIZE = 0xF4DF80
MNG_SIZE = 0xD4A8
INFO = 0x3E8
LAYOUT = 0xB2E8
EMPTY = 0xFFFFFFFF
# Free placement record as HOME writes it (hardware-proven 2026-09-07, USA New
# 3DS: placing one badge rewrote all 360 records): u32 0, badgeId/setId 0xFFFFFFFF,
# index 0xFFFF, sub 0, pos/folder 0xFFFFFFFF. GYTB leaves the table all zero.
EMPTY_RECORD = bytes(4) + b"\xff" * 10 + bytes(2) + b"\xff" * 8
DECORATION = 0xF0FF
# Opened 2026-09-07 after the console cases in docs/BADGES_TESTING.md (USA New
# 3DS, byte parity with HOME's own writes for place/move/remove, folder member,
# decoration incl. folder move/delete, repeated copies, shortcut, stock, rows).
HARDWARE_VALIDATED = True
VALIDATION_MESSAGE = ("Badge layout editing is awaiting console validation. "
                      "This card is read-only to protect its badges. "
                      "See docs/BADGES_TESTING.md in the source distribution.")
# sub-ID -> (width, height, x, y), as documented by 3dbrew.
SHAPES = {0: (1, 1, 0, 0), 0x100: (2, 1, 0, 0), 0x101: (2, 1, 1, 0),
          0x1000: (1, 2, 0, 0), 0x1010: (1, 2, 0, 1),
          0x1100: (2, 2, 0, 0), 0x1101: (2, 2, 1, 0),
          0x1110: (2, 2, 0, 1), 0x1111: (2, 2, 1, 1)}


class Badges:
    def __init__(self, data, management):
        if len(data) != DATA_SIZE or len(management) != MNG_SIZE:
            raise ValueError("Badge files have an unsupported size.")
        self.data, self.raw = bytes(data), bytes(management)
        self.catalog, self.layout, self.sets, self._images = {}, {}, {}, {}
        u32 = lambda off: struct.unpack_from("<I", management, off)[0]
        if u32(0) or u32(4) > 100 or u32(8) > 1000 or u32(12) > 360:
            raise ValueError("Invalid badge header.")
        for n in range(100):
            off = 0xA028 + n * 0x30
            sid, index = u32(off + 0x10), u32(off + 0x14)
            if sid not in (0, EMPTY) and index < 100:
                self.sets[sid] = self._title(index * 16 * 0x8A, f"Set {sid}")
        for n in range(1000):
            if not management[0x358 + n // 8] & (1 << (n % 8)):
                continue
            off = INFO + n * 0x28
            _, bid, sid, index, sub = struct.unpack_from("<IIIHH", management, off)
            placed, quantity = struct.unpack_from("<HH", management, off + 0x10)
            if index >= 1000 or sub not in SHAPES:
                raise ValueError("Unsupported badge identifier or shape.")
            self.catalog[n] = dict(id=n, badgeId=bid, setId=sid, index=index,
                                   sub=sub, quantity=quantity, placed=placed,
                                   name=self._title(0x35E80 + index * 16 * 0x8A, f"Badge {bid}"),
                                   setName=self.sets.get(sid, f"Set {sid}"),
                                   shortcut=f"{struct.unpack_from('<Q', management, off + 0x18)[0]:016x}")
        identifiers = {self.raw[INFO + n * 0x28:INFO + n * 0x28 + 16]: n
                       for n in self.catalog}
        for n in range(360):
            off = LAYOUT + n * 24
            record = self.raw[off:off + 24]
            ident = record[:16]
            pos, folder = struct.unpack_from("<II", management, off + 16)
            # Free = HOME's sentinel or GYTB's untouched zero record; anything
            # else that names no badge fails closed.
            if record in (EMPTY_RECORD, bytes(24)):
                continue
            if ident not in identifiers:
                raise ValueError("Badge layout references an unknown badge.")
            # Decoration (hardware-proven, cases 06/07): folder == 0xF0FF and pos =
            # the HOME grid position of the FOLDER TILE, not the folder id. The
            # file-level layout keeps that position; LayoutApi maps it to the id.
            decoration = pos if folder == DECORATION else None
            self.layout[n] = dict(badge=identifiers[ident], pos=pos,
                                  folder=-1 if folder in (EMPTY, DECORATION) else folder,
                                  decoration=decoration)
        if len(self.layout) != u32(12):
            raise ValueError("Badge placement count does not match its layout.")
        counts = Counter(b["badge"] for b in self.layout.values())
        if any(b["placed"] != counts[n] for n, b in self.catalog.items()):
            raise ValueError("Badge per-item placement counts do not match the layout.")
        self.validate(self.layout)

    def _title(self, off, fallback):
        for lang in (1, 0):
            title = self.data[off + lang * 0x8A:off + (lang + 1) * 0x8A]
            name = title.decode("utf-16-le", "replace").split("\0", 1)[0].strip()
            if name:
                return name
        return fallback

    def image(self, badge):
        from PIL import Image
        if badge not in self.catalog:
            raise ValueError("Badge does not exist.")
        if badge not in self._images:
            off = 0x318F80 + self.catalog[badge]["index"] * 0x2800
            img = Image.new("RGBA", (64, 64))
            pix = img.load()
            n = 0
            for ty in range(0, 64, 8):
                for tx in range(0, 64, 8):
                    for x, y in MORTON:
                        rgb = struct.unpack_from("<H", self.data, off + n * 2)[0]
                        a = (self.data[off + 0x2000 + n // 2] >> ((n % 2) * 4)) & 15
                        pix[tx + x, ty + y] = (((rgb >> 11) * 255 // 31),
                                              ((rgb >> 5 & 63) * 255 // 63),
                                              ((rgb & 31) * 255 // 31), a * 17)
                        n += 1
            stream = io.BytesIO()
            img.save(stream, "PNG")
            self._images[badge] = base64.b64encode(stream.getvalue()).decode("ascii")
        return self._images[badge]

    def pieces(self, badge):
        c = self.catalog[badge]
        if c["sub"] == 0:
            return [badge]
        pieces = [n for n, b in self.catalog.items()
                  if (b["badgeId"], b["setId"]) == (c["badgeId"], c["setId"])]
        w, h, _, _ = SHAPES[c["sub"]]
        coords = [SHAPES[self.catalog[n]["sub"]] for n in pieces]
        if (len(pieces) != w * h or
                set(coords) != {(w, h, x, y) for x in range(w) for y in range(h)}):
            raise ValueError("This composite badge has missing or ambiguous pieces.")
        return sorted(pieces, key=lambda n: SHAPES[self.catalog[n]["sub"]][2:])

    def validate(self, layout):
        if len(layout) > 360 or any(type(n) is not int or not 0 <= n < 360 for n in layout):
            raise ValueError("The badge layout is full or invalid.")
        used = Counter(b["badge"] for b in layout.values())
        for n, count in used.items():
            if n not in self.catalog or count > self.catalog[n]["quantity"]:
                raise ValueError("No copies of this badge are available.")
        decorations = set()
        for b in layout.values():
            if b.get("decoration") is not None:
                ref = b["decoration"]  # folder id in staging, folder tile position in the file
                if type(ref) is not int or not 0 <= ref < 360 or ref in decorations or self.catalog[b["badge"]]["sub"]:
                    raise ValueError("Invalid or duplicate folder decoration.")
                decorations.add(ref)

    def serialize(self, layout=None, *, validated=False):
        if layout is None or layout == self.layout:
            return self.raw
        if not validated and not HARDWARE_VALIDATED:
            raise ValueError(VALIDATION_MESSAGE)
        self.validate(layout)
        out = bytearray(self.raw)
        for n in range(360):  # HOME normalizes untouched zero records on its first write
            off = LAYOUT + n * 24
            if out[off:off + 24] == bytes(24):
                out[off:off + 24] = EMPTY_RECORD
        for slot in self.layout.keys() | layout.keys():
            off = LAYOUT + slot * 24
            if slot not in layout:
                out[off:off + 24] = EMPTY_RECORD
                continue
            b = layout[slot]
            info = INFO + b["badge"] * 0x28
            out[off:off + 16] = self.raw[info:info + 16]
            decor = b.get("decoration")
            struct.pack_into("<II", out, off + 16,
                             b["pos"] if decor is None else decor,
                             (EMPTY if b["folder"] == -1 else b["folder"]) if decor is None else DECORATION)
        struct.pack_into("<I", out, 12, len(layout))
        counts = Counter(b["badge"] for b in layout.values())
        for n in self.catalog:
            struct.pack_into("<H", out, INFO + n * 0x28 + 0x10, counts[n])
        return bytes(out)


def make_mock_badges(target):
    """Synthetic artwork and identifiers only; never uses a console collection."""
    data, mng = bytearray(DATA_SIZE), bytearray(MNG_SIZE)
    names = ["Sun", "Leaf", "Rainbow", "Rainbow", "Window", "Window", "Window", "Window"]
    subs = [0, 0, 0x100, 0x101, 0x1100, 0x1101, 0x1110, 0x1111]
    struct.pack_into("<III", mng, 4, 1, len(names), 0)
    struct.pack_into("<II", mng, 0xA028 + 0x10, 1, 0)
    data[0x8A:0x8A + 18] = "Demo set\0".encode("utf-16-le")
    for n, name in enumerate(names):
        bid = n + 1 if n < 2 else (3 if n < 4 else 4)
        struct.pack_into("<IIIHHHH", mng, INFO + n * 40, 0, bid, 1, n, subs[n], 0, 5)
        mng[0x358 + n // 8] |= 1 << (n % 8)
        off = 0x35E80 + n * 16 * 0x8A + 0x8A
        title = (name + "\0").encode("utf-16-le")
        data[off:off + len(title)] = title
        off = 0x318F80 + n * 0x2800
        rgb = [0xFE80, 0x5668, 0xEBB8, 0x433F, 0x641F, 0xFB40, 0x841F, 0x46DF][n]
        data[off:off + 0x2000] = struct.pack("<H", rgb) * 4096
        data[off + 0x2000:off + 0x2800] = b"\xdd" * 2048
    user = target / "user"
    user.mkdir(parents=True, exist_ok=True)
    (target / "boss").mkdir(exist_ok=True)
    (target / "icon").write_bytes(b"synthetic badge extdata")
    (user / "BadgeData.dat").write_bytes(data)
    (user / "BadgeMngFile.dat").write_bytes(mng)
