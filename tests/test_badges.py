import base64
import io
import struct

import pytest
from PIL import Image

from core.badges import Badges, DATA_SIZE, DECORATION, EMPTY_RECORD, INFO, LAYOUT, MNG_SIZE, make_mock_badges


@pytest.fixture
def collection(tmp_path):
    make_mock_badges(tmp_path)
    return Badges((tmp_path / "user" / "BadgeData.dat").read_bytes(),
                  (tmp_path / "user" / "BadgeMngFile.dat").read_bytes())


def test_roundtrip_preserves_unknown_bytes(collection):
    raw = bytearray(collection.raw)
    raw[0x100:0x110] = bytes(range(16))
    parsed = Badges(collection.data, raw)
    assert parsed.serialize() == raw
    modified = parsed.serialize({0: dict(badge=0, folder=-1, pos=22, decoration=None)}, validated=True)
    changed = {i for i, (a, b) in enumerate(zip(raw, modified)) if a != b}
    # counters, the per-badge count and the placement table only (zero records are
    # normalized to EMPTY_RECORD like HOME does); everything else byte-preserved
    assert changed <= set(range(12, 16)) | set(range(INFO + 0x10, INFO + 0x12)) | set(range(LAYOUT, LAYOUT + 360 * 24))
    assert Badges(collection.data, modified).layout[0]["pos"] == 22


def test_home_written_empty_records_and_first_placement(collection):
    """Hardware evidence (USA New 3DS, 4-row HOME, 2026-09-07, sandbox
    badge-validation/02-single): placing ONE badge made HOME rewrite all 360
    placement records. Empty record = u32 0, badgeId/setId 0xFFFFFFFF, index
    0xFFFF, sub 0, pos/folder 0xFFFFFFFF. The placed badge took layout slot 0,
    pos 118 = column 30, row 3 (1-based) in column-major order, folder 0xFFFFFFFF."""
    raw = bytearray(collection.raw)
    for n in range(360):
        raw[LAYOUT + n * 24:LAYOUT + (n + 1) * 24] = EMPTY_RECORD
    raw[LAYOUT:LAYOUT + 16] = raw[INFO:INFO + 16]
    struct.pack_into("<II", raw, LAYOUT + 16, 118, 0xFFFFFFFF)
    struct.pack_into("<I", raw, 12, 1)
    struct.pack_into("<H", raw, INFO + 0x10, 1)
    parsed = Badges(collection.data, raw)
    assert parsed.layout == {0: dict(badge=0, pos=118, folder=-1, decoration=None)}
    assert parsed.serialize() == raw
    removed = parsed.serialize({}, validated=True)
    assert removed[LAYOUT:LAYOUT + 24] == EMPTY_RECORD
    assert struct.unpack_from("<I", removed, 12)[0] == 0
    assert Badges(collection.data, removed).layout == {}


def test_decoration_record_is_folder_home_position(collection):
    """Hardware evidence (cases 06/07, 2026-09-07): a folder decoration record has
    folder = 0xF0FF and pos = the HOME grid position of the FOLDER TILE (12 for a
    folder at cell 12), not the folder id. Positions up to 359 are valid."""
    raw = bytearray(collection.raw)
    for n in range(360):
        raw[LAYOUT + n * 24:LAYOUT + (n + 1) * 24] = EMPTY_RECORD
    for slot, (badge, pos) in enumerate(((1, 12), (0, 200))):
        raw[LAYOUT + slot * 24:LAYOUT + slot * 24 + 16] = raw[INFO + badge * 0x28:INFO + badge * 0x28 + 16]
        struct.pack_into("<II", raw, LAYOUT + slot * 24 + 16, pos, DECORATION)
        struct.pack_into("<H", raw, INFO + badge * 0x28 + 0x10, 1)
    struct.pack_into("<I", raw, 12, 2)
    parsed = Badges(collection.data, raw)
    assert parsed.layout == {0: dict(badge=1, pos=12, folder=-1, decoration=12),
                             1: dict(badge=0, pos=200, folder=-1, decoration=200)}
    assert parsed.serialize() == raw
    moved = parsed.serialize({**parsed.layout, 0: dict(badge=1, pos=40, folder=-1, decoration=40)}, validated=True)
    assert struct.unpack_from("<II", moved, LAYOUT + 16) == (40, DECORATION)


def test_icon_alpha_and_color(collection):
    img = Image.open(io.BytesIO(base64.b64decode(collection.image(0)))).convert("RGBA")
    assert img.size == (64, 64)
    assert img.getpixel((0, 0)) == (255, 210, 0, 221)
    assert collection.catalog[0]["name"] == "Sun"


def test_tiled_icon_pixel_order(collection):
    data = bytearray(collection.data)
    # Morton indices 1 and 2 are adjacent horizontally and vertically.
    struct.pack_into("<H", data, 0x318F80 + 2, 0xF800)
    struct.pack_into("<H", data, 0x318F80 + 4, 0x001F)
    data[0x318F80 + 0x2000] = 0xF0
    icon = Badges(data, collection.raw).image(0)
    img = Image.open(io.BytesIO(base64.b64decode(icon)))
    assert img.getpixel((0, 0))[3] == 0
    assert img.getpixel((1, 0)) == (255, 0, 0, 255)
    assert img.getpixel((0, 1))[:3] == (0, 0, 255)


def test_bad_size_unknown_reference_and_counter_fail_closed(collection):
    with pytest.raises(ValueError):
        Badges(collection.data[:-1], collection.raw)
    raw = bytearray(collection.raw)
    struct.pack_into("<I", raw, 12, 1)
    with pytest.raises(ValueError, match="count"):
        Badges(collection.data, raw)
    raw[LAYOUT:LAYOUT + 16] = b"x" * 16
    with pytest.raises(ValueError, match="unknown badge"):
        Badges(collection.data, raw)
