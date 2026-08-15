"""Staging (undo/redo sobre snapshots de estado) e backups do extdata."""
import copy
import json
import shutil
import time
import zipfile
from pathlib import Path


class Staging:
    """Snapshots imutaveis: cada commit guarda o estado anterior no undo stack."""

    def __init__(self, state):
        self.state = state
        self.staged: list[str] = []
        self._undo: list[tuple] = []  # (estado_anterior, staged_anterior)
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
        """Depois de um write bem-sucedido: staging zerado, estado mantido."""
        self.staged.clear()
        self._undo.clear()
        self._redo.clear()


class Backups:
    """Zips do extdata extraido + historico em JSON lines."""

    def __init__(self, root: Path, keep: int = 20):
        self.root = Path(root)
        self.keep = keep
        self.root.mkdir(parents=True, exist_ok=True)
        self._hist = self.root / "history.jsonl"

    def create(self, extdata_dir: Path, kind: str, note: str,
               extra: dict | None = None) -> dict:
        """extra: {arcname: bytes | Path} — arquivos fora da arvore de extdata
        (ex.: __nand__/Launcher.dat); o restore os separa do extract do SD."""
        ts = time.strftime("%Y%m%d-%H%M%S")
        bid = f"{ts}-{len(self.history())}"
        zpath = self.root / f"layout_{bid}.3dsl"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(Path(extdata_dir).rglob("*")):
                if p.is_file():
                    z.write(p, p.relative_to(extdata_dir).as_posix())
                elif p.is_dir():
                    # diretorio vazio (ex.: boss/) PRECISA sobreviver ao zip:
                    # extdata importado sem ele faz o HOME reconstruir o
                    # SaveData inteiro (statuses, tema, pastas) — Fase 0C
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
