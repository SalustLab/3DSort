"""Descoberta do SD do 3DS e wrapper do save3ds_fuse (extract/import de extdata)."""
import subprocess
from dataclasses import dataclass
from pathlib import Path

HOME_EXTDATA_IDS = {"00000082": "JPN", "0000008f": "USA", "00000098": "EUR"}


@dataclass
class Console:
    sd_root: Path
    id0: str
    id1: str
    region: str
    extdata_id: str  # 16 digitos, como o save3ds espera

    @property
    def extdata_dir(self) -> Path:
        return (self.sd_root / "Nintendo 3DS" / self.id0 / self.id1 /
                "extdata" / "00000000" / self.extdata_id[-8:])


def find_console(sd_root: Path) -> Console:
    """Localiza id0/id1 e o extdata do HOME menu no SD. Erro claro se nao achar."""
    sd_root = Path(sd_root)
    n3ds = sd_root / "Nintendo 3DS"
    if not n3ds.is_dir():
        raise FileNotFoundError(f"pasta 'Nintendo 3DS' nao encontrada em {sd_root}")
    for id0 in n3ds.iterdir():
        if not (id0.is_dir() and len(id0.name) == 32):
            continue
        for id1 in id0.iterdir():
            if not (id1.is_dir() and len(id1.name) == 32):
                continue
            ext_root = id1 / "extdata" / "00000000"
            if not ext_root.is_dir():
                continue
            for eid, region in HOME_EXTDATA_IDS.items():
                if (ext_root / eid).is_dir():
                    return Console(sd_root, id0.name, id1.name, region, "00000000" + eid)
    raise FileNotFoundError(f"extdata do HOME menu nao encontrado em {n3ds}")


def find_sd_drive() -> Path | None:
    """Varre drives montados atras de um SD de 3DS."""
    for letter in "DEFGHIJKLMNOP":
        root = Path(f"{letter}:/")
        try:
            if (root / "Nintendo 3DS").is_dir():
                return root
        except OSError:
            continue
    return None


class Save3ds:
    def __init__(self, exe: Path, boot9: Path, movable: Path):
        self.exe, self.boot9, self.movable = Path(exe), Path(boot9), Path(movable)

    @staticmethod
    def extract_movable(essential_exefs: Path, out: Path):
        from pyctr.type.exefs import ExeFSReader
        with ExeFSReader(essential_exefs) as e:
            with e.open("movable") as f:
                Path(out).write_bytes(f.read())

    def _check(self):
        for p in (self.exe, self.boot9, self.movable):
            if not p.exists():
                raise FileNotFoundError(f"recurso do save3ds ausente: {p}")

    def _run(self, extdata_id: str, sd_root: Path, mode: str, target: Path):
        self._check()
        target.mkdir(parents=True, exist_ok=True)
        cmd = [str(self.exe), "--sdext", extdata_id, "--sd", str(sd_root),
               "--boot9", str(self.boot9), "--movable", str(self.movable),
               mode, str(target)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"save3ds {mode} falhou: {r.stderr or r.stdout}")

    def extract(self, extdata_id: str, sd_root: Path, out_dir: Path):
        self._run(extdata_id, sd_root, "--extract", out_dir)

    def import_(self, extdata_id: str, sd_root: Path, src_dir: Path):
        self._run(extdata_id, sd_root, "--import", src_dir)
