"""Staging (undo/redo over state snapshots) and extdata backups."""
import copy
import json
import shutil
import time
import zipfile
from pathlib import Path


class Staging:
    """Immutable snapshots: each commit stores the previous state on the undo stack."""

    def __init__(self, state):
        self.state = state
        self.staged: list[str] = []
        self._undo: list[tuple] = []  # (previous_state, previous_staged)
        self._redo: list[tuple] = []

    def commit(self, label: str, new_state):
        self._undo.append((self.state, list(self.staged)))
        self._redo.clear()
        self.state = copy.deepcopy(new_state)
        self.staged.append(label)

    def undo(self):
        prev_state, prev_staged = self._undo.pop()
        self._redo.append((self.state, list(self.staged)))
        self.state, self.staged = prev_state, prev_staged

    def redo(self):
        nxt_state, nxt_staged = self._redo.pop()
        self._undo.append((self.state, list(self.staged)))
        self.state, self.staged = nxt_state, nxt_staged

    def clear(self):
        """After a successful write: staging cleared, state kept."""
        self.staged.clear()
        self._undo.clear()
        self._redo.clear()


class Backups:
    """Zips of the extracted extdata + history in JSON lines."""

    def __init__(self, root: Path, keep: int = 20):
        self.root = Path(root)
        self.keep = keep
        self.root.mkdir(parents=True, exist_ok=True)
        self._hist = self.root / "history.jsonl"

    def create(self, extdata_dir: Path, kind: str, note: str,
               extra: dict | None = None) -> dict:
        """extra: {arcname: bytes | Path} - files outside the extdata tree
        (e.g. __nand__/Launcher.dat); restore separates them from the SD extract."""
        ts = time.strftime("%Y%m%d-%H%M%S")
        bid = f"{ts}-{len(self.history())}"
        zpath = self.root / f"layout_{bid}.3dsl"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(Path(extdata_dir).rglob("*")):
                if p.is_file():
                    z.write(p, p.relative_to(extdata_dir).as_posix())
                elif p.is_dir():
                    # an empty directory (e.g. boss/) MUST survive the zip:
                    # extdata imported without it makes the HOME rebuild the
                    # whole SaveData (statuses, theme, folders) - Phase 0C
                    z.writestr(p.relative_to(extdata_dir).as_posix() + "/", "")
            for arcname, src in (extra or {}).items():
                if isinstance(src, (bytes, bytearray)):
                    z.writestr(arcname, src)
                else:
                    z.write(src, arcname)
        entry = {"id": bid, "file": zpath.name, "kind": kind, "note": note,
                 "when": time.strftime("%Y-%m-%d %H:%M:%S")}
        with self._hist.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._prune()
        return entry

    def move_root(self, new_root: Path):
        """Changes the backups folder, taking the zips and the history along."""
        new_root = Path(new_root)
        new_root.mkdir(parents=True, exist_ok=True)
        if new_root.resolve() == self.root.resolve():
            return
        for p in list(self.root.glob("*.3dsl")) + [self._hist]:
            if p.exists():
                shutil.move(str(p), str(new_root / p.name))
        self.root = new_root
        self._hist = new_root / "history.jsonl"

    def history(self) -> list[dict]:
        if not self._hist.exists():
            return []
        entries = [json.loads(line) for line in self._hist.read_text("utf-8").splitlines() if line]
        return [e for e in entries if (self.root / e["file"]).exists()]

    def restore(self, backup_id: str, target_dir: Path):
        entry = next(e for e in self.history() if e["id"] == backup_id)
        target = Path(target_dir)
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        with zipfile.ZipFile(self.root / entry["file"]) as z:
            z.extractall(target)

    def _prune(self):
        entries = self.history()
        for e in entries[:-self.keep] if len(entries) > self.keep else []:
            (self.root / e["file"]).unlink(missing_ok=True)
