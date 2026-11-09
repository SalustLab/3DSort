"""Read-only, bounded theme package inspection. No console write operations."""
import base64
import io
import os
from pathlib import Path, PurePosixPath
import stat
import struct
import uuid
import zipfile
import zlib

from PIL import Image

from core.icons import MORTON

BODY_LIMIT = 0x150000
BGM_LIMIT = 0x337000
FILE_LIMIT = 8 * 1024 * 1024
TOTAL_LIMIT = 32 * 1024 * 1024
ENTRY_LIMIT = 128
LIBRARY_LIMIT = 1000
THEME_EXTDATA = {"JPN": "000002cc", "USA": "000002cd",
                 "EUR": "000002ce", "KOR": "000002cf"}
PACKAGE_FILES = {"body_lz.bin", "bgm.bcstm", "info.smdh", "preview.png",
                 "preview.jpg", "preview.jpeg"}


def safe_path(path, root):
    """Reject every redirected component, including Windows junctions."""
    path, root = Path(path), Path(root)
    relative = path.relative_to(root)
    parts = [root, *(root.joinpath(*relative.parts[:i]) for i in range(1, len(relative.parts) + 1))]
    for part in parts:
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Symlink/reparse redirection is not supported")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Path leaves the selected source")
    return path


def read_file(path, root, limit=FILE_LIMIT):
    path = safe_path(path, root)
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError("File is not regular or exceeds the size limit")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("File exceeds the size limit")
    return data


def lz11(data):
    """Nintendo LZ11, bounded before allocation and at each back reference."""
    pos = 0

    def take():
        nonlocal pos
        if pos >= len(data):
            raise ValueError("Truncated LZ11 stream")
        value = data[pos]
        pos += 1
        return value

    if take() != 0x11:
        raise ValueError("Expected LZ11 header")
    size = take() | take() << 8 | take() << 16
    if not size:
        size = take() | take() << 8 | take() << 16 | take() << 24
    if not 0 < size <= BODY_LIMIT:
        raise ValueError("LZ11 output size exceeds the supported limit")
    out = bytearray()
    while len(out) < size:
        flags = take()
        for bit in range(7, -1, -1):
            if len(out) == size:
                break
            if not flags & (1 << bit):
                out.append(take())
                continue
            a, b = take(), take()
            kind = a >> 4
            if kind == 0:
                c = take()
                length = ((a & 15) << 4 | b >> 4) + 0x11
                distance = ((b & 15) << 8 | c) + 1
            elif kind == 1:
                c, d = take(), take()
                length = ((a & 15) << 12 | b << 4 | c >> 4) + 0x111
                distance = ((c & 15) << 8 | d) + 1
            else:
                length = kind + 1
                distance = ((a & 15) << 8 | b) + 1
            if distance > len(out) or len(out) + length > size:
                raise ValueError("Invalid LZ11 back reference")
            for _ in range(length):
                out.append(out[-distance])
    return bytes(out)


def png_url(image):
    stream = io.BytesIO()
    image.save(stream, "PNG")
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")


def preview_image(data):
    with Image.open(io.BytesIO(data)) as image:
        if image.format not in ("PNG", "JPEG"):
            raise ValueError("Only PNG/JPEG previews are supported")
        w, h = image.size
        if not (0 < w <= 4096 and 0 < h <= 4096 and w * h <= 4_000_000):
            raise ValueError("Preview image dimensions exceed the limit")
        image.load()
        image.thumbnail((1008, 960))
        return png_url(image.convert("RGB"))


def smdh(data):
    if len(data) != 0x36C0 or data[:4] != b"SMDH":
        raise ValueError("Invalid SMDH header or size")
    if struct.unpack_from("<H", data, 4)[0] != 0:
        raise ValueError("Unsupported SMDH version")
    for language in [1, 0, *range(2, 16)]:
        off = 8 + language * 0x200
        fields = [data[off + start:off + end].decode("utf-16-le").split("\0")[0]
                  for start, end in [(0, 0x80), (0x80, 0x180), (0x180, 0x200)]]
        if fields[0]:
            return dict(zip(("name", "description", "author"), fields))
    return {}


