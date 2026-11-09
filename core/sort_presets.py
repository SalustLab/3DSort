"""Sorting preset definitions and local, atomic configuration storage."""
import copy
import json
import os
from pathlib import Path
import tempfile
import uuid

FIELDS = ("internal_title", "official_title", "release_date")
BUILTINS = [
    {"id": ident, "name": name, "builtin": True,
     "criteria": [{"field": field, "direction": direction}]}
    for ident, name, field, direction in (
        ("az", "A \u2192 Z", "internal_title", "asc"),
        ("za", "Z \u2192 A", "internal_title", "desc"),
        ("date_asc", "Release date \u2191", "release_date", "asc"),
        ("date_desc", "Release date \u2193", "release_date", "desc"))]


def validate(preset):
    if not isinstance(preset, dict) or set(preset) - {"id", "name", "criteria"}:
        raise ValueError("Invalid preset configuration.")
    name, criteria = preset.get("name"), preset.get("criteria")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise ValueError("Enter a preset name (1-80 characters).")
    if not isinstance(criteria, list) or not 1 <= len(criteria) <= 3:
        raise ValueError("Choose one to three criteria.")
    seen = set()
    for criterion in criteria:
        if (not isinstance(criterion, dict) or set(criterion) != {"field", "direction"}
                or criterion["field"] not in FIELDS
                or criterion["direction"] not in ("asc", "desc")
                or criterion["field"] in seen):
            raise ValueError("Choose distinct criteria and valid directions.")
        seen.add(criterion["field"])
    ident = preset.get("id")
    if ident is not None and (not isinstance(ident, str) or not ident.startswith("custom:")):
        raise ValueError("Built-in presets cannot be modified.")
    return {"id": ident or "custom:" + uuid.uuid4().hex,
            "name": name.strip(), "criteria": copy.deepcopy(criteria)}


class Presets:
    def __init__(self, path):
        self.path = Path(path)
        self.custom = []
        self.warning = None
        self.invalid = False
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1 or not isinstance(data.get("presets"), list):
                raise ValueError("Unsupported preset configuration.")
            custom = [validate(p) for p in data["presets"]]
            ids = [p["id"] for p in custom]
            if any(not p.get("id") for p in data["presets"]) or len(set(ids)) != len(ids):
                raise ValueError("Invalid preset IDs.")
            self.custom = custom
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError):
            self.invalid = True
            self.warning = "Custom presets could not be loaded. Built-in presets remain available."

    def library(self):
        return {"presets": copy.deepcopy(BUILTINS + self.custom), "warning": self.warning}

    def write(self, custom):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.invalid and self.path.exists():
            recovery = self.path.with_name(self.path.name + ".recovery-" + uuid.uuid4().hex)
            recovery.write_bytes(self.path.read_bytes())
        temp = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as f:
                temp = f.name
                json.dump({"version": 1, "presets": custom}, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, self.path)
        finally:
            if temp and os.path.exists(temp):
                os.unlink(temp)
        self.custom, self.warning, self.invalid = custom, None, False
