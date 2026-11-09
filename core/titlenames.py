"""Exact Title ID commercial names from the bundled 3dsdb catalog."""
import gzip
import json
from pathlib import Path

TABLE_PATH = Path(__file__).with_name("titlenames.json.gz")
_table = None


def official_title(tid):
    global _table
    if _table is None:
        try:
            with gzip.open(TABLE_PATH, "rt", encoding="utf-8") as f:
                data = json.load(f)
            _table = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            _table = {}
    value = _table.get(f"{tid:016x}")
    return value if isinstance(value, str) and value.strip() else None
