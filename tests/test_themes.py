import base64
import copy
import io
import os
from pathlib import Path
import stat
import struct
import zipfile

from PIL import Image
import pytest

from app import build_api
from core import themes
from core.savedata import OFF_THEMES, SIZES, SaveData
from tools.theme_fixtures import literal_lz, make_library, metadata, theme_body


def image(url):
    return Image.open(io.BytesIO(base64.b64decode(url.split(",")[1])))


def test_empty_sources(tmp_path):
    assert themes.Library(None).discover()["message"] == "No SD detected"
    assert "missing" in themes.Library(tmp_path).discover()["message"]
    (tmp_path / "Themes").mkdir()
    assert "No themes found" in themes.Library(tmp_path).discover()["message"]
    (tmp_path / "Themes" / "unrelated.txt").write_text("ignore")
    assert not themes.Library(tmp_path).discover()["themes"]


def test_packages_metadata_previews_and_ids(tmp_path):
    make_library(tmp_path)
    library = themes.Library(tmp_path)
    listing = library.discover()
    assert len(listing["themes"]) == 4
    assert listing["current"]["status"] == "unknown"
    details = {t["name"]: library.detail(t["id"]) for t in listing["themes"]}
    assert details["package"]["name"] == "Synthetic 星"
    assert details["package"]["author"] == "Test author"
    assert details["package"]["bgm"]
    assert image(details["package"]["preview"]).getpixel((0, 0)) == (12, 90, 180)
    assert details["artwork"]["status"] == "supported"
    assert not details["no-preview"]["preview"]
    assert not details["no-preview"]["bgm"]
    assert details["corrupt"]["status"] == "unsupported"
    assert "LZ11" in " ".join(details["corrupt"]["limitations"])
    for bad in ("../package", str(tmp_path), "package", None, []):
        with pytest.raises(ValueError):
            library.detail(bad)
    ident = listing["themes"][0]["id"]
    library.discover()
    with pytest.raises(ValueError):
        library.detail(ident)


def test_duplicate_names_and_metadata_fallback(tmp_path):
    directory = tmp_path / "Themes"
    directory.mkdir()
    for name in ("one", "two"):
        package = directory / name
        package.mkdir()
        (package / "body_LZ.bin").write_bytes(theme_body())
        (package / "info.smdh").write_bytes(metadata("Same name"))
    library = themes.Library(tmp_path)
    entries = library.discover()["themes"]
    assert entries[0]["id"] != entries[1]["id"]
    assert [library.detail(t["id"])["name"] for t in entries] == ["Same name"] * 2
    (directory / "one" / "info.smdh").write_bytes(b"bad")
    entries = library.discover()["themes"]
    result = next(library.detail(t["id"]) for t in entries if t["name"] == "one")
    assert result["name"] == "one" and "SMDH" in " ".join(result["limitations"])


@pytest.mark.parametrize("frame,top_width,bottom_width", [(1, 412, 320), (0, 1008, 1008), (2, None, 960), (3, 1008, 1008), (4, None, 960)])
def test_texture_orientation_color_and_dimensions(frame, top_width, bottom_width):
    parsed = themes.body(theme_body(True, frame))
    for screen, width in (("top", top_width), ("bottom", bottom_width)):
        if width is None:
            assert screen not in parsed["screens"]
            continue
        decoded = image(parsed["screens"][screen])
        assert decoded.size == (width, 240)
        assert decoded.getpixel((0, 0)) == (255, 0, 0)
        assert decoded.getpixel((21, 0)) == (0, 255, 0)
        assert decoded.getpixel((0, 17)) == ((0, 0, 255) if screen == "top" else (255, 255, 255))


@pytest.mark.parametrize("data", [b"", b"\x10\x01\0\0", b"\x11\0\0\0", b"\x11\x01\0\0\0", b"\x11\x03\0\0\x80\x20\0", b"\x11\x02\0\0\x40A\x20\0", b"\x11" + (themes.BODY_LIMIT + 1).to_bytes(3, "little")])
def test_lz11_rejects_boundaries(data):
    with pytest.raises(ValueError):
        themes.lz11(data)