def rgb565(data, width, height):
    if len(data) != width * height * 2:
        raise ValueError("Truncated RGB565 texture")
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    pos = 0
    for ty in range(0, height, 8):
        for tx in range(0, width, 8):
            for dx, dy in MORTON:
                value = data[pos] | data[pos + 1] << 8
                pos += 2
                r, g, b = value >> 11, value >> 5 & 63, value & 31
                pixels[tx + dx, ty + dy] = (r * 255 // 31, g * 255 // 63, b * 255 // 31)
    return image


def body(data):
    raw = lz11(data)
    if len(raw) < 0xC4:
        raise ValueError("Truncated theme body header")
    u32 = lambda off: struct.unpack_from("<I", raw, off)[0]
    if u32(0) != 1:
        raise ValueError("Unsupported theme body version")

    def block(off, size):
        if off < 0xC4 or off + size > len(raw):
            raise ValueError("Theme data offset is out of bounds")
        return raw[off:off + size]

    # Validate documented enabled references even when the corresponding overlay
    # is not rendered. Unknown bytes are never assigned invented meanings.
    fields = [(0x2C, 0x30, 12), (0x34, 0x38, 12),
              (0x3C, 0x40, 128 * 64 * 3), (0x3C, 0x44, 128 * 64 * 3),
              (0x48, 0x4C, 13), (0x50, 0x54, 64 * 128 * 3),
              (0x50, 0x58, 64 * 128 * 3), (0x5C, 0x60, 13),
              (0x64, 0x68, 9), (0x6C, 0x70, 32), (0x6C, 0x74, 32),
              (0x78, 0x7C, 13), (0x80, 0x84, 13), (0x88, 0x8C, 9),
              (0x90, 0x94, 13), (0x98, 0x9C, 32), (0xA0, 0xA4, 21),
              (0xA8, 0xAC, 12), (0xB0, 0xB4, 6)]
    for flag, offset, size in fields:
        if u32(flag) >= (3 if flag == 0x78 else 2):
            raise ValueError("Invalid theme property flag")
        if u32(flag) == 1:
            block(u32(offset), size)
    if u32(0xB8) > 1:
        raise ValueError("Invalid sound effect flag")
    if u32(0xB8):
        block(u32(0xC0), u32(0xBC))

    result = {"version": 1, "bgmEnabled": bool(raw[5]), "screens": {}, "limitations": []}
    for screen, draw_off, frame_off, texture_off in [("top", 0xC, 0x10, 0x18), ("bottom", 0x20, 0x24, 0x28)]:
        draw, frame = u32(draw_off), u32(frame_off)
        if draw not in (0, 1, 2, 3) or (screen == "bottom" and draw == 2):
            raise ValueError("Invalid screen draw type")
        if draw == 3:
            allowed = (0, 1, 3) if screen == "top" else (0, 1, 2, 3, 4)
            if frame not in allowed:
                result["limitations"].append(f"Unsupported {screen} frame type {frame}")
                continue
            width = 512 if frame == 1 else 1024
            texture = block(u32(texture_off), width * 256 * 2)
            # Expose full artwork, not a guessed viewport/animation position.
            visible = (412 if screen == "top" else 320) if frame == 1 else (960 if frame in (2, 4) else 1008)
            image = rgb565(texture, width, 256).crop((0, 0, visible, 240))
            result["screens"][screen] = png_url(image)
        elif draw in (1, 2):
            if screen == "top":
                block(u32(0x14), 5 if draw == 1 else 7)
                if draw == 2:
                    block(u32(0x18), 64 * 64)
                    if u32(0x1C):
                        block(u32(0x1C), 64 * 64)
            result["limitations"].append(f"{screen.capitalize()} color/effect rendering is unsupported")
    result["limitations"].append("Background artwork only; no HOME overlays, stereoscopy, animation or scroll simulation. Not a console screenshot.")
    return result


def package_files(path, root):
    """Read only allowlisted package members, never extract archives."""
    safe_path(path, root)
    if path.is_dir():
        files = {}
        with os.scandir(path) as entries:
            for i, entry in enumerate(entries):
                if i >= ENTRY_LIMIT:
                    raise ValueError("Too many package entries")
                if entry.name.lower() in PACKAGE_FILES:
                    key = entry.name.lower()
                    if key in files:
                        raise ValueError("Ambiguous duplicate package files")
                    files[key] = read_file(Path(entry.path), root)
        if sum(map(len, files.values())) > TOTAL_LIMIT:
            raise ValueError("Package exceeds total size limit")
        return files
    if path.stat().st_size > TOTAL_LIMIT:
        raise ValueError("Archive exceeds size limit")
    # Bound the central directory before ZipFile allocates a ZipInfo per entry.
    # ZIP64 is unnecessary for these small theme packages and is unsupported.
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - 65557))
        tail = stream.read(65557)
    eocd = tail.rfind(b"PK\x05\x06")
    if eocd < 0 or len(tail) - eocd < 22:
        raise ValueError("Invalid ZIP directory")
    if eocd >= 20 and tail[eocd - 20:eocd - 16] == b"PK\x06\x07":
        raise ValueError("ZIP64 theme packages are unsupported")
    disk, directory_disk, disk_count, count, directory_size = struct.unpack_from("<4HI", tail, eocd + 4)
    if disk or directory_disk or disk_count != count or count > ENTRY_LIMIT or directory_size > ENTRY_LIMIT * 1024:
        raise ValueError("Too many archive entries or unsupported ZIP directory")
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > ENTRY_LIMIT:
            raise ValueError("Too many archive entries")
        total, files, names = 0, {}, set()
        for entry in entries:
            name = entry.orig_filename
            parts = PurePosixPath(name).parts
            mode = entry.external_attr >> 16
            if (not parts or len(name) > 1024 or "\0" in name or name.startswith(("/", "\\")) or "\\" in name or ":" in name
                    or any(p in ("..", ".") for p in name.split("/"))
                    or entry.external_attr & 0x400 or stat.S_ISLNK(mode)
                    or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))):
                raise ValueError("Unsafe archive path or redirected entry")
            if entry.flag_bits & 1:
                raise ValueError("Encrypted ZIP packages are unsupported")
            total += entry.file_size
            if (entry.file_size > FILE_LIMIT or total > TOTAL_LIMIT
                    or entry.file_size > max(1, entry.compress_size) * 200):
                raise ValueError("Archive size or compression ratio exceeds limit")
            key = name.lower().rstrip("/")
            if key in names:
                raise ValueError("Duplicate archive member")
            names.add(key)
            if not entry.is_dir() and parts[-1].lower() in PACKAGE_FILES:
                files[key] = entry
        bodies = [k for k in files if PurePosixPath(k).name == "body_lz.bin"]
        if len(bodies) != 1:
            raise ValueError("Expected one body_LZ.bin in the archive")
        parent = PurePosixPath(bodies[0]).parent
        return {PurePosixPath(k).name: archive.read(v) for k, v in files.items()
                if PurePosixPath(k).parent == parent}


