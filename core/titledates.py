"""Release dates for 3DS titles, from the bundled offline table.

core/titledates.json.gz maps tid (16 hex chars) -> "YYYY-MM-DD". Built once by
tools/build_titledates.py (3dsdb tid->product code + GameTDB product code->date).
Missing file or missing tid -> None; sorting then treats the title as undated.
"""
import gzip
import json
from pathlib import Path

TABLE_PATH = Path(__file__).parent / "titledates.json.gz"
_table = None


def _load() -> dict:
    global _table
    if _table is None:
        try:
            with gzip.open(TABLE_PATH, "rt", encoding="utf-8") as f:
                _table = json.load(f)
        except (OSError, ValueError):
            _table = {}
    return _table


def release_date(tid: int) -> str | None:
    """ISO date ("YYYY-MM-DD") for a title, or None if unknown."""
    return _load().get(f"{tid:016x}")
