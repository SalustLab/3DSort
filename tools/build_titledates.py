"""Builds core/titledates.json.gz: 3DS title ID -> release date ("YYYY-MM-DD"),
plus DS/DSiWare 4-letter game code -> release date.

Sources (fetched live; run with internet access):
  - hax0kartik/3dsdb region JSONs: title ID -> product code (e.g. CTR-N-KGKE)
  - GameTDB 3dstdb.xml: 4-letter game code -> <date year month day>
  - GameTDB dstdb.xml: DS/DSiWare game code -> date (the app reads the code from
    the low half of a TWL tid, which is how DSiWare and NDS forwarders are keyed)

Merge key: the last 4 chars of the product code == GameTDB <id>.
Only base applications (tid high 00040000) are kept on the 3DS side; system
apps have no entry and sort as undated in the app. Rerun any time to refresh.

Usage: python tools/build_titledates.py
Last generated: 2026-09-30.
"""
import argparse
import gzip
import io
import json
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
import unicodedata
from pathlib import Path

DB_REGIONS = ("GB", "JP", "KR", "TW", "US")
DB_URL = "https://hax0kartik.github.io/3dsdb/jsons/list_{}.json"
GAMETDB_URL = "https://www.gametdb.com/3dstdb.zip?LANG=EN"
GAMETDB_DS_URL = "https://www.gametdb.com/dstdb.zip?LANG=EN"
OUT = Path(__file__).resolve().parent.parent / "core" / "titledates.json.gz"
UA = {"User-Agent": "3DSort-titledates-builder/1.0"}


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        return r.read()


def gametdb_dates(url: str = GAMETDB_URL) -> dict:
    """4-letter game code -> ISO date, from a GameTDB xml (3dstdb or dstdb)."""
    raw = fetch(url)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        name = next(n for n in z.namelist() if n.endswith(".xml"))
        root = ET.fromstring(z.read(name))
    dates = {}
    for game in root.iter("game"):
        gid, date = game.findtext("id"), game.find("date")
        if gid is None or date is None:
            continue
        y, m, d = (date.get(k) for k in ("year", "month", "day"))
        if not (y and m and d):
            continue
        code = gid.strip().upper()[:4]
        iso = f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
        # A code can repeat across GameTDB entries; keep the earliest date.
        if code not in dates or iso < dates[code]:
            dates[code] = iso
    return dates


def title_names(sources):
    """Exact IDs only; source order wins, then normalized lexical name."""
    result = {}
    for entries in sources:
        candidates = {}
        for entry in entries:
            tid = entry.get("TitleID", "").strip().lower()
            name = " ".join(unicodedata.normalize("NFC", entry.get("Name", "")).split())
            if len(tid) == 16 and tid.startswith("00040000") and all(c in "0123456789abcdef" for c in tid) and name:
                candidates.setdefault(tid, []).append(name)
        for tid, names in candidates.items():
            result.setdefault(tid, min(names, key=lambda name: (name.lower(), name)))
    return result


def write_names(sources, output=None):
    output = output or OUT.with_name("titlenames.json.gz")
    payload = json.dumps(title_names(sources), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    output.write_bytes(gzip.compress(payload, mtime=0))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--names-only", action="store_true", help="Only rebuild commercial title names")
    parser.add_argument("--source-dir", type=Path, help="Read list_GB.json, list_JP.json, etc. locally (names only)")
    args = parser.parse_args()
    if args.source_dir and not args.names_only:
        parser.error("--source-dir requires --names-only")
    if args.names_only:
        sources = [json.loads((args.source_dir / f"list_{region}.json").read_text(encoding="utf-8"))
                   if args.source_dir else json.loads(fetch(DB_URL.format(region)))
                   for region in DB_REGIONS]
        write_names(sources)
        print(f"Wrote {len(title_names(sources))} exact-ID commercial names")
        return
    dates = gametdb_dates()
    print(f"GameTDB: {len(dates)} game codes with a date")
    table, total = {}, 0
    sources = []
    for region in DB_REGIONS:
        entries = json.loads(fetch(DB_URL.format(region)))
        sources.append(entries)
        n = 0
        for e in entries:
            tid = e.get("TitleID", "").strip().lower()
            code = e.get("Product Code", "").strip().upper()[-4:]
            if len(tid) != 16 or not tid.startswith("00040000"):
                continue
            total += 1
            iso = dates.get(code)
            if iso:
                table[tid] = iso
                n += 1
        print(f"3dsdb {region}: {len(entries)} entries, {n} matched a date")
    print(f"Total: {len(table)} tids dated out of {total} applications")
    write_names(sources)
    ds = gametdb_dates(GAMETDB_DS_URL)
    table.update(ds)
    print(f"GameTDB DS/DSiWare: {len(ds)} game codes with a date")
    payload = json.dumps(table, separators=(",", ":"), sort_keys=True)
    with gzip.open(OUT, "wt", encoding="utf-8", newline="\n") as f:
        f.write(payload)
    print(f"Wrote {OUT} ({OUT.stat().st_size} bytes gz, {len(payload)} raw)")


if __name__ == "__main__":
    main()