class Library:
    """Per-selected-root opaque IDs; parsing is lazy with a bounded result cache."""
    def __init__(self, root):
        self.root = Path(root) if root is not None else None
        self.paths = {}
        self.cache = {}

    def discover(self):
        self.paths.clear()
        self.cache.clear()
        result = {"themes": [], "message": "", "current": {"status": "unknown", "message": "Current theme identity is unknown. Cache content is not proof of the active theme."}}
        if self.root is None:
            result["message"] = "No SD detected"
            return result
        directory = self.root / "Themes"
        try:
            safe_path(directory, self.root)
            with os.scandir(directory) as entries:
                for entry in entries:
                    if len(self.paths) >= LIBRARY_LIMIT:
                        result["message"] = "Library limited to 1000 packages"
                        break
                    path = Path(entry.path)
                    is_directory = entry.is_dir(follow_symlinks=False)
                    if is_directory or path.suffix.lower() == ".zip":
                        ident = uuid.uuid4().hex
                        self.paths[ident] = (path, is_directory)
                        result["themes"].append({"id": ident, "name": path.name if is_directory else path.stem,
                                                  "source": "Directory package" if is_directory else "ZIP package"})
            if not result["themes"]:
                result["message"] = "No themes found in SD:/Themes/"
        except FileNotFoundError:
            result["message"] = "SD:/Themes/ is missing"
        except (OSError, ValueError):
            result["message"] = "Theme directory is unavailable or redirected"
        return result

    def detail(self, ident, full=True):
        if not isinstance(ident, str) or ident not in self.paths:
            raise ValueError("Unknown theme ID; refresh the library")
        if ident in self.cache:
            return self._view(self.cache[ident], full)
        path, is_directory = self.paths[ident]
        result = {"id": ident, "name": path.name if is_directory else path.stem,
                  "source": "Directory package" if is_directory else "ZIP package",
                  "author": "", "status": "unsupported", "bgm": None, "preview": None, "previewSource": None,
                  "screens": {}, "limitations": [], "files": []}
        try:
            files = package_files(path, self.root)
            result["files"] = [{"name": k, "size": len(v)} for k, v in files.items()]
            result["bgm"] = bool(files.get("bgm.bcstm"))
            if "info.smdh" in files:
                try:
                    result.update(smdh(files["info.smdh"]))
                except (ValueError, UnicodeError) as exc:
                    result["limitations"].append(str(exc))
            for name in ("preview.png", "preview.jpg", "preview.jpeg"):
                if name in files:
                    try:
                        result["preview"] = preview_image(files[name])
                        result["previewSource"] = "package"
                        result["limitations"].append("Package-supplied preview; accuracy is not verified against the body.")
                        break
                    except (OSError, ValueError, Image.DecompressionBombError) as exc:
                        result["limitations"].append(f"Invalid preview: {exc}")
            if "body_lz.bin" not in files:
                raise ValueError("Missing body_LZ.bin")
            parsed = body(files["body_lz.bin"])
            result.update({k: v for k, v in parsed.items() if k != "limitations"})
            result["limitations"].extend(parsed["limitations"])
            result["status"] = "supported" if parsed["screens"] else "partial"
            if not result["preview"]:
                result["preview"] = parsed["screens"].get("top") or parsed["screens"].get("bottom")
                if result["preview"]:
                    result["previewSource"] = "body"
        except (OSError, ValueError, NotImplementedError, RuntimeError, EOFError,
                SyntaxError, zipfile.BadZipFile, zlib.error) as exc:
            result["limitations"].append(str(exc))
        if len(self.cache) >= 24:
            self.cache.pop(next(iter(self.cache)))
        self.cache[ident] = result
        return self._view(result, full)

    @staticmethod
    def _view(result, full):
        if full:
            return result
        summary = {k: v for k, v in result.items() if k not in ("screens", "preview")}
        summary["preview"] = None
        if result["preview"]:
            with Image.open(io.BytesIO(base64.b64decode(result["preview"].split(",", 1)[1]))) as image:
                image.thumbnail((200, 160))
                summary["preview"] = png_url(image)
        return summary


