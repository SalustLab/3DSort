"""3DSort — app desktop (pywebview) e modo dev --serve para testes Playwright.

Uso:
  python app.py                 janela nativa (SD real, se encontrado)
  python app.py --serve [porta] UI + API em http://127.0.0.1:porta (dev/testes)
  python app.py --mock          dados sinteticos (sem SD/boot9) — combinavel com --serve
  python app.py --sd CAMINHO    usa esse caminho como raiz do SD (ex.: o sandbox)
"""
import json
import struct
import sys
import tempfile
from pathlib import Path

from core.icons import (cache_index, icon_png_b64, smdh_entry, smdh_short_name,
                        twl_icon_png_b64, twl_short_name)
from core.launcher import parse as parse_launcher
from core.savedata import SaveData, assign_positions, merge_reserved
from core.sdcard import Save3ds, find_console, find_sd_drive
from core.store import Backups, Staging

ROOT = Path(__file__).parent
UI = ROOT / "ui"
APP_DIR = Path.home() / "3DSort"


class Api:
    """Camada unica consumida pela ponte js_api do pywebview e pelo modo --serve."""

    def __init__(self, save3ds: Save3ds, sd_root: Path | None, workdir: Path,
                 backups: Backups, launcher: Path | None = None):
        self.save3ds = save3ds
        self.sd_root = sd_root
        self.workdir = Path(workdir)
        self.backups = backups
        self.launcher_path = launcher  # Launcher.dat (NAND, dump manual) — opcional
        self.console = None
        self.staging = None
        self._names = {}
        self._icons = {}
        self._reserved = {}    # {conteiner: {pos reservada (NAND/pasta/lacuna)}}
        self._launcher_reserved = {}  # so as reservas vindas do Launcher.dat
        self._system = []      # apps NAND do Launcher.dat (se houver)
        self._launcher_folders = []

    # ---- ciclo de vida -------------------------------------------------
    def import_sd(self):
        """(Re)le o layout do SD para o workdir e reinicia o staging."""
        if self.sd_root is None:
            self.sd_root = find_sd_drive()
        if self.sd_root is None:
            return {"error": "SD do 3DS nao encontrado"}
        self.console = find_console(self.sd_root)
        ext = self.workdir / "extract"
        if ext.exists():
            import shutil
            shutil.rmtree(ext)
        self.save3ds.extract(self.console.extdata_id, self.sd_root, ext)
        self._load(ext)
        return self.get_state()

    def _load(self, ext: Path):
        raw = (ext / "user" / "SaveData.dat").read_bytes()
        sd = SaveData(raw)
        cached = (ext / "user" / "CacheD.dat").read_bytes()
        idx = cache_index((ext / "user" / "Cache.dat").read_bytes())
        self._names, self._icons = {}, {}
        for tid, i in idx.items():
            e = smdh_entry(cached, i)
            n = smdh_short_name(e) or twl_short_name(e)  # TWL = DSiWare (banner NDS)
            if n:
                self._names[tid] = n
                self._icons[tid] = icon_png_b64(e) or twl_icon_png_b64(e)
        order = [e.slot for e in sorted(sd.entries, key=lambda e: e.pos)]
        folders = {e.slot: e.folder for e in sd.entries}
        tids = {e.slot: e.tid for e in sd.entries}
        self.staging = Staging({"order": order, "folders": folders, "tids": tids})
        self._system, self._launcher_folders, self._cart_pos = [], [], None
        self._launcher_reserved = {}
        if self.launcher_path and Path(self.launcher_path).exists():
            entries, lfolders, cart = parse_launcher(Path(self.launcher_path).read_bytes())
            self._system = sorted(entries, key=lambda e: e.pos)
            self._launcher_folders = lfolders
            self._cart_pos = cart
            for e in entries:
                self._launcher_reserved.setdefault(e.folder, set()).add(e.pos)
            for f in lfolders:  # o tile da pasta ocupa um slot do home grid
                self._launcher_reserved.setdefault(-1, set()).add(f.pos)
            if cart is not None:  # slot do cartucho tambem
                self._launcher_reserved.setdefault(-1, set()).add(cart)
        self._reserved = merge_reserved(
            {e.slot: (e.folder, e.pos) for e in sd.entries}, self._launcher_reserved)

    # ---- leitura -------------------------------------------------------
    def get_state(self):
        if self.staging is None:
            r = self.import_sd()
            if "error" in r:
                return r
        st = self.staging.state
        # mesma atribuicao que write_sd fara: posicao por conteiner, pulando reservas
        pos_map = assign_positions(st["order"], st["folders"], self._reserved)
        items = []
        for slot in st["order"]:
            tid = st["tids"][slot]
            items.append({
                "slot": slot, "pos": pos_map[slot], "tid": f"{tid:016x}",
                "folder": st["folders"][slot],
                "name": self._names.get(tid, f"{tid:016x}"),
                "icon": self._icons.get(tid),
            })
        system = [{"tid": f"{e.tid:016x}", "pos": e.pos, "folder": e.folder,
                   "pinned": True, "name": self._names.get(e.tid, "System"),
                   "icon": self._icons.get(e.tid)} for e in self._system]
        if self._cart_pos is not None:
            system.append({"tid": None, "pos": self._cart_pos, "folder": -1,
                           "pinned": True, "name": "Game Card", "icon": None})
        # reservas do home sem dono conhecido (sem Launcher.dat: todas) = placeholders
        known = ({s["pos"] for s in system if s["folder"] == -1} |
                 {f.pos for f in self._launcher_folders})
        system += [{"tid": None, "pos": p, "folder": -1, "pinned": True,
                    "name": "System app", "icon": None}
                   for p in sorted(self._reserved.get(-1, set()) - known)]
        system.sort(key=lambda s: (s["folder"], s["pos"]))
        return {
            "items": items,
            "system": system,
            "folderNames": {f.id: f.name for f in self._launcher_folders},
            "folderPos": {f.id: f.pos for f in self._launcher_folders},
            "staged": list(self.staging.staged),
            "canUndo": bool(self.staging._undo),
            "canRedo": bool(self.staging._redo),
            "sd": self._sd_info(),
            "backups_dir": str(self.backups.root),
            "history": self.backups.history()[::-1],
        }

    def _sd_info(self):
        info = {"region": self.console.region if self.console else None,
                "root": str(self.sd_root) if self.sd_root else None}
        if self.sd_root is not None:
            try:
                import shutil
                du = shutil.disk_usage(self.sd_root)
                info["total_bytes"] = du.total
                info["used_bytes"] = du.used
                info["free_blocks"] = du.free // 131072  # bloco do 3DS = 128 KB
            except OSError:
                pass
        return info

    # ---- mutacoes (staged) ----------------------------------------------
    def _commit(self, label, **changes):
        self.staging.commit(label, {**self.staging.state, **changes})
        return self.get_state()

    def move_item(self, slot: int, before_slot: int | None):
        order = [s for s in self.staging.state["order"] if s != slot]
        i = order.index(before_slot) if before_slot is not None else len(order)
        order.insert(i, slot)
        tid = self.staging.state["tids"][slot]
        return self._commit(f"Moved {self._names.get(tid, slot)}", order=order)

    def swap_items(self, slot_a: int, slot_b: int):
        """Troca exata de lugar entre dois itens — nenhum outro se move."""
        st = self.staging.state
        order = list(st["order"])
        i, j = order.index(slot_a), order.index(slot_b)
        order[i], order[j] = order[j], order[i]
        folders = dict(st["folders"])
        folders[slot_a], folders[slot_b] = folders[slot_b], folders[slot_a]
        names = self._names
        tids = st["tids"]
        return self._commit(
            f"Swapped {names.get(tids[slot_a], slot_a)} <-> {names.get(tids[slot_b], slot_b)}",
            order=order, folders=folders)

    def set_folder(self, slot: int, folder: int):
        folders = dict(self.staging.state["folders"])
        folders[slot] = folder
        tid = self.staging.state["tids"][slot]
        verb = "Removed from folder" if folder == -1 else f"Moved into folder {folder}"
        return self._commit(f"{verb}: {self._names.get(tid, slot)}", folders=folders)

    def sort_preset(self, preset: str):
        st = self.staging.state
        keyed = [(self._names.get(st["tids"][s], ""), s) for s in st["order"]]
        rev = preset in ("za",)
        order = [s for _, s in sorted(keyed, key=lambda t: t[0].lower(), reverse=rev)]
        label = {"az": "A → Z", "za": "Z → A"}[preset]
        return self._commit(f"Sorted: {label}", order=order)

    def undo(self):
        if self.staging._undo:
            self.staging.undo()
        return self.get_state()

    def redo(self):
        if self.staging._redo:
            self.staging.redo()
        return self.get_state()

    def reset_staging(self):
        """Descarta todas as mudancas staged (cada uma recuperavel via redo)."""
        while self.staging._undo:
            self.staging.undo()
        return self.get_state()

    # ---- SD ---------------------------------------------------------------
    def backup_manual(self):
        self.backups.create(self.workdir / "extract", kind="manual", note="backup manual")
        return self.get_state()

    def restore_backup(self, backup_id: str):
        self.backups.restore(backup_id, self.workdir / "extract")
        self._load(self.workdir / "extract")
        # restaurar e um estado novo em relacao ao SD: precisa ficar staged para o WRITE
        self.staging.commit(f"Restored backup {backup_id}", self.staging.state)
        return self.get_state()

    def write_sd(self):
        """Aplica o staging ao SaveData.dat e importa para o SD. Backup antes, sempre."""
        n = len(self.staging.staged)
        if n == 0:
            return {"error": "nada staged"}
        ext = self.workdir / "extract"
        self.backups.create(ext, kind="auto", note=f"antes de escrever {n} mudancas")
        sav_path = ext / "user" / "SaveData.dat"
        sd = SaveData(sav_path.read_bytes())
        st = self.staging.state
        # pastas primeiro: apply_order distribui posicoes pelo conteiner ATUAL
        for slot, folder in st["folders"].items():
            sd.set_folder(int(slot), folder)
        sd.apply_order(list(st["order"]), reserved=self._reserved)
        sav_path.write_bytes(sd.serialize())
        self.save3ds.import_(self.console.extdata_id, self.sd_root, ext)
        self.staging.clear()
        return self.get_state()


