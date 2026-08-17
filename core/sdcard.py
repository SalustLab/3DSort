"""3DS SD card discovery and save3ds_fuse wrapper (extdata extract/import)."""
import getpass
import hashlib
import shutil
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SAVE3DS_NAME = "save3ds_fuse.exe" if sys.platform == "win32" else "save3ds_fuse"
# Keeps the save3ds child process from flashing a console window in a windowed build.
# creationflags only exists on Windows, so the kwargs are empty elsewhere.
_RUN_KW = ({"creationflags": subprocess.CREATE_NO_WINDOW}
           if sys.platform == "win32" else {})

HOME_EXTDATA_IDS = {"00000082": "JPN", "0000008f": "USA", "00000098": "EUR"}
# HOME menu system save on the NAND (Launcher.dat lives inside it), per region
NAND_SAVE_IDS = {"JPN": "00020082", "USA": "0002008f", "EUR": "00020098"}


def id0_from_movable(movable: bytes) -> str:
    """id0 = SHA-256(KeyY)[0:16] read as 4 little-endian u32, each in hex.
    KeyY = bytes 0x110:0x120 of movable.sed. Validated against the real console (spike 0A)."""
    key_y = movable[0x110:0x120]
    digest = hashlib.sha256(key_y).digest()
    return "".join(f"{w:08x}" for w in struct.unpack("<4I", digest[:16]))


@dataclass
class Console:
    sd_root: Path
    id0: str
    id1: str
    region: str
    extdata_id: str  # 16 digits, as save3ds expects

    @property
    def extdata_dir(self) -> Path:
        return (self.sd_root / "Nintendo 3DS" / self.id0 / self.id1 /
                "extdata" / "00000000" / self.extdata_id[-8:])


def find_console(sd_root: Path, prefer_id0: str | None = None) -> Console:
    """Locates id0/id1 and the HOME menu extdata on the SD. Clear error if not found.

    A card can carry several id0 folders (used on more than one console, or kept
    across a system format), and the leftovers look exactly like the live one.
    prefer_id0 (derived from the movable.sed on the card) picks the right one;
    without it, or when it names no folder here, the first match wins."""
    sd_root = Path(sd_root)
    n3ds = sd_root / "Nintendo 3DS"
    if not n3ds.is_dir():
        raise FileNotFoundError(f"'Nintendo 3DS' folder not found in {sd_root}")
    found = []
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
                    c = Console(sd_root, id0.name, id1.name, region, "00000000" + eid)
                    if prefer_id0 is not None and c.id0 == prefer_id0:
                        return c
                    found.append(c)
    if not found:
        raise FileNotFoundError(f"HOME menu extdata not found in {n3ds}")
    return found[0]


def default_sd_candidates(bases=None) -> list[Path]:
    """Places an SD card can be mounted: drive letters D..P on Windows, or the
    subdirectories of the usual removable mount points on Linux/macOS."""
    if sys.platform == "win32":
        return [Path(f"{letter}:/") for letter in "DEFGHIJKLMNOP"]
    if bases is None:
        user = getpass.getuser()
        bases = [Path("/media") / user, Path("/media"), Path("/run/media") / user,
                 Path("/mnt"), Path("/Volumes")]
    out = []
    for base in bases:
        try:
            out.extend(sorted(p for p in Path(base).iterdir() if p.is_dir()))
        except OSError:
            continue
    return out


def list_3ds_roots(candidates=None) -> list[Path]:
    """Candidates that contain a 'Nintendo 3DS' folder (default: see
    default_sd_candidates)."""
    if candidates is None:
        candidates = default_sd_candidates()
    out = []
    for root in candidates:
        try:
            if (Path(root) / "Nintendo 3DS").is_dir():
                out.append(Path(root))
        except OSError:
            continue
    return out


def find_sd_drive() -> Path | None:
    """Scans mounted drives for a 3DS SD card."""
    roots = list_3ds_roots()
    return roots[0] if roots else None


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
                raise FileNotFoundError(f"save3ds resource missing: {p}")

    def _run(self, extdata_id: str, sd_root: Path, mode: str, target: Path):
        self._check()
        target.mkdir(parents=True, exist_ok=True)
        cmd = [str(self.exe), "--sdext", extdata_id, "--sd", str(sd_root),
               "--boot9", str(self.boot9), "--movable", str(self.movable),
               mode, str(target)]
        r = subprocess.run(cmd, capture_output=True, text=True, **_RUN_KW)
        if r.returncode != 0:
            raise RuntimeError(f"save3ds {mode} failed: {r.stderr or r.stdout}")

    def extract(self, extdata_id: str, sd_root: Path, out_dir: Path):
        self._run(extdata_id, sd_root, "--extract", out_dir)

    def import_(self, extdata_id: str, sd_root: Path, src_dir: Path):
        self._run(extdata_id, sd_root, "--import", src_dir)

    # ---- NAND system save (Launcher.dat) - v1.1 ----------------------------
    # save3ds operates on a synthetic "cleartext" NAND tree assembled in the
    # workdir from the container dumped via GodMode9 (cp of
    # 1:/data/<id0>/sysdata/<id>/00000000). The real NAND is never touched from here.

    def build_nand_tree(self, workdir: Path, container: Path, save_id: str) -> Path:
        """Builds workdir/nand/{private/movable.sed, data/<id0>/sysdata/<id>/00000000}."""
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
        r = subprocess.run(cmd, capture_output=True, text=True, **_RUN_KW)
        if r.returncode != 0:
            raise RuntimeError(f"save3ds nandsave {mode} failed: {r.stderr or r.stdout}")

    def nand_extract(self, save_id: str, nand_root: Path, out_dir: Path):
        self._run_nand(save_id, nand_root, "--extract", out_dir)

    def nand_import(self, save_id: str, nand_root: Path, src_dir: Path):
        self._run_nand(save_id, nand_root, "--import", src_dir)

    @staticmethod
    def nand_container(nand_root: Path, save_id: str) -> Path:
        """Path of the container inside the synthetic tree (post-import)."""
        return next((Path(nand_root) / "data").glob(f"*/sysdata/{save_id}/00000000"))