@pytest.mark.parametrize("length,encoded", [(3, b"\x20\0"), (17, b"\x00\0\0"), (273, b"\x10\0\0\0")])
def test_lz11_back_reference_forms(length, encoded):
    data = b"\x11" + (length + 1).to_bytes(3, "little") + b"\x40A" + encoded
    assert themes.lz11(data) == b"A" * (length + 1)
    assert themes.lz11(b"\x11\0\0\0\x01\0\0\0\0Z") == b"Z"


@pytest.mark.parametrize("offset,value", [(0, 2), (0xC, 7), (0x20, 2), (0x2C, 2), (0x2C, 1)])
def test_invalid_theme_header_and_properties(offset, value):
    raw = bytearray(0xC4)
    struct.pack_into("<I", raw, 0, 1)
    struct.pack_into("<I", raw, offset, value)
    with pytest.raises(ValueError):
        themes.body(literal_lz(raw))


def test_truncated_texture_and_invalid_offset():
    raw = bytearray(0xC4)
    struct.pack_into("<I", raw, 0, 1)
    struct.pack_into("<I", raw, 0xC, 3)
    struct.pack_into("<I", raw, 0x10, 1)
    for off in (0, 0xC4, 0xFFFFFFFF):
        struct.pack_into("<I", raw, 0x18, off)
        with pytest.raises(ValueError, match="bounds"):
            themes.body(literal_lz(raw))
    with pytest.raises(ValueError, match="Truncated"):
        themes.body(literal_lz(b"\x01\0\0\0"))


def test_smdh_versions_languages_unicode():
    assert themes.smdh(metadata())["name"] == "Synthetic 星"
    data = bytearray(metadata())
    data[4] = 1
    with pytest.raises(ValueError, match="version"):
        themes.smdh(data)
    data = bytearray(metadata())
    data[0x208:0x288] = bytes(0x80)
    data[8:12] = "日本".encode("utf-16-le")
    assert themes.smdh(data)["name"] == "日本"
    with pytest.raises(ValueError):
        themes.smdh(data[:-1])


@pytest.mark.parametrize("name", ["../body_LZ.bin", "/body_LZ.bin", "C:/body_LZ.bin", "a\\body_LZ.bin", "a/../body_LZ.bin", "./body_LZ.bin"])
def test_zip_path_rejection(tmp_path, name):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(name, b"x")
    if "\\" in name:
        # ZipInfo normalizes Windows separators when producing archives; patch
        # both headers to model hostile input from another ZIP producer.
        archive.write_bytes(archive.read_bytes().replace(b"a/body_LZ.bin", b"a\\body_LZ.bin"))
    with pytest.raises(ValueError, match="Unsafe"):
        themes.package_files(archive, tmp_path)


def test_zip_symlink_count_ratio_and_size(tmp_path, monkeypatch):
    archive = tmp_path / "bad.zip"
    entry = zipfile.ZipInfo("body_LZ.bin")
    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(entry, "target")
    with pytest.raises(ValueError, match="Unsafe"):
        themes.package_files(archive, tmp_path)
    with zipfile.ZipFile(archive, "w") as z:
        for i in range(themes.ENTRY_LIMIT + 1):
            z.writestr(str(i), b"")
    with pytest.raises(ValueError, match="entries"):
        themes.package_files(archive, tmp_path)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("body_LZ.bin", bytes(100_000))
    with pytest.raises(ValueError, match="ratio"):
        themes.package_files(archive, tmp_path)
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("body_LZ.bin", bytes(100))
    monkeypatch.setattr(themes, "FILE_LIMIT", 10)
    with pytest.raises(ValueError, match="size"):
        themes.package_files(archive, tmp_path)


