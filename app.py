"""3DSort — app desktop (pywebview) e modo dev --serve para testes Playwright.

Uso:
  python app.py                 janela nativa (SD real, se encontrado)
  python app.py --serve [porta] UI + API em http://127.0.0.1:porta (dev/testes)
  python app.py --mock          dados sinteticos (sem SD/boot9) — combinavel com --serve
  python app.py --sd CAMINHO    usa esse caminho como raiz do SD (ex.: o sandbox)
"""
import copy
import hashlib
import json
import struct
import sys
import tempfile
import time
from pathlib import Path

from core.icons import (cache_index, icon_png_b64, smdh_entry, smdh_short_name,
                        twl_icon_png_b64, twl_short_name)
from core.launcher import Launcher, parse as parse_launcher
from core.savedata import SaveData, assign_positions
from core.sdcard import NAND_SAVE_IDS, Save3ds, find_console, find_sd_drive
from core.store import Backups, Staging

ROOT = Path(__file__).parent
UI = ROOT / "ui"
APP_DIR = Path.home() / "3DSort"

# sub-estado do staging que vive no Launcher.dat (NAND); o resto e SaveData.dat (SD)
LAUNCHER_KEYS = ("nand_pos", "nand_folder", "folder_defs", "cart_pos")


class Api:
    """Camada unica consumida pela ponte js_api do pywebview e pelo modo --serve."""

    def __init__(self, save3ds: Save3ds, sd_root: Path | None, workdir: Path,
                 backups: Backups, launcher: Path | None = None,
                 container: Path | None = None):
        self.save3ds = save3ds
        self.sd_root = sd_root
        self.workdir = Path(workdir)
        self.backups = backups
        self.launcher_path = launcher      # Launcher.dat plano (fallback read-only)
        self.container_path = container    # homemenu_save.bin (system save, editavel)
        self.console = None
        self.staging = None
        self._names = {}
        self._icons = {}
        self._unknown_holes = {}   # {conteiner: {pos abaixo do max sem dono conhecido}}
        self._launcher_writable = False
        self._launcher_raw = None      # bytes do Launcher.dat como carregado
        self._launcher_baseline = None  # sub-estado launcher no load (p/ dirty check)
        self._container_sha = None     # sha do container no parse (gate anti-obsoleto)

    # ---- ciclo de vida -------------------------------------------------
    def import_sd(self):
        """(Re)le o layout do SD para o workdir e reinicia o staging."""
        if self.sd_root is None:
            self.sd_root = find_sd_drive()
        if self.sd_root is None:
            return {"error": "SD do 3DS nao encontrado"}
        self.console = find_console(self.sd_root)
        self._check_inject_receipt()
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
        st = {"order": order,
              "folders": {e.slot: e.folder for e in sd.entries},
              "tids": {e.slot: e.tid for e in sd.entries},
              "nand_tids": {}, "nand_pos": {}, "nand_folder": {},
              "folder_defs": {}, "cart_pos": None}
        launcher_raw = self._read_launcher()
        if launcher_raw:
            entries, lfolders, cart = parse_launcher(launcher_raw)
            st["nand_tids"] = {e.slot: e.tid for e in entries}
            st["nand_pos"] = {e.slot: e.pos for e in entries}
            st["nand_folder"] = {e.slot: e.folder for e in entries}
            st["folder_defs"] = {f.id: {"pos": f.pos, "name": f.name, "rows": f.rows}
                                 for f in lfolders}
            st["cart_pos"] = cart
        self._launcher_raw = launcher_raw
        self._launcher_baseline = copy.deepcopy({k: st[k] for k in LAUNCHER_KEYS})
        self.staging = Staging(st)
        # Com launcher, TODO ocupante e conhecido (jogos por tid+pos; NAND,
        # pastas e cart no Launcher) — buraco e vaga livre real (gate 0C).
        # SEM launcher, buracos podem ter dono invisivel (apps NAND inferidos):
        # ficam reservados e viram placeholders "System app".
        if launcher_raw:
            self._unknown_holes = {}
        else:
            occ = {}
            for e in sd.entries:
                occ.setdefault(e.folder, set()).add(e.pos)
            if st["cart_pos"] is not None:
                occ.setdefault(-1, set()).add(st["cart_pos"])
            holes = {c: set(range(max(ps) + 1)) - ps for c, ps in occ.items()}
            self._unknown_holes = {c: h for c, h in holes.items() if h}

    def _nand_save_id(self) -> str:
        region = self.console.region if self.console else "USA"
        return NAND_SAVE_IDS[region]

    def _find_container(self) -> Path | None:
        cands = []
        if self.sd_root is not None:
            sd3 = Path(self.sd_root) / "3DSort"
            if self._pending_inject_info():
                # ha escrita publicada: o container GERADO e a verdade do app
                cands.append(sd3 / "homemenu_save_new.bin")
            cands.append(sd3 / "homemenu_save.bin")
        if self.container_path:  # explicito (build_api: sandbox/APP_DIR; mock: tmp)
            cands.append(Path(self.container_path))
        return next((p for p in cands if p.exists()), None)

    def _read_launcher(self) -> bytes | None:
        """Container (editavel, via save3ds --nandsave) > arquivo plano (read-only)."""
        self._launcher_writable = False
        self._container_sha = None
        cont = self._find_container()
        if cont is not None:
            import shutil
            self.container_path = cont
            nand = self.save3ds.build_nand_tree(self.workdir, cont, self._nand_save_id())
            out = self.workdir / "launcher_read"
            if out.exists():
                shutil.rmtree(out)
            self.save3ds.nand_extract(self._nand_save_id(), nand, out)
            self._container_sha = hashlib.sha256(cont.read_bytes()).hexdigest()
            self._launcher_writable = True
            return (out / "Launcher.dat").read_bytes()
        if self.launcher_path and Path(self.launcher_path).exists():
            return Path(self.launcher_path).read_bytes()
        return None

    # ---- leitura -------------------------------------------------------
    def _reserved_now(self, st) -> dict:
        """Reservas dinamicas: buracos sem dono ∪ posicoes STAGED de NAND/pasta/cart."""
        res = {c: set(ps) for c, ps in self._unknown_holes.items()}
        for slot, p in st["nand_pos"].items():
            res.setdefault(st["nand_folder"][slot], set()).add(p)
        for d in st["folder_defs"].values():
            res.setdefault(-1, set()).add(d["pos"])
        if st["cart_pos"] is not None:
            res.setdefault(-1, set()).add(st["cart_pos"])
        return res

    def _launcher_dirty(self, st) -> bool:
        return any(st[k] != self._launcher_baseline[k] for k in LAUNCHER_KEYS)

    def get_state(self):
        if self.staging is None:
            r = self.import_sd()
            if "error" in r:
                return r
        st = self.staging.state
        # mesma atribuicao que write_sd fara: posicao por conteiner, pulando reservas
        pos_map = assign_positions(st["order"], st["folders"], self._reserved_now(st))
        items = []
        for slot in st["order"]:
            tid = st["tids"][slot]
            items.append({
                "key": f"g:{slot}", "slot": slot, "pos": pos_map[slot],
                "tid": f"{tid:016x}", "folder": st["folders"][slot],
                "name": self._names.get(tid, f"{tid:016x}"),
                "icon": self._icons.get(tid),
            })
        pinned = not self._launcher_writable
        system = [{"key": f"n:{slot}", "slot": slot, "tid": f"{tid:016x}",
                   "pos": st["nand_pos"][slot], "folder": st["nand_folder"][slot],
                   "pinned": pinned, "name": self._names.get(tid, "System"),
                   "icon": self._icons.get(tid)}
                  for slot, tid in st["nand_tids"].items()]
        if st["cart_pos"] is not None:
            system.append({"key": "cart", "slot": None, "tid": None,
                           "pos": st["cart_pos"], "folder": -1, "pinned": pinned,
                           "name": "Game Card", "icon": None})
        # buracos abaixo do maximo: sem Launcher.dat o dono e desconhecido ("System
        # app"); com Launcher.dat sao vagas livres do grid ("hole": o console mostra
        # um espaco vazio ali). Ambos ficam reservados: nada e realocado para eles.
        hole = self._launcher_raw is not None
        system += [{"key": None, "slot": None, "tid": None, "pos": p, "folder": -1,
                    "pinned": True, "hole": hole,
                    "name": "Empty slot" if hole else "System app", "icon": None}
                   for p in sorted(self._unknown_holes.get(-1, set()))]
        system.sort(key=lambda s: (s["folder"], s["pos"]))
        return {
            "items": items,
            "system": system,
            "folderNames": {fid: d["name"] for fid, d in st["folder_defs"].items()},
            "folderPos": {fid: d["pos"] for fid, d in st["folder_defs"].items()},
            "folderRows": {fid: d["rows"] for fid, d in st["folder_defs"].items()},
            "launcherWritable": self._launcher_writable,
            "launcherDirty": self._launcher_dirty(st),
            "pendingInject": self._pending_inject_info(),
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

    @staticmethod
    def _key(k) -> tuple[str, int | None]:
        """int ou 'g:N' -> ('g',N); 'n:N' -> ('n',N); 'f:N' -> ('f',N); 'cart'."""
        if isinstance(k, int):
            return ("g", k)
        if k == "cart":
            return ("cart", None)
        if isinstance(k, str) and ":" in k:
            kind, _, n = k.partition(":")
            if kind in ("g", "n", "f") and n.lstrip("-").isdigit():
                return (kind, int(n))
        raise ValueError(f"invalid entity key: {k!r}")

    def _require_writable(self):
        if not self._launcher_writable:
            raise ValueError("System layout is read-only. Dump the HOME menu "
                             "system save first (see the SYNC tab).")

    def _entity_pos(self, st) -> dict:
        """{(kind, n): (conteiner, pos)} para todas as entidades staged."""
        pos_map = assign_positions(st["order"], st["folders"], self._reserved_now(st))
        out = {("g", s): (st["folders"][s], pos_map[s]) for s in st["order"]}
        for slot, p in st["nand_pos"].items():
            out[("n", slot)] = (st["nand_folder"][slot], p)
        for fid, d in st["folder_defs"].items():
            out[("f", fid)] = (-1, d["pos"])
        if st["cart_pos"] is not None:
            out[("cart", None)] = (-1, st["cart_pos"])
        return out

    def _label(self, st, key) -> str:
        kind, n = key
        if kind == "g":
            return self._names.get(st["tids"][n], str(n))
        if kind == "n":
            return self._names.get(st["nand_tids"][n], "System")
        if kind == "f":
            return st["folder_defs"][n]["name"]
        return "Game Card"

    def _next_free(self, st, container: int, taken=()) -> int:
        used = {p for c, p in self._entity_pos(st).values() if c == container}
        used |= self._unknown_holes.get(container, set()) | set(taken)
        return next(p for p in range(len(used) + 1) if p not in used)

    def move_item(self, slot: int, before_slot: int | None):
        order = [s for s in self.staging.state["order"] if s != slot]
        i = order.index(before_slot) if before_slot is not None else len(order)
        order.insert(i, slot)
        tid = self.staging.state["tids"][slot]
        return self._commit(f"Moved {self._names.get(tid, slot)}", order=order)

    def swap_items(self, a, b):
        """Troca exata de lugar entre dois tiles de qualquer tipo — ninguem mais se move."""
        ka, kb = self._key(a), self._key(b)
        st = self.staging.state
        if ka[0] == "g" and kb[0] == "g":
            slot_a, slot_b = ka[1], kb[1]
            order = list(st["order"])
            i, j = order.index(slot_a), order.index(slot_b)
            order[i], order[j] = order[j], order[i]
            folders = dict(st["folders"])
            folders[slot_a], folders[slot_b] = folders[slot_b], folders[slot_a]
            return self._commit(
                f"Swapped {self._label(st, ka)} <-> {self._label(st, kb)}",
                order=order, folders=folders)
        self._require_writable()
        pos_of = self._entity_pos(st)
        (ca, pa), (cb, pb) = pos_of[ka], pos_of[kb]
        for key, dest in ((ka, cb), (kb, ca)):
            if key[0] in ("f", "cart") and dest != -1:
                raise ValueError("Folders and the Game Card can only sit on the home grid.")
        changes, desired = {}, {}
        for key, cont, pos in ((ka, cb, pb), (kb, ca, pa)):
            self._place(st, changes, desired, key, cont, pos)
        if desired:
            self._rebuild_order(st, changes, desired, pos_of)
        return self._commit(
            f"Swapped {self._label(st, ka)} <-> {self._label(st, kb)}", **changes)

    def _place(self, st, changes, desired, key, cont, pos):
        kind, n = key
        if kind == "g":
            desired[n] = (cont, pos)
        elif kind == "n":
            changes.setdefault("nand_pos", dict(st["nand_pos"]))[n] = pos
            changes.setdefault("nand_folder", dict(st["nand_folder"]))[n] = cont
        elif kind == "f":
            fd = changes.setdefault("folder_defs", copy.deepcopy(st["folder_defs"]))
            fd[n]["pos"] = pos
        else:
            changes["cart_pos"] = pos

    def _rebuild_order(self, st, changes, desired, pos_of):
        """Reconstroi order/folders para que assign_positions reproduza as posicoes
        desejadas. Valido porque todo buraco abaixo do maximo e reservado: o conjunto
        de posicoes livres por conteiner e exatamente o conjunto ocupado pelos jogos."""
        base = {s: desired.get(s, pos_of[("g", s)]) for s in st["order"]}
        changes["order"] = [s for s, _ in sorted(base.items(),
                                                 key=lambda kv: (kv[1][1], kv[0]))]
        folders = dict(st["folders"])
        for s, (cont, _) in desired.items():
            folders[s] = cont
        changes["folders"] = folders

    def set_folder(self, key, folder: int):
        st = self.staging.state
        kind, n = self._key(key)
        if folder != -1 and st["folder_defs"] and folder not in st["folder_defs"]:
            raise ValueError(f"Folder {folder} does not exist.")
        verb = "Removed from folder" if folder == -1 else "Moved into folder"
        if kind == "g":
            folders = dict(st["folders"])
            folders[n] = folder
            return self._commit(f"{verb}: {self._label(st, (kind, n))}", folders=folders)
        if kind == "n":
            self._require_writable()
            nand_pos = dict(st["nand_pos"])
            nand_folder = dict(st["nand_folder"])
            nand_folder[n] = folder
            # posicao explicita no conteiner de destino: menor livre
            probe = {**st, "nand_pos": {k: v for k, v in nand_pos.items() if k != n},
                     "nand_folder": nand_folder}
            nand_pos[n] = self._next_free(probe, folder)
            return self._commit(f"{verb}: {self._label(st, (kind, n))}",
                                nand_pos=nand_pos, nand_folder=nand_folder)
        raise ValueError("Folders and the Game Card cannot go inside folders.")

    # ---- pastas (lifecycle, staged) --------------------------------------
    def folder_create(self):
        self._require_writable()
        st = self.staging.state
        referenced = set(st["folders"].values()) | set(st["nand_folder"].values())
        free = [i for i in range(60) if i not in st["folder_defs"] and i not in referenced]
        if not free:
            raise ValueError("No free folder slot (60 in use).")
        fid = free[0]
        home = {p for c, p in self._entity_pos(st).values() if c == -1}
        home |= self._unknown_holes.get(-1, set())
        pos = max(home) + 1 if home else 0
        if pos >= 360:
            raise ValueError("Home grid is full.")
        defs = copy.deepcopy(st["folder_defs"])
        defs[fid] = {"pos": pos, "name": "New folder", "rows": 2}
        return self._commit("Created folder", folder_defs=defs)

    def folder_rename(self, fid: int, name: str):
        self._require_writable()
        st = self.staging.state
        if fid not in st["folder_defs"]:
            raise ValueError(f"Folder {fid} does not exist.")
        if not name or len(name.encode("utf-16-le")) > 0x20:
            raise ValueError("Folder name must be 1 to 16 characters.")
        defs = copy.deepcopy(st["folder_defs"])
        old = defs[fid]["name"]
        defs[fid]["name"] = name
        return self._commit(f"Renamed folder {old} to {name}", folder_defs=defs)

    def _return_members_home(self, st, fid, changes):
        """Membros da pasta voltam ao home: jogos no fim da ordem, NAND depois deles."""
        game_members = [s for s in st["order"] if st["folders"][s] == fid]
        folders = dict(st["folders"])
        for s in game_members:
            folders[s] = -1
        changes["folders"] = folders
        changes["order"] = ([s for s in st["order"] if s not in game_members]
                            + game_members)
        nand_members = [s for s, f in st["nand_folder"].items() if f == fid]
        if nand_members:
            nand_pos = dict(st["nand_pos"])
            nand_folder = dict(st["nand_folder"])
            taken = []
            for s in nand_members:
                nand_folder[s] = -1
                probe = {**st, **changes,
                         "nand_pos": {k: v for k, v in nand_pos.items()
                                      if k not in nand_members},
                         "nand_folder": nand_folder}
                nand_pos[s] = self._next_free(probe, -1, taken=taken)
                taken.append(nand_pos[s])
            changes["nand_pos"] = nand_pos
            changes["nand_folder"] = nand_folder

    def folder_empty(self, fid: int):
        self._require_writable()
        st = self.staging.state
        if fid not in st["folder_defs"]:
            raise ValueError(f"Folder {fid} does not exist.")
        changes = {}
        self._return_members_home(st, fid, changes)
        return self._commit(f"Emptied folder {st['folder_defs'][fid]['name']}", **changes)

    def folder_delete(self, fid: int):
        self._require_writable()
        st = self.staging.state
        if fid not in st["folder_defs"]:
            raise ValueError(f"Folder {fid} does not exist.")
        defs = copy.deepcopy(st["folder_defs"])
        name = defs.pop(fid)["name"]
        # defs sem a pasta ANTES de reposicionar membros: o tile liberado
        # entra na compactacao e os membros ocupam as menores posicoes reais
        changes = {"folder_defs": defs}
        self._return_members_home(st, fid, changes)
        return self._commit(f"Deleted folder {name}", **changes)

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

    # ---- SD + NAND ---------------------------------------------------------
    def backup_manual(self):
        self.backups.create(self.workdir / "extract", kind="manual",
                            note="backup manual", extra=self._backup_extra())
        return self.get_state()

    def _backup_extra(self) -> dict:
        """Launcher/container entram no zip fora da arvore de extdata (__nand__/)."""
        extra = {}
        if self._launcher_raw:
            extra["__nand__/Launcher.dat"] = self._launcher_raw
        if self._launcher_writable and self.container_path:
            extra["__nand__/homemenu_save.bin"] = Path(self.container_path)
        return extra

    def restore_backup(self, backup_id: str):
        import shutil
        ext = self.workdir / "extract"
        self.backups.restore(backup_id, ext)
        restored_launcher = None
        nand_dir = ext / "__nand__"
        if nand_dir.exists():  # tirar do extract ANTES do proximo import para o SD
            lp = nand_dir / "Launcher.dat"
            restored_launcher = lp.read_bytes() if lp.exists() else None
            shutil.rmtree(nand_dir)
        # cinto para backups legados sem entries de diretorio no zip: o extdata
        # nunca pode ir ao SD sem boss/ (o HOME reconstruiria o SaveData, Fase 0C)
        (ext / "boss").mkdir(exist_ok=True)
        self._load(ext)
        # restaurar e um estado novo em relacao ao SD: precisa ficar staged para o WRITE
        if restored_launcher and self._launcher_writable:
            entries, lfolders, cart = parse_launcher(restored_launcher)
            self.staging.commit(f"Restored backup {backup_id}", {
                **self.staging.state,
                "nand_tids": {e.slot: e.tid for e in entries},
                "nand_pos": {e.slot: e.pos for e in entries},
                "nand_folder": {e.slot: e.folder for e in entries},
                "folder_defs": {f.id: {"pos": f.pos, "name": f.name, "rows": f.rows}
                                for f in lfolders},
                "cart_pos": cart,
            })
        else:
            self.staging.commit(f"Restored backup {backup_id}", self.staging.state)
        return self.get_state()

    def write_sd(self):
        """Aplica o staging ao SaveData.dat (e, se preciso, ao Launcher.dat) e importa.
        Backup antes, sempre. All-or-nothing: os dois arquivos saem do MESMO snapshot;
        se o ramo launcher falhar, o staging NAO e limpo e o retry e idempotente."""
        n = len(self.staging.staged)
        if n == 0:
            return {"error": "nada staged"}
        st = self.staging.state
        dirty = self._launcher_dirty(st)
        if dirty:
            self._require_writable()
            cur = hashlib.sha256(Path(self.container_path).read_bytes()).hexdigest()
            if cur != self._container_sha:
                return {"error": "System save changed on disk. Re-dump it in "
                                 "GodMode9 and re-import before writing."}
            # ancora do gate 2 so vale se veio de dump fresco do GM9 (cp --hash).
            # Copia promovida pos-inject nao tem .sha de proposito: qualquer boot
            # do HOME drifta bytes volateis da NAND (observado na Fase 0C)
            sha_file = Path(str(self.container_path) + ".sha")
            if not sha_file.exists() or sha_file.read_bytes() != bytes.fromhex(cur):
                return {"error": "No fresh GodMode9 dump of the system save "
                                 "(missing or stale homemenu_save.bin.sha). Run "
                                 "3DSort_dump in GodMode9, then Import from SD."}
        ext = self.workdir / "extract"
        self.backups.create(ext, kind="auto", note=f"antes de escrever {n} mudancas",
                            extra=self._backup_extra())
        sav_path = ext / "user" / "SaveData.dat"
        sd = SaveData(sav_path.read_bytes())
        # tema/configs (0x13B8+) sempre da versao ATUAL do cartao: o extract do
        # workdir pode ser anterior a mudancas feitas no console (ex.: tema) e
        # nem restore nem write podem regredi-las. Best-effort: sem SD legivel,
        # escreve com o que temos.
        try:
            import shutil
            fresh = self.workdir / "write_base"
            if fresh.exists():
                shutil.rmtree(fresh)
            self.save3ds.extract(self.console.extdata_id, self.sd_root, fresh)
            sd.graft_tail((fresh / "user" / "SaveData.dat").read_bytes())
        except Exception:
            pass
        # pastas primeiro: apply_order distribui posicoes pelo conteiner ATUAL
        for slot, folder in st["folders"].items():
            sd.set_folder(int(slot), folder)
        sd.apply_order(list(st["order"]), reserved=self._reserved_now(st))
        # sempre desembrulhar: 0 no array de status desfaz o gift box de todos
        # os icones (mecanismo do Cthulhu); o console re-marca "novo" se quiser
        sd.set_all_status(0)
        # gate 0B: pasta nova ganha nº de batismo = contador do Launcher atual
        # (mesma fonte que _write_launcher incrementa; delete deixa orfao)
        new_fids = sorted(set(st["folder_defs"]) -
                          set(self._launcher_baseline["folder_defs"]))
        if new_fids and self._launcher_raw:
            n0 = Launcher(self._launcher_raw).next_folder_number
            for i, fid in enumerate(new_fids):
                sd.set_folder_number(fid, n0 + i)
        sav_path.write_bytes(sd.serialize())
        self.save3ds.import_(self.console.extdata_id, self.sd_root, ext)
        if dirty:
            self._write_launcher(st, n)
        self.staging.clear()
        self._launcher_baseline = copy.deepcopy({k: st[k] for k in LAUNCHER_KEYS})
        return self.get_state()

    def _write_launcher(self, st, n_changes: int):
        """Edita o Launcher.dat dentro do container e publica no SD o payload de
        injecao (homemenu_save_new.bin + .sha + scripts GM9). A NAND real so muda
        quando o USUARIO rodar o script de injecao no GodMode9."""
        import shutil
        save_id = self._nand_save_id()
        nand = self.save3ds.build_nand_tree(self.workdir, Path(self.container_path),
                                            save_id)
        out = self.workdir / "launcher_write"
        if out.exists():
            shutil.rmtree(out)
        self.save3ds.nand_extract(save_id, nand, out)
        ln = Launcher((out / "Launcher.dat").read_bytes())
        for slot in st["nand_tids"]:
            ln.set_position(slot, st["nand_pos"][slot])
            ln.set_folder(slot, st["nand_folder"][slot])
        baseline_fids = set(self._launcher_baseline["folder_defs"])
        for fid, d in st["folder_defs"].items():
            ln.set_folder_name(fid, d["name"])
            ln.set_folder_rows(fid, d["rows"])
            ln.set_folder_pos(fid, d["pos"])
        for fid in baseline_fids - set(st["folder_defs"]):
            ln.delete_folder(fid)
        new_fids = set(st["folder_defs"]) - baseline_fids
        if new_fids:
            ln.set_next_folder_number(ln.next_folder_number + len(new_fids))
        ln.set_cart_pos(st["cart_pos"])
        ln.validate(active_sd_refs=set(st["folders"].values()))
        (out / "Launcher.dat").write_bytes(ln.serialize())
        self.save3ds.nand_import(save_id, nand, out)
        new_container = Save3ds.nand_container(nand, save_id)
        sd3 = Path(self.sd_root) / "3DSort"
        sd3.mkdir(parents=True, exist_ok=True)
        payload = sd3 / "homemenu_save_new.bin"
        shutil.copy2(new_container, payload)
        digest = hashlib.sha256(payload.read_bytes()).digest()
        (sd3 / "homemenu_save_new.bin.sha").write_bytes(digest)
        scripts = Path(self.sd_root) / "gm9" / "scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        id0 = self.console.id0
        (scripts / "3DSort_dump.gm9").write_text(gm9_dump_script(id0, save_id),
                                                 encoding="ascii", newline="\n")
        (scripts / "3DSort_inject.gm9").write_text(gm9_inject_script(id0, save_id),
                                                   encoding="ascii", newline="\n")
        self._pending_path().write_text(json.dumps({
            "sha": digest.hex(), "when": time.strftime("%Y-%m-%d %H:%M:%S"),
            "changes": n_changes}), encoding="utf-8")

    # ---- injecao pendente (NAND) -------------------------------------------
    def _pending_path(self) -> Path:
        return self.workdir / "pending_inject.json"

    def _pending_inject_info(self) -> dict | None:
        p = self._pending_path()
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def _check_inject_receipt(self) -> bool:
        """Recibo do script GM9 confirma a injecao: promove o container gerado a
        dump corrente e limpa o estado pendente."""
        info = self._pending_inject_info()
        if not info or self.sd_root is None:
            return False
        sd3 = Path(self.sd_root) / "3DSort"
        receipt = sd3 / "inject_done.sha"
        payload = sd3 / "homemenu_save_new.bin"
        if not (receipt.exists() and payload.exists()):
            return False
        if receipt.read_bytes() != bytes.fromhex(info["sha"]):
            return False
        self._promote_payload(sd3)
        receipt.unlink(missing_ok=True)
        self._pending_path().unlink(missing_ok=True)
        return True

    @staticmethod
    def _promote_payload(sd3: Path):
        """O container gerado vira o dump corrente (verdade ESTRUTURAL). As
        ancoras .sha sao descartadas de proposito: qualquer boot do HOME drifta
        bytes volateis da NAND (Fase 0C), entao so um novo 3DSort_dump gera
        ancora valida para a proxima escrita de launcher."""
        import shutil
        payload = sd3 / "homemenu_save_new.bin"
        if payload.exists():
            shutil.move(str(payload), sd3 / "homemenu_save.bin")
        (sd3 / "homemenu_save_new.bin.sha").unlink(missing_ok=True)
        (sd3 / "homemenu_save.bin.sha").unlink(missing_ok=True)

    def verify_inject(self):
        if self._pending_inject_info() is None:
            return self.get_state()
        if self._check_inject_receipt():
            return self.import_sd()
        return {"error": "No inject receipt found. Run the 3DSort_inject script "
                         "in GodMode9, then verify again."}

    def confirm_inject(self):
        """Override manual: usuario garante que injetou sem recibo."""
        if self._pending_inject_info() is not None and self.sd_root is not None:
            sd3 = Path(self.sd_root) / "3DSort"
            self._promote_payload(sd3)
            (sd3 / "inject_done.sha").unlink(missing_ok=True)
        self._pending_path().unlink(missing_ok=True)
        return self.import_sd()


# ---- scripts GodMode9 (gerados por console: id0 e regiao conhecidos) --------
def gm9_dump_script(id0: str, save_id: str) -> str:
    """Copia o system save do HOME menu para o SD. cp -h gera o .sha ao lado,
    que e a ancora anti-obsolescencia do script de injecao."""
    return f"""# 3DSort: dump the HOME menu system save to the SD card
set SAVE "1:/data/{id0}/sysdata/{save_id}/00000000"
if not exist $[SAVE]
\techo "HOME menu save not found. Wrong console or region?"
\tgoto End
end
cp --hash --overwrite --no_cancel $[SAVE] 0:/3DSort/homemenu_save.bin
echo "Dumped. Edit the layout in 3DSort on the PC, then run 3DSort_inject."
@End
"""


def gm9_inject_script(id0: str, save_id: str) -> str:
    """Injeta o container editado. Cada sha e um gate duro: o script aborta no
    primeiro que falhar, entao um estado inconsistente nunca chega a NAND."""
    return f"""# 3DSort: inject the edited HOME menu system save into the NAND
set SAVE "1:/data/{id0}/sysdata/{save_id}/00000000"
ask "Write the 3DSort layout to the console NAND?"
# gate 1: payload esta integro (a escrita do PC terminou)
sha 0:/3DSort/homemenu_save_new.bin 0:/3DSort/homemenu_save_new.bin.sha
# gate 2: a NAND continua exatamente como no dump (aborta se o HOME bootou no meio)
sha $[SAVE] 0:/3DSort/homemenu_save.bin.sha
allow $[SAVE]
cp --overwrite --no_cancel 0:/3DSort/homemenu_save_new.bin $[SAVE]
# gate 3: a copia chegou bit-perfeita; so entao consertar o CMAC
sha $[SAVE] 0:/3DSort/homemenu_save_new.bin.sha
fixcmac $[SAVE]
# recibo para o app confirmar a injecao no proximo import
cp --overwrite --no_cancel 0:/3DSort/homemenu_save_new.bin.sha 0:/3DSort/inject_done.sha
echo "Injected. You can boot the HOME menu now."
"""


# ---- mock: mesma Api, crypto fake -------------------------------------------
class FakeSave3ds(Save3ds):
    """Simula extract/import copiando uma arvore de extdata ja 'decriptada'.
    No canal NAND, o 'container' mock e um arquivo cujos bytes SAO o Launcher.dat."""

    def __init__(self, plain_dir: Path):
        self.plain = Path(plain_dir)

    def extract(self, extdata_id, sd_root, out_dir):
        import shutil
        shutil.copytree(self.plain, out_dir, dirs_exist_ok=True)

    def import_(self, extdata_id, sd_root, src_dir):
        import shutil
        shutil.copytree(src_dir, self.plain, dirs_exist_ok=True)

    def build_nand_tree(self, workdir, container, save_id):
        import shutil
        save_dir = Path(workdir) / "nand" / "data" / "mock" / "sysdata" / save_id
        save_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(container, save_dir / "00000000")
        return Path(workdir) / "nand"

    def nand_extract(self, save_id, nand_root, out_dir):
        import shutil
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.nand_container(nand_root, save_id),
                     Path(out_dir) / "Launcher.dat")

    def nand_import(self, save_id, nand_root, src_dir):
        import shutil
        shutil.copy2(Path(src_dir) / "Launcher.dat",
                     self.nand_container(nand_root, save_id))


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
MOCK_CART_POS = 17                   # depois dos 12 jogos (3-7, 10-16)


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
             {p for _, p, _ in MOCK_FOLDERS} | {MOCK_CART_POS})
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
    struct.pack_into("<H", buf, ln.OFF_CART_POS, MOCK_CART_POS)
    for i in range(ln.SLOTS):
        struct.pack_into("<h", buf, ln.OFF_POS + i * 2, -1)
        struct.pack_into("<b", buf, ln.OFF_FOLDER + i, -1)
    for i in range(ln.FOLDERS):
        struct.pack_into("<h", buf, ln.OFF_FOLDER_POS + i * 2, -1)
    struct.pack_into("<I", buf, ln.OFF_NEXT_FOLDER_NUM, len(MOCK_FOLDERS) + 1)
    buf[ln.OFF_NEXT_FOLDER_NUM_MIRROR] = len(MOCK_FOLDERS) + 1
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
    # par bin+sha como o cp --hash do GM9 deixa (ancora de dump fresco)
    Path(str(path) + ".sha").write_bytes(hashlib.sha256(bytes(buf)).digest())


