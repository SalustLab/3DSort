"""Cache de icones do HOME menu: Cache.dat (indice tid->entrada) e
CacheD.dat (uma entrada de 0x36C0 por titulo — icone E nomes).

Titulos 3DS: entrada SMDH (magic "SMDH"); icone grande 48x48 RGB565, tiles 8x8
em ordem Morton (padrao de textura 3DS). Titulos TWL (DSiWare, ex. TWiLight
Menu++): header SRL @0 + banner NDS @0x378 (validado em dump real) — titulo
UTF-16 por lingua e icone 32x32 4bpp paletado RGB555, indice 0 = transparente.
"""
import base64
import io
import struct

SMDH_ENTRY = 0x36C0
SMDH_LARGE_OFF = 0x24C0
SMDH_LARGE_LEN = 0x1200
TWL_BANNER_OFF = 0x378
TWL_VERSIONS = (0x0001, 0x0002, 0x0003, 0x0103)

# (dx, dy) da z-curve dentro de um tile 8x8
MORTON = [
    ((i & 1) | ((i & 4) >> 1) | ((i & 16) >> 2),
     ((i & 2) >> 1) | ((i & 8) >> 2) | ((i & 32) >> 3))
    for i in range(64)
]


def cache_index(cache: bytes) -> dict[int, int]:
    """Cache.dat -> {titleID: indice no CacheD.dat}. Entradas vazias = tid 0xFF.."""
    out = {}
    for i in range((len(cache) - 8) // 16):
        tid = struct.unpack_from("<Q", cache, 8 + i * 16)[0]
        if tid != 0xFFFFFFFFFFFFFFFF:
            out[tid] = i
    return out


def smdh_entry(cached: bytes, index: int) -> bytes:
    return cached[index * SMDH_ENTRY:(index + 1) * SMDH_ENTRY]


def smdh_short_name(entry: bytes, lang: int = 1) -> str | None:
    """Nome curto do SMDH. lang 1 = ingles (0 = japones)."""
    if entry[:4] != b"SMDH":
        return None
    off = 0x8 + lang * 0x200
    return entry[off:off + 0x80].decode("utf-16-le", "replace").rstrip("\0")


def decode_icon(icon: bytes, size: int = 48):
    from PIL import Image
    img = Image.new("RGB", (size, size))
    px = img.load()
    pos = 0
    for ty in range(0, size, 8):
        for tx in range(0, size, 8):
            for dx, dy in MORTON:
                v = icon[pos] | (icon[pos + 1] << 8)
                pos += 2
                px[tx + dx, ty + dy] = ((v >> 11) << 3, ((v >> 5) & 0x3F) << 2, (v & 0x1F) << 3)
    return img


def icon_png_b64(entry: bytes) -> str | None:
    """SMDH -> PNG base64 do icone 48x48, ou None se a entrada nao for SMDH."""
    if entry[:4] != b"SMDH":
        return None
    img = decode_icon(entry[SMDH_LARGE_OFF:SMDH_LARGE_OFF + SMDH_LARGE_LEN])
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _twl_banner(entry: bytes) -> bytes | None:
    if entry[:4] == b"SMDH" or len(entry) < TWL_BANNER_OFF + 0x840:
        return None
    if struct.unpack_from("<H", entry, TWL_BANNER_OFF)[0] not in TWL_VERSIONS:
        return None
    return entry[TWL_BANNER_OFF:]


def twl_short_name(entry: bytes, lang: int = 1) -> str | None:
    """1a linha do titulo do banner NDS (lang 1 = ingles), ou None se nao-TWL."""
    b = _twl_banner(entry)
    if b is None:
        return None
    t = b[0x240 + lang * 0x100: 0x240 + (lang + 1) * 0x100].decode("utf-16-le", "replace")
    return t.split("\x00")[0].split("\n")[0] or None


def twl_icon_png_b64(entry: bytes) -> str | None:
    """Banner NDS -> PNG base64 do icone (32x32 4bpp -> 48x48), ou None."""
    from PIL import Image
    b = _twl_banner(entry)
    if b is None:
        return None
    icon = b[0x20:0x220]
    pal = struct.unpack("<16H", b[0x220:0x240])
    img = Image.new("RGBA", (32, 32))
    px = img.load()
    k = 0
    for ty in range(0, 32, 8):
        for tx in range(0, 32, 8):
            for y in range(8):
                for x in range(0, 8, 2):
                    byte = icon[k]
                    k += 1
                    for dx, v in ((0, byte & 15), (1, byte >> 4)):
                        if v == 0:
                            px[tx + x + dx, ty + y] = (0, 0, 0, 0)
                        else:
                            c = pal[v]
                            px[tx + x + dx, ty + y] = ((c & 31) * 255 // 31,
                                                       ((c >> 5) & 31) * 255 // 31,
                                                       ((c >> 10) & 31) * 255 // 31, 255)
    buf = io.BytesIO()
    img.resize((48, 48), Image.NEAREST).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()