# ---- mock: mesma Api, crypto fake -------------------------------------------
class FakeSave3ds(Save3ds):
    """Simula extract/import copiando uma arvore de extdata ja 'decriptada'."""

    def __init__(self, plain_dir: Path):
        self.plain = Path(plain_dir)

    def extract(self, extdata_id, sd_root, out_dir):
        import shutil
        shutil.copytree(self.plain, out_dir, dirs_exist_ok=True)

    def import_(self, extdata_id, sd_root, src_dir):
        import shutil
        shutil.copytree(src_dir, self.plain, dirs_exist_ok=True)


def _mock_icon(name, base):
    """Icone 48x48 estilo prototipo: gradiente diagonal + monograma."""
    from PIL import Image, ImageDraw, ImageFont
    dark = tuple(int(c * .62) for c in base)
    img = Image.new("RGB", (48, 48))
    px = img.load()
    for y in range(48):
        for x in range(48):
            t = (x + y) / 94
            px[x, y] = tuple(int(base[k] + (dark[k] - base[k]) * t) for k in range(3))
    words = name.split()
    mono = "".join(w[0] for w in words)[:3].upper()
    try:
        font = ImageFont.truetype("arialbd.ttf", 20 if len(mono) < 3 else 16)
    except OSError:
        font = ImageFont.load_default()
    d = ImageDraw.Draw(img)
    box = d.textbbox((0, 0), mono, font=font)
    d.text(((48 - box[2] - box[0]) / 2, (48 - box[3] - box[1]) / 2), mono,
           fill=(255, 255, 255), font=font)
    return img