def test_image_bounds_and_bad_images():
    stream = io.BytesIO()
    Image.new("RGB", (4097, 1)).save(stream, "PNG")
    with pytest.raises(ValueError, match="dimensions"):
        themes.preview_image(stream.getvalue())
    with pytest.raises(OSError):
        themes.preview_image(b"not an image")


def test_redirects_and_filesystem_errors(tmp_path, monkeypatch):
    directory = tmp_path / "Themes"
    directory.mkdir()
    target = tmp_path / "elsewhere"
    target.mkdir()
    try:
        (directory / "redirect.zip").symlink_to(target, target_is_directory=True)
    except OSError:
        # Windows may require developer mode for symlinks; exercise reparse bit.
        real = Path.lstat
        def redirected(path):
            if path == directory:
                return type("Info", (), {"st_mode": stat.S_IFDIR, "st_file_attributes": 0x400})()
            return real(path)
        monkeypatch.setattr(Path, "lstat", redirected)
        assert "redirected" in themes.Library(tmp_path).discover()["message"]
    else:
        library = themes.Library(tmp_path)
        entry = library.discover()["themes"][0]
        assert library.detail(entry["id"])["status"] == "unsupported"
    monkeypatch.setattr(os, "scandir", lambda *a: (_ for _ in ()).throw(PermissionError("denied")))
    assert "unavailable" in themes.Library(tmp_path).discover()["message"]


def test_cache_is_separate_and_unknown():
    manage = bytearray(0x800)
    content = theme_body(True)
    struct.pack_into("<I", manage, 8, len(content))
    struct.pack_into("<I", manage, 0x338, 100)
    files = {"ThemeManage.bin": manage, "BodyCache.bin": content}
    result = themes.cache_info(lambda name, limit: files[name])
    assert result["status"] == "unknown" and result["shuffleSlots"] == 1
    assert result["screens"]["top"]
    for data in (b"bad", bytes(0x801)):
        with pytest.raises(ValueError):
            themes.cache_info(lambda name, limit: data)
    struct.pack_into("<I", manage, 8, themes.BODY_LIMIT + 1)
    with pytest.raises(ValueError, match="lengths"):
        themes.cache_info(lambda name, limit: manage)


@pytest.mark.parametrize("size", SIZES)
def test_browsing_preserves_save_staging_and_fresh_graft(size):
    api = build_api(mock=True)
    api.get_state()
    source = api.workdir / "extract" / "user" / "SaveData.dat"
    raw = source.read_bytes()[:size]
    source.write_bytes(raw)
    make_library(api.sd_root)
    before = copy.deepcopy(api.staging.__dict__)
    files_before = {p.relative_to(api.sd_root): p.read_bytes() for p in api.sd_root.rglob("*") if p.is_file()}
    for entry in api.list_themes()["themes"]:
        api.get_theme(entry["id"])
        api.get_theme(entry["id"], True)
    assert api.get_theme_cache()["status"] == "unknown"
    assert api.staging.__dict__ == before and source.read_bytes() == raw
    assert files_before == {p.relative_to(api.sd_root): p.read_bytes() for p in api.sd_root.rglob("*") if p.is_file()}
    save = SaveData(raw)
    assert save.serialize() == raw
    fresh = raw[:OFF_THEMES] + b"\xA7" * (size - OFF_THEMES)
    save.graft_tail(fresh)
    assert save.serialize() == fresh
    assert api.list_sort_presets()["presets"]


def test_api_cache_scoped_extraction(tmp_path, monkeypatch):
    api = build_api(mock=True)
    assert api.get_theme_cache()["status"] == "unknown"
    api.get_state()
    parent = api.console.extdata_dir.parent
    (parent / "000002cd").mkdir()
    calls = []
    def extract(eid, root, out):
        calls.append((eid, root))
        user = out / "user"
        user.mkdir()
        (user / "ThemeManage.bin").write_bytes(bytes(0x800))
    monkeypatch.setattr(api.save3ds, "extract", extract)
    monkeypatch.setattr(api.save3ds, "import_", lambda *a: pytest.fail("read-only"))
    result = api.get_theme_cache()
    assert result["extdataId"] == "000002cd" and result["bodySize"] == 0
    assert calls == [("00000000000002cd", api.sd_root)]
    assert result["status"] == "unknown"


