# Phase 1 spike: viability proof of the round-trip on the sandbox SD.
# NEVER touches the real SD (G:) - operates only on sandbox/.
# Usage: python spike.py
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
SANDBOX = ROOT / "sandbox"
SD_ROOT = SANDBOX / "sd"
KEYS = SANDBOX / "keys"
BOOT9 = KEYS / "boot9.bin"
MOVABLE = KEYS / "movable.sed"
ESSENTIAL = KEYS / "essential.exefs"
EXTRACT = SANDBOX / "extract"
VERIFY = SANDBOX / "verify"
OUT_ICONS = SANDBOX / "icons"
SAVE3DS = ROOT / "tools" / "save3ds" / "save3ds_fuse.exe"
EXTDATA_ID = "000000000000008f"  # HOME menu, console USA


def step(msg):
    print(f"\n=== {msg}")


def extract_movable():
    if MOVABLE.exists():
        print(f"movable.sed already exists ({MOVABLE.stat().st_size} bytes)")
        return
    from pyctr.type.exefs import ExeFSReader
    with ExeFSReader(ESSENTIAL) as e:
        names = list(e.entries)
        print("entries in essential.exefs:", names)
        with e.open("movable") as f:
            MOVABLE.write_bytes(f.read())
    print(f"movable.sed extracted ({MOVABLE.stat().st_size} bytes)")


def run_save3ds(mode, target_dir):
    target_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(SAVE3DS), "--sdext", EXTDATA_ID,
        "--sd", str(SD_ROOT),
        "--boot9", str(BOOT9),
        "--movable", str(MOVABLE),
        mode, str(target_dir),
    ]
    print(">", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout)
    if r.returncode != 0:
        print(r.stderr)
        sys.exit(f"save3ds failed (exit {r.returncode})")


def parse_savedata(data):
    version = data[0]
    title_ids = struct.unpack_from("<360Q", data, 0x8)
    status = struct.unpack_from("<360b", data, 0xB48)
    positions = struct.unpack_from("<360h", data, 0xCB0)
    folders = struct.unpack_from("<360b", data, 0xF80)
    slots = [
        {"slot": i, "tid": title_ids[i], "pos": positions[i], "folder": folders[i]}
        for i in range(360)
        if status[i] == 1
    ]
    return version, slots


SMDH_LARGE_OFF = 0x24C0
SMDH_LARGE_LEN = 0x1200
SMDH_ENTRY = 0x36C0
# Morton order (z-curve) inside each 8x8 tile, 3DS texture pattern
_MORTON = [
    (((i & 1) | ((i & 4) >> 1) | ((i & 16) >> 2)),
     (((i & 2) >> 1) | ((i & 8) >> 2) | ((i & 32) >> 3)))
    for i in range(64)
]


def decode_icon_rgb565(icon, size=48):
    from PIL import Image
    img = Image.new("RGB", (size, size))
    px = img.load()
    pos = 0
    for ty in range(0, size, 8):
        for tx in range(0, size, 8):
            for dx, dy in _MORTON:
                v = icon[pos] | (icon[pos + 1] << 8)
                pos += 2
                px[tx + dx, ty + dy] = (
                    (v >> 11) << 3, ((v >> 5) & 0x3F) << 2, (v & 0x1F) << 3)
    return img


def smdh_name(entry, lang=1):  # 1 = English
    off = 0x8 + lang * 0x200
    return entry[off:off + 0x80].decode("utf-16-le").rstrip("\0")


