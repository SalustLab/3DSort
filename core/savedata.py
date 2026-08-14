"""SaveData.dat (v4) do HOME menu — ordem de icones e pasta de cada icone.

Formato: 3dbrew /wiki/Home_Menu. Regioes nao documentadas sao preservadas
byte a byte: o parser mantem o buffer original e so reescreve os arrays
conhecidos ao serializar.
"""
import struct
from dataclasses import dataclass

SIZE = 0x2DA0
OFF_TID = 0x8       # u64[360]
OFF_STATUS = 0xB48  # s8[360], 1 = icone ativo
OFF_POS = 0xCB0     # s16[360], posicao linear no grid
OFF_FOLDER = 0xF80  # s8[360], indice da pasta (-1 = home grid)
SLOTS = 360


@dataclass
class Entry:
    slot: int
    tid: int
    pos: int
    folder: int


class SaveData:
    def __init__(self, raw: bytes):
        if len(raw) != SIZE:
            raise ValueError(f"SaveData.dat: esperado {SIZE:#x} bytes, veio {len(raw):#x}")
        if raw[0] != 4:
            raise ValueError(f"SaveData.dat: versao {raw[0]} nao suportada (esperado 4)")
        self._buf = bytearray(raw)

    @property
    def entries(self) -> list[Entry]:
        tids = struct.unpack_from(f"<{SLOTS}Q", self._buf, OFF_TID)
        status = struct.unpack_from(f"<{SLOTS}b", self._buf, OFF_STATUS)
        pos = struct.unpack_from(f"<{SLOTS}h", self._buf, OFF_POS)
        folder = struct.unpack_from(f"<{SLOTS}b", self._buf, OFF_FOLDER)
        return [Entry(i, tids[i], pos[i], folder[i]) for i in range(SLOTS) if status[i] == 1]

    def set_position(self, slot: int, pos: int):
        struct.pack_into("<h", self._buf, OFF_POS + slot * 2, pos)

    def set_folder(self, slot: int, folder: int):
        struct.pack_into("<b", self._buf, OFF_FOLDER + slot, folder)

    def apply_order(self, slots_in_order: list[int], reserved: dict | None = None):
        """Reatribui posicoes POR CONTEINER (home grid = -1, cada pasta) na ordem dada.

        Posicoes sao locais ao conteiner (validado em dump real do Launcher.dat:
        item de pasta reinicia em 0). `reserved` ({folder: {pos,...}}) marca os
        slots que nunca podem ser ocupados (apps NAND, tiles de pasta, lacunas);
        quando None, e derivado das lacunas atuais do proprio arquivo — so vale
        se as pastas NAO mudaram (com set_folder antes, as lacunas derivadas
        misturariam posicao velha com pasta nova: passe o reserved do estado
        original). Membros novos de um conteiner entram nas menores posicoes
        livres. Usa a pasta ATUAL de cada slot. Exige todos os slots ativos.
        """
        entries = self.entries
        active = {e.slot for e in entries}
        if set(slots_in_order) != active or len(slots_in_order) != len(active):
            raise ValueError("apply_order: conjunto de slots nao bate com os icones ativos")
        if reserved is None:
            reserved = merge_reserved({e.slot: (e.folder, e.pos) for e in entries}, None)
        for slot, pos in assign_positions(
                slots_in_order, {e.slot: e.folder for e in entries}, reserved).items():
            self.set_position(slot, pos)

    def serialize(self) -> bytes:
        return bytes(self._buf)


def merge_reserved(current: dict, extra: dict | None) -> dict:
    """Reservas por conteiner: lacunas atuais ([0..max] menos posicoes ocupadas)
    unidas as explicitas. `current`: {slot: (folder, pos)}."""
    held = {}
    for folder, pos in current.values():
        held.setdefault(folder, set()).add(pos)
    reserved = {f: set(range(max(ps) + 1)) - ps for f, ps in held.items()}
    for f, ps in (extra or {}).items():
        reserved.setdefault(f, set()).update(ps)
    return reserved


def assign_positions(slots_in_order: list[int], folder_of: dict,
                     reserved: dict) -> dict:
    """Menores posicoes livres de cada conteiner, na ordem dada, pulando reservas."""
    out, nxt = {}, {}
    for slot in slots_in_order:
        c = folder_of[slot]
        p = nxt.get(c, 0)
        res = reserved.get(c, ())
        while p in res:
            p += 1
        out[slot] = p
        nxt[c] = p + 1
    return out
