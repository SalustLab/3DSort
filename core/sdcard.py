"""Descoberta do SD do 3DS e wrapper do save3ds_fuse (extract/import de extdata)."""
import hashlib
import shutil
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path

HOME_EXTDATA_IDS = {"00000082": "JPN", "0000008f": "USA", "00000098": "EUR"}
# system save do HOME menu na NAND (Launcher.dat vive dentro dele), por regiao
NAND_SAVE_IDS = {"JPN": "00020082", "USA": "0002008f", "EUR": "00020098"}


def id0_from_movable(movable: bytes) -> str:
    """id0 = SHA-256(KeyY)[0:16] lidos como 4 u32 little-endian, cada um em hex.
    KeyY = bytes 0x110:0x120 do movable.sed. Validado contra o console real (spike 0A)."""
    key_y = movable[0x110:0x120]
    digest = hashlib.sha256(key_y).digest()
    return "".join(f"{w:08x}" for w in struct.unpack("<4I", digest[:16]))


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

    # ---- system save da NAND (Launcher.dat) — v1.1 ------------------------
    # O save3ds opera sobre uma arvore NAND "cleartext" sintetica montada no
    # workdir a partir do container dumpado via GodMode9 (cp de
    # 1:/data/<id0>/sysdata/<id>/00000000). A NAND real nunca e tocada daqui.

    def build_nand_tree(self, workdir: Path, container: Path, save_id: str) -> Path:
        """Monta workdir/nand/{private/movable.sed, data/<id0>/sysdata/<id>/00000000}."""
        nand = Path(workdir) / "nand"
        (nand / "private").mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.movable, nand / "private" / "movable.sed")
        id0 = id0_from_movable(Path(self.movable).read_bytes())
        save_dir = nand / "data" / id0 / "sysdata" / save_id
        save_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(container, save_dir / "00000000")
        return nand

    def _run_nand(self, save_id: str, nand_root: Path, mode: str, target: Path):
        self._check()
        target.mkdir(parents=True, exist_ok=True)
        cmd = [str(self.exe), "--nandsave", save_id, "--nand", str(nand_root),
               "--boot9", str(self.boot9), mode, str(target)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"save3ds nandsave {mode} falhou: {r.stderr or r.stdout}")

    def nand_extract(self, save_id: str, nand_root: Path, out_dir: Path):
        self._run_nand(save_id, nand_root, "--extract", out_dir)

    def nand_import(self, save_id: str, nand_root: Path, src_dir: Path):
        self._run_nand(save_id, nand_root, "--import", src_dir)

    @staticmethod
    def nand_container(nand_root: Path, save_id: str) -> Path:
        """Caminho do container dentro da arvore sintetica (pos-import)."""
        return next((Path(nand_root) / "data").glob(f"*/sysdata/{save_id}/00000000"))