# apps NAND do mock: (nome, tid real, pos, pasta) — home 0-2 + 8, um dentro de pasta
MOCK_NAND = [("System Settings", 0x0004001000021000, 0, -1),
             ("Mii Maker", 0x0004001000021700, 1, -1),
             ("Nintendo eShop", 0x0004001000021900, 2, -1),
             ("StreetPass Mii Plaza", 0x0004001000021800, 8, -1),
             ("Health & Safety", 0x0004001020021300, 0, 0)]
MOCK_FOLDERS = [(0, 9, "Homebrew")]  # (id, pos do tile no home grid, nome)


def make_mock_extdata(target: Path):
    """Extdata sintetico: 12 jogos + SMDH dos apps NAND do mock no cache."""
    from core.icons import MORTON, SMDH_ENTRY, SMDH_LARGE_OFF
    from core.savedata import OFF_FOLDER, OFF_POS, OFF_STATUS, OFF_TID, SIZE

    def build_savedata(entries):
        buf = bytearray(SIZE)
        buf[0] = 4
        for i in range(360):
            struct.pack_into("<h", buf, OFF_POS + i * 2, -1)
            struct.pack_into("<b", buf, OFF_FOLDER + i, -1)
        for slot, tid, pos, folder in entries:
            struct.pack_into("<Q", buf, OFF_TID + slot * 8, tid)
            struct.pack_into("<b", buf, OFF_STATUS + slot, 1)
            struct.pack_into("<h", buf, OFF_POS + slot * 2, pos)
            struct.pack_into("<b", buf, OFF_FOLDER + slot, folder)
        return bytes(buf)
    games = ["Mario Kart 7", "Animal Crossing New Leaf", "Pokemon Y",
             "Zelda A Link Between Worlds", "Fire Emblem Awakening",
             "Super Smash Bros", "Luigis Mansion", "Kirby Triple Deluxe",
             "Tomodachi Life", "Monster Hunter 4", "Rhythm Heaven", "Shovel Knight"]
    user = target / "user"
    user.mkdir(parents=True, exist_ok=True)
    entries, cache, cached = [], bytearray(8), bytearray()
    cache[0] = 1

    def add_title(tid, name, k):
        nonlocal cache, cached
        cache += struct.pack("<QII", tid, 0, 0)
        e = bytearray(SMDH_ENTRY)
        e[0:4] = b"SMDH"
        for lang in range(16):
            e[0x8 + lang * 0x200: 0x8 + lang * 0x200 + len(name) * 2] = name.encode("utf-16-le")
        base = ((k * 47) % 200 + 55, (k * 83) % 200 + 30, (k * 131) % 220 + 35)
        img = _mock_icon(name, base)
        px = img.load()
        pos = SMDH_LARGE_OFF
        for ty in range(0, 48, 8):
            for tx in range(0, 48, 8):
                for dx, dy in MORTON:
                    r, g, b = px[tx + dx, ty + dy]
                    v = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
                    e[pos:pos + 2] = struct.pack("<H", v)
                    pos += 2
        cached += e

    taken = ({p for _, _, p, f in MOCK_NAND if f == -1} |
             {p for _, p, _ in MOCK_FOLDERS})
    game_pos = [p for p in range(len(games) + len(taken)) if p not in taken]
    for i, name in enumerate(games):
        tid = 0x0004000000030000 + i * 0x100
        entries.append((i, tid, game_pos[i], -1))
        add_title(tid, name, i)
    for j, (name, tid, _, _) in enumerate(MOCK_NAND):
        add_title(tid, name, len(games) + j)
    (user / "SaveData.dat").write_bytes(build_savedata(entries))
    (user / "Cache.dat").write_bytes(cache)
    (user / "CacheD.dat").write_bytes(cached)


