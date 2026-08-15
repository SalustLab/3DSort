"""Builds core/titledates.json.gz: 3DS title ID -> release date ("YYYY-MM-DD").

Sources (fetched live; run with internet access):
  - hax0kartik/3dsdb region JSONs: title ID -> product code (e.g. CTR-N-KGKE)
  - GameTDB 3dstdb.xml: 4-letter game code -> <date year month day>

Merge key: the last 4 chars of the product code == GameTDB <id>.
Only base applications (tid high 00040000) are kept; DSiWare/system apps have
no entry and sort as undated in the app. Rerun any time to refresh the table.

Usage: python tools/build_titledates.py
Last generated: 2026-08-15.
"""
import gzip
import io
import json
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

DB_REGIONS = ("GB", "JP", "KR", "TW", "US")
DB_URL = "https://hax0kartik.github.io/3dsdb/jsons/list_{}.json"
GAMETDB_URL = "https://www.gametdb.com/3dstdb.zip?LANG=EN"
OUT = Path(__file__).resolve().parent.parent / "core" / "titledates.json.gz"
UA = {"User-Agent": "3DSort-titledates-builder/1.0"}


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        return r.read()


def gametdb_dates() -> dict:
    """4-letter game code -> ISO date, from GameTDB's 3dstdb.xml."""
    raw = fetch(GAMETDB_URL)
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


def main():
    dates = gametdb_dates()
    print(f"GameTDB: {len(dates)} game codes with a date")
    table, total = {}, 0
    for region in DB_REGIONS:
        entries = json.loads(fetch(DB_URL.format(region)))
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
    payload = json.dumps(table, separators=(",", ":"), sort_keys=True)
    with gzip.open(OUT, "wt", encoding="utf-8", newline="\n") as f:
        f.write(payload)
    print(f"Wrote {OUT} ({OUT.stat().st_size} bytes gz, {len(payload)} raw)")


if __name__ == "__main__":
    main()