def build_api(mock: bool, sd_root: Path | None = None,
              no_launcher: bool = False) -> Api:
    if mock:
        tmp = Path(tempfile.mkdtemp(prefix="3dsort-mock-"))
        plain = tmp / "plain"
        make_mock_extdata(plain)
        # arvore fake de SD para o fluxo real de find_console funcionar
        fake_sd = tmp / "sd"
        (fake_sd / "Nintendo 3DS" / ("0" * 32) / ("1" * 32) / "extdata" /
         "00000000" / "0000008f").mkdir(parents=True)
        container = None
        if not no_launcher:
            # container mock = bytes do Launcher.dat (ver FakeSave3ds)
            container = tmp / "homemenu_save.bin"
            make_mock_launcher(container)
        return Api(FakeSave3ds(plain), fake_sd, tmp / "work", Backups(tmp / "backups"),
                   container=container)
    workdir = APP_DIR / "work"
    workdir.mkdir(parents=True, exist_ok=True)
    sandbox_keys = ROOT / "sandbox" / "keys"
    launcher = container = None
    if not no_launcher:
        launcher = next((p for p in (sandbox_keys / "Launcher.dat",
                                     APP_DIR / "Launcher.dat") if p.exists()), None)
        container = next((p for p in (sandbox_keys / "homemenu_save.bin",
                                      APP_DIR / "homemenu_save.bin") if p.exists()), None)
    return Api(
        Save3ds(ROOT / "tools" / "save3ds" / "save3ds_fuse.exe",
                sandbox_keys / "boot9.bin", sandbox_keys / "movable.sed"),
        sd_root, workdir, Backups(APP_DIR / "backups"), launcher=launcher,
        container=container)


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
    api = build_api(mock="--mock" in args, sd_root=sd,
                    no_launcher="--no-launcher" in args)
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
