"""Original synthetic theme assets for parser/browser tests; no Nintendo content."""
import io
from pathlib import Path
import struct
import zipfile

from PIL import Image


def literal_lz(raw):
    return b"\x11" + len(raw).to_bytes(3, "little") + b"".join(
        b"\0" + raw[i:i + 8] for i in range(0, len(raw), 8))


def theme_body(textures=False, frame=1):
    raw = bytearray(0xC4)
    struct.pack_into("<I", raw, 0, 1)
    if textures:
        for screen, draw_off, frame_off, offset in [(0, 0xC, 0x10, 0x18), (1, 0x20, 0x24, 0x28)]:
            struct.pack_into("<I", raw, draw_off, 3)
            struct.pack_into("<I", raw, frame_off, frame)
            struct.pack_into("<I", raw, offset, len(raw))
            width = 512 if frame == 1 else 1024
            # Independent x/y-to-Morton encoder, with asymmetric markers.
            texture = bytearray(width * 256 * 2)
            for y in range(256):
                for x in range(width):
                    value = (0xF800 if x < 20 else 0x07E0) if y < 16 else (0x001F if screen == 0 else 0xFFFF)
                    morton = sum(((x >> b) & 1) << (2 * b) | ((y >> b) & 1) << (2 * b + 1) for b in range(3))
                    index = ((y // 8) * (width // 8) + x // 8) * 64 + morton
                    struct.pack_into("<H", texture, index * 2, value)
            raw.extend(texture)
    return literal_lz(raw)


def metadata(name="Synthetic 星", author="Test author"):
    data = bytearray(0x36C0)
    data[:4] = b"SMDH"
    for off, text in [(0x208, name), (0x288, "Original synthetic test artwork"), (0x388, author)]:
        encoded = text.encode("utf-16-le")
        data[off:off + len(encoded)] = encoded
    return bytes(data)


def make_library(root):
    directory = Path(root) / "Themes"
    directory.mkdir()
    package = directory / "package"
    package.mkdir()
    (package / "body_LZ.bin").write_bytes(theme_body())
    (package / "info.smdh").write_bytes(metadata())
    (package / "bgm.bcstm").write_bytes(b"CSTM" + bytes(32))
    stream = io.BytesIO()
    Image.new("RGB", (400, 480), (12, 90, 180)).save(stream, "PNG")
    (package / "preview.png").write_bytes(stream.getvalue())
    with zipfile.ZipFile(directory / "artwork.zip", "w") as archive:
        archive.writestr("theme/body_LZ.bin", theme_body(True))
        archive.writestr("theme/info.smdh", metadata("Texture artwork", "Texture author"))
    with zipfile.ZipFile(directory / "corrupt.zip", "w") as archive:
        archive.writestr("body_LZ.bin", b"invalid")
    missing = directory / "no-preview"
    missing.mkdir()
    (missing / "body_LZ.bin").write_bytes(theme_body())
    return directory


if __name__ == "__main__":
    # Private mock SD owned by this process; never accepts a physical card path.
    import sys
    from app import build_api, serve
    api = build_api(mock=True, mock_badges=True)
    make_library(api.sd_root)
    serve(api, int(sys.argv[1]))
