"""Launcher.dat (system save do HOME menu na NAND) — parse e escrita cirurgica.

Formato: 3dbrew /wiki/Home_Menu. Da as posicoes/pastas dos apps NAND e as
definicoes das pastas (nome, posicao, linhas), que nao existem no SD.
O arquivo vive dentro do container DISA em nand:/data/<id0>/sysdata/<ID>/00000000
(ID por regiao: JPN 00020082, USA 0002008F, EUR 00020098), dumpado via GodMode9
e editado no PC via save3ds --nandsave (core/sdcard.py).

Estrategia identica a savedata.SaveData: o buffer INTEIRO e preservado e apenas
os arrays conhecidos sao reescritos. Round-trip byte-identico por construcao.
Regioes nao documentadas contem dados vivos (cursor/UI em 0xB51-0xB5E,
estatisticas em 0x1D58+) — nunca tocar. Excecao decifrada no gate 0B
(2026-08-14): o contador "proximo nº de pasta" (u32 @0xD80 + byte espelho
@0xD85), mantido por set_next_folder_number.
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
OFF_FOLDER_NAME = 0x1560  # 60 x 0x22 bytes UTF-16LE (16 unidades + NUL garantido)
OFF_NEXT_FOLDER_NUM = 0xD80         # u32: proximo nº de batismo de pasta (gate 0B)
OFF_NEXT_FOLDER_NUM_MIRROR = 0xD85  # u8: espelho do contador (byte baixo)
SLOTS = 360
FOLDERS = 60
EMPTY_TIDS = (0, 0xFFFFFFFFFFFFFFFF)
NAME_BYTES = 0x22
NAME_MAX_PAYLOAD = 0x20   # 16 unidades UTF-16; ultimos 2 bytes sempre NUL


@dataclass
class NandEntry:
    slot: int
    tid: int
    pos: int
    folder: int


@dataclass
class Folder:
    id: int
    pos: int
    rows: int
    name: str


class Launcher:
    """Buffer inteiro preservado; mutacoes cirurgicas nos arrays conhecidos."""

    def __init__(self, raw: bytes):
        # console real (11.17 USA) produz 0x2558 bytes: campos extras no fim, layout igual
        if len(raw) < SIZE:
            raise ValueError(f"Launcher.dat: esperado >= {SIZE:#x} bytes, veio {len(raw):#x}")
        self._buf = bytearray(raw)

    # ---- leitura -----------------------------------------------------------
    @property
    def entries(self) -> list[NandEntry]:
        tids = struct.unpack_from(f"<{SLOTS}Q", self._buf, OFF_TID)
        pos = struct.unpack_from(f"<{SLOTS}h", self._buf, OFF_POS)
        folder = struct.unpack_from(f"<{SLOTS}b", self._buf, OFF_FOLDER)
        return [NandEntry(i, tids[i], pos[i], folder[i]) for i in range(SLOTS)
                if tids[i] not in EMPTY_TIDS and pos[i] >= 0]

    @property
    def folders(self) -> list[Folder]:
        fpos = struct.unpack_from(f"<{FOLDERS}h", self._buf, OFF_FOLDER_POS)
        frows = struct.unpack_from(f"<{FOLDERS}B", self._buf, OFF_FOLDER_ROWS)
        out = []
        for i in range(FOLDERS):
            if fpos[i] < 0:
                continue
            b = self._buf[OFF_FOLDER_NAME + i * NAME_BYTES:
                          OFF_FOLDER_NAME + (i + 1) * NAME_BYTES]
            out.append(Folder(i, fpos[i], frows[i],
                              bytes(b).decode("utf-16-le").split("\x00")[0]))
        return out

    @property
    def cart_pos(self) -> int | None:
        v = struct.unpack_from("<H", self._buf, OFF_CART_POS)[0]
        return None if v >= SLOTS else v

    # ---- mutacoes ----------------------------------------------------------
    def set_position(self, slot: int, pos: int):
        struct.pack_into("<h", self._buf, OFF_POS + slot * 2, pos)

    def set_folder(self, slot: int, folder: int):
        struct.pack_into("<b", self._buf, OFF_FOLDER + slot, folder)

    def set_folder_pos(self, fid: int, pos: int):
        struct.pack_into("<h", self._buf, OFF_FOLDER_POS + fid * 2, pos)

    def set_folder_rows(self, fid: int, rows: int):
        if rows < 1:
            raise ValueError(f"pasta {fid}: rows deve ser >= 1, veio {rows}")
        struct.pack_into("<B", self._buf, OFF_FOLDER_ROWS + fid, rows)

    def set_folder_name(self, fid: int, name: str):
        raw = name.encode("utf-16-le")
        if not name or len(raw) > NAME_MAX_PAYLOAD:
            raise ValueError(f"nome de pasta invalido (1..16 caracteres): {name!r}")
        field = raw + b"\x00" * (NAME_BYTES - len(raw))
        self._buf[OFF_FOLDER_NAME + fid * NAME_BYTES:
                  OFF_FOLDER_NAME + (fid + 1) * NAME_BYTES] = field

    def set_cart_pos(self, pos: int | None):
        struct.pack_into("<H", self._buf, OFF_CART_POS, 0xFFFF if pos is None else pos)

    @property
    def next_folder_number(self) -> int:
        return struct.unpack_from("<I", self._buf, OFF_NEXT_FOLDER_NUM)[0]

    def set_next_folder_number(self, n: int):
        # console duplica o valor num byte @0xD85; semantica exata desconhecida,
        # espelhamos o byte baixo (valores reais observados sao pequenos)
        struct.pack_into("<I", self._buf, OFF_NEXT_FOLDER_NUM, n)
        struct.pack_into("<B", self._buf, OFF_NEXT_FOLDER_NUM_MIRROR, n & 0xFF)

    def free_folder_ids(self) -> list[int]:
        """fids com pos < 0 e sem NENHUMA entrada NAND ativa apontando para eles.
        Refs SD sao checadas na camada Api (o SaveData nao esta visivel daqui)."""
        fpos = struct.unpack_from(f"<{FOLDERS}h", self._buf, OFF_FOLDER_POS)
        referenced = {e.folder for e in self.entries}
        return [i for i in range(FOLDERS) if fpos[i] < 0 and i not in referenced]

    def create_folder(self, name: str, rows: int = 2) -> int:
        """Reivindica o menor fid livre; pos fica -1 ate o caller posicionar o tile."""
        free = self.free_folder_ids()
        if not free:
            raise ValueError("sem slot de pasta livre (60 em uso)")
        fid = free[0]
        self.set_folder_name(fid, name)
        self.set_folder_rows(fid, rows)
        return fid

    def delete_folder(self, fid: int):
        members = [e.slot for e in self.entries if e.folder == fid]
        if members:
            raise ValueError(f"pasta {fid} ainda tem membros NAND: {members}")
        self.set_folder_pos(fid, -1)
        struct.pack_into("<B", self._buf, OFF_FOLDER_ROWS + fid, 2)
        self._buf[OFF_FOLDER_NAME + fid * NAME_BYTES:
                  OFF_FOLDER_NAME + (fid + 1) * NAME_BYTES] = b"\x00" * NAME_BYTES

    # ---- invariantes -------------------------------------------------------
    def validate(self, active_sd_refs: set = frozenset()):
        """Chamado antes de toda escrita. Erros aqui nunca chegam ao console."""
        live = {f.id for f in self.folders}
        containers: dict[int, list[int]] = {}
        for e in self.entries:
            if e.folder != -1 and e.folder not in live:
                raise ValueError(f"slot NAND {e.slot} referencia pasta morta {e.folder}")
            if not 0 <= e.pos < SLOTS:
                raise ValueError(f"slot NAND {e.slot} com posicao fora do grid: {e.pos}")
            containers.setdefault(e.folder, []).append(e.pos)
        for f in self.folders:
            if not 0 <= f.pos < SLOTS:
                raise ValueError(f"pasta {f.id} com posicao fora do grid: {f.pos}")
            if f.rows < 1:
                raise ValueError(f"pasta {f.id} com rows invalido: {f.rows}")
            containers.setdefault(-1, []).append(f.pos)
        if self.cart_pos is not None:
            containers.setdefault(-1, []).append(self.cart_pos)
        for cont, ps in containers.items():
            dup = {p for p in ps if ps.count(p) > 1}
            if dup:
                raise ValueError(f"posicoes duplicadas no container {cont}: {sorted(dup)}")
        for ref in active_sd_refs:
            if ref != -1 and ref not in live:
                raise ValueError(f"SaveData referencia pasta morta {ref}")

    def serialize(self) -> bytes:
        out = bytes(self._buf)
        if not out:  # §5.6: arquivo zero-size quebra o extdata/save no console
            raise ValueError("serialize produziria arquivo vazio")
        return out


def parse(raw: bytes) -> tuple[list[NandEntry], list[Folder], int | None]:
    """Wrapper de compat: -> (entries NAND, pastas, posicao do cartucho ou None)."""
    ln = Launcher(raw)
    return ln.entries, ln.folders, ln.cart_pos
