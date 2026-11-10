"""Read-only 3DSBank discovery. Slot metadata never authorizes writes."""
import re
from pathlib import Path


def _plain(path: Path, root: Path) -> bool:
    """Reject links and Windows reparse points, including intermediate paths."""
    try:
        path.relative_to(root)
        for part in (path, *path.parents):
            if part == root.parent:
                break
            st = part.lstat()
            if part.is_symlink() or getattr(st, "st_file_attributes", 0) & 0x400:
                return False
        return path.is_dir()
    except (OSError, ValueError):
        return False


def discover(root: Path) -> dict:
    root = Path(root).absolute()
    bankdir = root / "3DSBank"
    result = {"detected": False, "banks": [], "warnings": []}
    if not _plain(bankdir, root):
        return result
    values = {}
    ini = bankdir / "3DSBank.ini"
    try:
        st = ini.lstat()
        if ini.is_symlink() or getattr(st, "st_file_attributes", 0) & 0x400:
            raise ValueError("Linked configuration")
        if st.st_size > 65536:
            raise ValueError("Oversized configuration")
        section = False
        for line in ini.read_text("utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith((";", "/", "!")):
                continue
            if line.startswith("["):
                section = line == "[3DSBANK]"
                result["detected"] |= section
            elif section and "=" in line:
                key, value = (s.strip() for s in line.split("=", 1))
                if key in values:
                    raise ValueError("Duplicate configuration key")
                values[key] = value
    except (OSError, UnicodeError, ValueError):
        values = {}
        result["warnings"].append("Slot configuration unavailable or ambiguous.")
    try:
        entries = list(bankdir.iterdir())
    except OSError:
        result["warnings"].append("Bank directory cannot be enumerated.")
        return result
    slots = {}
    for entry in entries:
        match = re.fullmatch(r"Slot(0|[1-9][0-9]?)", entry.name)
        if match and int(match[1]) < 40 and _plain(entry, root):
            slots[int(match[1])] = entry
    for number, path in sorted(slots.items()):
        try:
            recognizable = any(re.fullmatch(r"[0-9a-fA-F]{32}", p.name)
                                 and _plain(p, root) for p in path.iterdir())
        except OSError:
            recognizable = False
            result["warnings"].append(f"Slot {number} cannot be enumerated.")
        result["detected"] |= recognizable
        result["banks"].append({"id": f"slot:{number}", "slot": number,
                                "name": values.get(f"SLOT_NAME_{number}") or f"Slot {number}",
                                "root": str(path), "active": False,
                                "editable": False,
                                "restriction": "Inactive bank writes are not validated."})
    active = root / "Nintendo 3DS"
    if result["detected"] and _plain(active, root):
        raw = values.get("FOLDER_SLOT", "")
        number = int(raw) if re.fullmatch(r"0|[1-9][0-9]?", raw) else None
        if number is not None and (number >= 40 or number in slots):
            number = None
        if number is not None:
            result["warnings"].append(
                f"Configuration suggests active slot {number}; directory ownership is unverified.")
        number = None  # INI updates and unchecked renames cannot establish ownership.
        result["banks"].insert(0, {"id": "active", "slot": number,
            "name": (values.get(f"SLOT_NAME_{number}") or f"Slot {number}") + " (active)"
                    if number is not None else "Active bank",
            "root": str(active), "active": True, "editable": False,
            "restriction": "Discovery alone does not validate bank identity for writing."})
    return result