def make_mock_launcher(path: Path):
    """Launcher.dat sintetico com os apps NAND e pastas do mock."""
    from core import launcher as ln
    buf = bytearray(ln.SIZE)
    struct.pack_into("<H", buf, ln.OFF_CART_POS, 0xFFFF)  # sem cartucho no mock
    for i in range(ln.SLOTS):
        struct.pack_into("<h", buf, ln.OFF_POS + i * 2, -1)
        struct.pack_into("<b", buf, ln.OFF_FOLDER + i, -1)
    for i in range(ln.FOLDERS):
        struct.pack_into("<h", buf, ln.OFF_FOLDER_POS + i * 2, -1)
    for slot, (_, tid, pos, folder) in enumerate(MOCK_NAND):
        struct.pack_into("<Q", buf, ln.OFF_TID + slot * 8, tid)
        struct.pack_into("<h", buf, ln.OFF_POS + slot * 2, pos)
        struct.pack_into("<b", buf, ln.OFF_FOLDER + slot, folder)
    for fid, pos, name in MOCK_FOLDERS:
        struct.pack_into("<h", buf, ln.OFF_FOLDER_POS + fid * 2, pos)
        struct.pack_into("<B", buf, ln.OFF_FOLDER_ROWS + fid, 2)
        raw = name.encode("utf-16-le")
        buf[ln.OFF_FOLDER_NAME + fid * 0x22: ln.OFF_FOLDER_NAME + fid * 0x22 + len(raw)] = raw
    path.write_bytes(bytes(buf))