def cache_info(read):
    """read(name, limit) is scoped to the selected console's decrypted archive."""
    manage = read("ThemeManage.bin", 0x800)
    if len(manage) != 0x800:
        raise ValueError("Invalid ThemeManage.bin size")
    body_size, bgm_size = struct.unpack_from("<II", manage, 8)
    sizes = struct.unpack_from("<20I", manage, 0x338)
    if body_size > BODY_LIMIT or bgm_size > BGM_LIMIT or any(x > BODY_LIMIT for x in sizes[:10]) or any(x > BGM_LIMIT for x in sizes[10:]):
        raise ValueError("Invalid theme cache payload lengths")
    result = {"status": "unknown", "message": "Cached content only; current theme identity remains unknown.",
              "bodySize": body_size, "bgmSize": bgm_size,
              "shuffleSlots": sum(bool(x) for x in sizes[:10]), "screens": {}}
    if body_size:
        raw = read("BodyCache.bin", BODY_LIMIT)
        if len(raw) < body_size:
            raise ValueError("Truncated BodyCache.bin")
        parsed = body(raw[:body_size])
        result["screens"] = parsed["screens"]
        result["limitations"] = parsed["limitations"]
    if bgm_size and len(read("BgmCache.bin", BGM_LIMIT)) < bgm_size:
        raise ValueError("Truncated BgmCache.bin")
    return result