def main():
    step("0. movable.sed")
    extract_movable()

    step("1. boot9.bin")
    if not BOOT9.exists():
        print(f"MISSING {BOOT9}")
        print("Dump it on the console via GodMode9 (see instructions in chat) and copy it to this folder.")
        sys.exit(1)
    print(f"boot9.bin ok ({BOOT9.stat().st_size} bytes)")

    step("2. extdata extract (sandbox)")
    if EXTRACT.exists():
        shutil.rmtree(EXTRACT)
    run_save3ds("--extract", EXTRACT)
    for p in sorted(EXTRACT.rglob("*")):
        if p.is_file():
            print(f"  {p.relative_to(EXTRACT)}  {p.stat().st_size}")

    step("3. parse SaveData.dat")
    sav_path = EXTRACT / "user" / "SaveData.dat"
    data = bytearray(sav_path.read_bytes())
    version, slots = parse_savedata(data)
    print(f"version={version}, {len(slots)} active icons")
    cache = (EXTRACT / "user" / "Cache.dat").read_bytes()
    cached = (EXTRACT / "user" / "CacheD.dat").read_bytes()
    cache_tids = {}
    for i in range((len(cache) - 8) // 16):
        tid = struct.unpack_from("<Q", cache, 8 + i * 16)[0]
        if tid != 0xFFFFFFFFFFFFFFFF:
            cache_tids[tid] = i
    names = {}
    for tid, idx in cache_tids.items():
        entry = cached[idx * SMDH_ENTRY:(idx + 1) * SMDH_ENTRY]
        if entry[:4] == b"SMDH":
            names[tid] = smdh_name(entry)
    for s in sorted(slots, key=lambda s: s["pos"])[:20]:
        n = names.get(s["tid"], "?")
        print(f"  pos={s['pos']:3d} folder={s['folder']:3d} tid={s['tid']:016x} {n}")
    print(f"  ... ({len(slots)} total, {len(names)} names in cache)")

    step("4. decode 3 real icons")
    OUT_ICONS.mkdir(exist_ok=True)
    done = 0
    for tid, idx in cache_tids.items():
        entry = cached[idx * SMDH_ENTRY:(idx + 1) * SMDH_ENTRY]
        if entry[:4] != b"SMDH":
            continue
        img = decode_icon_rgb565(entry[SMDH_LARGE_OFF:SMDH_LARGE_OFF + SMDH_LARGE_LEN])
        safe = "".join(c for c in names.get(tid, f"{tid:016x}") if c.isalnum() or c in " -_")[:40]
        img.save(OUT_ICONS / f"{safe}.png")
        print(f"  {OUT_ICONS / (safe + '.png')}")
        done += 1
        if done == 3:
            break
    assert done == 3, "fewer than 3 valid SMDH entries in the cache"

    step("5. swap 2 positions in SaveData.dat")
    a, b = sorted(slots, key=lambda s: s["pos"])[:2]
    print(f"  swapping '{names.get(a['tid'], a['tid'])}' (pos {a['pos']}) <-> '{names.get(b['tid'], b['tid'])}' (pos {b['pos']})")
    struct.pack_into("<h", data, 0xCB0 + a["slot"] * 2, b["pos"])
    struct.pack_into("<h", data, 0xCB0 + b["slot"] * 2, a["pos"])
    sav_path.write_bytes(data)

    step("6. import back into the sandbox")
    run_save3ds("--import", EXTRACT)

    step("7. re-extract and verification")
    if VERIFY.exists():
        shutil.rmtree(VERIFY)
    run_save3ds("--extract", VERIFY)
    ok = True
    for p in sorted(EXTRACT.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(EXTRACT)
        q = VERIFY / rel
        same = q.exists() and q.read_bytes() == p.read_bytes()
        print(f"  {rel}: {'SAME' if same else 'DIFFERENT'}")
        ok = ok and same
    v2, slots2 = parse_savedata((VERIFY / "user" / "SaveData.dat").read_bytes())
    pos2 = {s["tid"]: s["pos"] for s in slots2}
    assert pos2[a["tid"]] == b["pos"] and pos2[b["tid"]] == a["pos"], "swap did not persist"
    assert {s["tid"] for s in slots2} == {s["tid"] for s in slots}, "titles lost"
    assert ok, "round-trip diverged"
    print("\nSPIKE OK: full round-trip, swap persisted, no title lost.")


if __name__ == "__main__":
    main()
