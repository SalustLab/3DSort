import struct

from core.icons import (
    SMDH_ENTRY, SMDH_LARGE_OFF, SMDH_LARGE_LEN, TWL_BANNER_OFF,
    cache_index, decode_icon, icon_png_b64, smdh_short_name, MORTON,
    twl_icon_png_b64, twl_short_name,
)


def encode_icon(pixels, size=48):
    """Inverso do decode: pixels[y][x] = (r,g,b) -> bytes RGB565 tiled/Morton."""
    out = bytearray()
    for ty in range(0, size, 8):
        for tx in range(0, size, 8):
            for dx, dy in MORTON:
                r, g, b = pixels[ty + dy][tx + dx]
                v = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
                out += struct.pack("<H", v)
    return bytes(out)


def make_smdh(name="Mario Kart 7", pixels=None):
    e = bytearray(SMDH_ENTRY)
    e[0:4] = b"SMDH"
    for lang in range(16):
        e[0x8 + lang * 0x200: 0x8 + lang * 0x200 + len(name) * 2] = name.encode("utf-16-le")
    if pixels:
        e[SMDH_LARGE_OFF:SMDH_LARGE_OFF + SMDH_LARGE_LEN] = encode_icon(pixels)
    return bytes(e)


def gradient():
    return [[(x * 5 & 0xF8, y * 5 & 0xFC, (x + y) * 2 & 0xF8) for x in range(48)] for y in range(48)]


def test_decode_roundtrip_pixels():
    px = gradient()
    img = decode_icon(make_smdh(pixels=px)[SMDH_LARGE_OFF:SMDH_LARGE_OFF + SMDH_LARGE_LEN])
    assert img.size == (48, 48)
    for x, y in [(0, 0), (47, 0), (0, 47), (47, 47), (13, 29)]:
        assert img.getpixel((x, y)) == px[y][x]


def test_short_name():
    assert smdh_short_name(make_smdh(name="Zelda")) == "Zelda"


def test_cache_index_skips_empty():
    cache = bytearray(8 + 16 * 3)
    cache[0] = 1
    struct.pack_into("<Q", cache, 8, 0x0004000000030800)
    struct.pack_into("<Q", cache, 8 + 16, 0xFFFFFFFFFFFFFFFF)
    struct.pack_into("<Q", cache, 8 + 32, 0x0004000000064D00)
    assert cache_index(bytes(cache)) == {0x0004000000030800: 0, 0x0004000000064D00: 2}


def test_icon_png_b64():
    b64 = icon_png_b64(make_smdh(pixels=gradient()))
    import base64
    assert base64.b64decode(b64)[:8] == b"\x89PNG\r\n\x1a\n"


def test_invalid_smdh_returns_none():
    assert icon_png_b64(b"\x00" * SMDH_ENTRY) is None
    assert smdh_short_name(b"\x00" * SMDH_ENTRY) is None


# ---- entradas TWL (DSiWare, ex. TWiLight Menu++): banner NDS @ 0x378 -------
def encode_twl_icon(pixels):
    """Inverso do decode TWL: pixels[y][x] = indice 0-15 -> 4bpp tiled 8x8."""
    out = bytearray()
    for ty in range(0, 32, 8):
        for tx in range(0, 32, 8):
            for y in range(8):
                for x in range(0, 8, 2):
                    lo = pixels[ty + y][tx + x]
                    hi = pixels[ty + y][tx + x + 1]
                    out.append(lo | (hi << 4))
    return bytes(out)


def make_twl(name="TWiLight Menu++\nRocket Robz", pixels=None, palette=None):
    e = bytearray(SMDH_ENTRY)  # sem magic SMDH
    struct.pack_into("<H", e, TWL_BANNER_OFF, 0x0103)
    if pixels:
        e[TWL_BANNER_OFF + 0x20: TWL_BANNER_OFF + 0x220] = encode_twl_icon(pixels)
    for i, c in enumerate(palette or []):
        struct.pack_into("<H", e, TWL_BANNER_OFF + 0x220 + i * 2, c)
    for lang in range(6):
        off = TWL_BANNER_OFF + 0x240 + lang * 0x100
        e[off: off + len(name) * 2] = name.encode("utf-16-le")
    return bytes(e)


def test_twl_short_name_first_line():
    assert twl_short_name(make_twl()) == "TWiLight Menu++"


def test_twl_icon_decodes_palette_and_transparency():
    # paleta: 1 = vermelho puro RGB555, 2 = verde; indice 0 = transparente
    pixels = [[1 if x < 16 else (0 if y < 16 else 2) for x in range(32)] for y in range(32)]
    b64 = twl_icon_png_b64(make_twl(pixels=pixels, palette=[0, 0x001F, 0x03E0]))
    import base64, io
    from PIL import Image
    img = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGBA")
    assert img.size == (48, 48)
    assert img.getpixel((0, 0)) == (255, 0, 0, 255)      # esquerda: vermelho
    assert img.getpixel((47, 0))[3] == 0                 # dir. superior: transparente
    assert img.getpixel((47, 47)) == (0, 255, 0, 255)    # dir. inferior: verde


def test_twl_rejects_smdh_and_garbage():
    assert twl_short_name(make_smdh()) is None
    assert twl_icon_png_b64(b"\x00" * SMDH_ENTRY) is None
