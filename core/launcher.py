"""Launcher.dat (system save do HOME menu na NAND) — LEITURA APENAS.

Formato: 3dbrew /wiki/Home_Menu. Da as posicoes/pastas dos apps NAND e as
definicoes das pastas (nome, posicao, linhas), que nao existem no SD.
O arquivo sai plano do GodMode9 (montar nand:/data/<id0>/sysdata/<ID>/00000000
e copiar /Launcher.dat; ID por regiao: JPN 00020082, USA 0002008F, EUR 00020098).
v1 nunca serializa/escreve este arquivo.
"""
import struct
from dataclasses import dataclass

SIZE = 0x2490
OFF_CART_POS = 0x2        # u16, posicao do slot de cartucho no home grid
OFF_TID = 0x8             # u64[360] titleIDs NAND
OFF_POS = 0xD9A           # s16[360] posicao linear (espaco compartilhado com o SD)
OFF_FOLDER = 0x106A       # s8[360], -1 = home grid
OFF_FOLDER_POS = 0x11DC   # s16[60], -1 = pasta apagada
OFF_FOLDER_ROWS = 0x1434  # u8[60]
OFF_FOLDER_NAME = 0x1560  # 60 x 0x22 bytes UTF-16LE (0x11 chars)
SLOTS = 360
FOLDERS = 60
EMPTY_TIDS = (0, 0xFFFFFFFFFFFFFFFF)


@dataclass
class NandEntry:
    tid: int
    pos: int
    folder: int


@dataclass
class Folder:
    id: int
    pos: int
    rows: int
    name: str


def parse(raw: bytes) -> tuple[list[NandEntry], list[Folder], int | None]:
    """-> (entries NAND, pastas, posicao do cartucho no home grid ou None)."""
    # console real (11.17 USA) produz 0x2558 bytes: campos extras no fim, layout igual
    if len(raw) < SIZE:
        raise ValueError(f"Launcher.dat: esperado >= {SIZE:#x} bytes, veio {len(raw):#x}")
    cart_pos = struct.unpack_from("<H", raw, OFF_CART_POS)[0]
    if cart_pos >= SLOTS:
        cart_pos = None
    tids = struct.unpack_from(f"<{SLOTS}Q", raw, OFF_TID)
    pos = struct.unpack_from(f"<{SLOTS}h", raw, OFF_POS)
    folder = struct.unpack_from(f"<{SLOTS}b", raw, OFF_FOLDER)
    entries = [NandEntry(tids[i], pos[i], folder[i]) for i in range(SLOTS)
               if tids[i] not in EMPTY_TIDS and pos[i] >= 0]
    fpos = struct.unpack_from(f"<{FOLDERS}h", raw, OFF_FOLDER_POS)
    frows = struct.unpack_from(f"<{FOLDERS}B", raw, OFF_FOLDER_ROWS)
    folders = []
    for i in range(FOLDERS):
        if fpos[i] < 0:
            continue
        b = raw[OFF_FOLDER_NAME + i * 0x22: OFF_FOLDER_NAME + (i + 1) * 0x22]
        folders.append(Folder(i, fpos[i], frows[i], b.decode("utf-16-le").split("\x00")[0]))
    return entries, folders, cart_pos