def test_readonly_helper_and_bridge_signature(tmp_path, monkeypatch):
    import inspect
    from core.sdcard import Save3ds
    api = build_api(mock=True)
    assert list(inspect.signature(api.get_theme).parameters) == ["ident", "full"]
    with pytest.raises(ValueError):
        api.get_theme("anything")
    helper = Save3ds(tmp_path / "helper", tmp_path / "boot", tmp_path / "movable")
    for path in (helper.exe, helper.boot9, helper.movable):
        path.write_bytes(b"synthetic")
    calls = []
    def run(cmd, **kwargs):
        calls.append(cmd)
        return type("Result", (), {"returncode": 0})()
    monkeypatch.setattr("core.sdcard.subprocess.run", run)
    helper.extract_readonly("00000000000002cd", tmp_path, tmp_path / "out")
    assert "--readonly" in calls[0] and "--extract" in calls[0]
    assert "--import" not in calls[0]


def test_archive_total_size_and_ambiguous_members(tmp_path, monkeypatch):
    archive = tmp_path / "test.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("body_LZ.bin", b"a" * 80)
        z.writestr("bgm.bcstm", b"b" * 80)
    # Keep compressed file smaller than total cap while exercising inflated sum.
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("body_LZ.bin", b"a" * 300)
        z.writestr("bgm.bcstm", b"b" * 300)
    monkeypatch.setattr(themes, "TOTAL_LIMIT", 500)
    with pytest.raises(ValueError, match="size"):
        themes.package_files(archive, tmp_path)
    monkeypatch.setattr(themes, "TOTAL_LIMIT", 32 * 1024 * 1024)
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("one/body_LZ.bin", theme_body())
        z.writestr("two/body_LZ.bin", theme_body())
    with pytest.raises(ValueError, match="one body"):
        themes.package_files(archive, tmp_path)


def test_bad_preview_falls_back_and_deleted_package_isolated(tmp_path):
    make_library(tmp_path)
    package = tmp_path / "Themes" / "package"
    (package / "preview.png").write_bytes(b"bad PNG")
    (package / "body_LZ.bin").write_bytes(theme_body(True))
    library = themes.Library(tmp_path)
    entries = library.discover()["themes"]
    entry = next(t for t in entries if t["name"] == "package")
    result = library.detail(entry["id"])
    assert result["preview"] == result["screens"]["top"]
    assert "Invalid preview" in " ".join(result["limitations"])
    small = library.detail(entry["id"], False)
    assert "screens" not in small and image(small["preview"]).width <= 200
    removed = next(t for t in entries if t["name"] == "artwork")
    (tmp_path / "Themes" / "artwork.zip").unlink()
    assert library.detail(removed["id"])["status"] == "unsupported"
    assert library.detail(entry["id"])["name"] == "Synthetic 星"


def test_cache_truncated_body_bgm_and_unknown_regions():
    manage = bytearray(0x800)
    struct.pack_into("<I", manage, 8, 200)
    with pytest.raises(ValueError, match="Truncated Body"):
        themes.cache_info(lambda name, limit: manage if name == "ThemeManage.bin" else b"x")
    struct.pack_into("<II", manage, 8, 0, 200)
    with pytest.raises(ValueError, match="Truncated Bgm"):
        themes.cache_info(lambda name, limit: manage if name == "ThemeManage.bin" else b"x")
    api = build_api(mock=True)
    api.get_state()
    api.console.region = "TWN"
    assert "unsupported" in api.get_theme_cache()["message"]