def build_api(mock: bool, sd_root: Path | None = None) -> Api:
    if mock:
        tmp = Path(tempfile.mkdtemp(prefix="3dsort-mock-"))
        plain = tmp / "plain"
        make_mock_extdata(plain)
        # arvore fake de SD para o fluxo real de find_console funcionar
        fake_sd = tmp / "sd"
        (fake_sd / "Nintendo 3DS" / ("0" * 32) / ("1" * 32) / "extdata" /
         "00000000" / "0000008f").mkdir(parents=True)
        launcher = tmp / "Launcher.dat"
        make_mock_launcher(launcher)
        return Api(FakeSave3ds(plain), fake_sd, tmp / "work", Backups(tmp / "backups"),
                   launcher=launcher)
    workdir = APP_DIR / "work"
    workdir.mkdir(parents=True, exist_ok=True)
    sandbox_keys = ROOT / "sandbox" / "keys"
    launcher = next((p for p in (sandbox_keys / "Launcher.dat", APP_DIR / "Launcher.dat")
                     if p.exists()), None)
    return Api(
        Save3ds(ROOT / "tools" / "save3ds" / "save3ds_fuse.exe",
                sandbox_keys / "boot9.bin", sandbox_keys / "movable.sed"),
        sd_root, workdir, Backups(APP_DIR / "backups"), launcher=launcher)


def serve(api: Api, port: int):
    import http.server

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(UI), **kw)

        def do_POST(self):
            name = self.path.removeprefix("/api/")
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
            args = json.loads(body).get("args", []) if body else []
            try:
                result = getattr(api, name)(*args)
            except Exception as e:  # erro vira JSON, nao stacktrace no browser
                result = {"error": str(e)}
            data = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    print(f"3DSort dev em http://127.0.0.1:{port}")
    http.server.ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()


def main():
    args = sys.argv[1:]
    sd = Path(args[args.index("--sd") + 1]) if "--sd" in args else None
    api = build_api(mock="--mock" in args, sd_root=sd)
    if "--serve" in args:
        port = next((int(a) for a in args if a.isdigit()), 8347)
        serve(api, port)
    else:
        import webview
        webview.create_window("3DSort", str(UI / "index.html"), js_api=api,
                              width=1280, height=800)
        webview.start()


if __name__ == "__main__":
    main()
