# Save formats and preservation boundaries

Implementation references: `core/savedata.py`, `core/launcher.py`, `core/icons.py`.
Historical source: main CLAUDE.md section 5 (at a4aef85).

## SaveData.dat v4

Accepted sizes: 0x2DA0 and 0x2CB0. Both have the same known arrays; the latter
has a tail 0xF0 shorter. Other sizes/versions fail closed.

| Offset | Field |
|---|---|
| 0x8 | 360 u64 title IDs |
| 0xB48 | 360 status bytes; never use as active-title filter |
| 0xCB0 | 360 s16 positions |
| 0xF80 | 360 s8 folders; -1 = HOME |
| 0x12C8 | 60 u32 folder baptism numbers |
| 0x13B8 | theme/shuffle tail |

Active means nonzero/non-FFFFFFFFFFFFFFFF title ID and nonnegative position.
Preserve unknown bytes, including 0x10E8..0x12C8. Writes clear status bytes;
this is not proof that all console-internal gift-box state is controlled.
Fresh card theme bytes are grafted during writing, including after restore;
graft_tail adopts the fresh tail length. This is preservation, not theme editing.

## Launcher and caches

Launcher accepts at least 0x2490 bytes; historically observed USA 11.17 size
is 0x2558. Known arrays: tids @0x8, positions @0xD9A, folders @0x106A;
folder positions @0x11DC, rows @0x1434, names @0x1560 (0x22 bytes each).
Game Card position is u16 @0x2. Folder counter is u32 @0xD80 with mirror
@0xD85. Preserve unknown tail and volatile state. Folder names permit 16
UTF-16 units plus terminator. Definitions belong to Launcher, not SaveData.

Cache.dat has an 8-byte header and 16-byte records indexing CacheD.dat.
CacheD entries are 0x36C0-byte SMDH records, or TWL headers with NDS banner
@0x378. SMDH names start @0x8 + language*0x200; icon @0x24C0 uses RGB565
Morton tiles. TWL icons use banner+0x20, palette +0x220 and names +0x240.
DSiWare high tid 00048004 is a game, not the cartridge slot. Homebrew cannot
be identified solely by retail title-ID range.

Badge formats and empirical evidence remain canonical in
[BADGES_TESTING](BADGES_TESTING.md); exact-position contracts in
[SPATIAL_LAYOUT](SPATIAL_LAYOUT.md).
