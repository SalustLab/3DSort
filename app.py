"""3DSort — desktop app (pywebview) and --serve dev mode for Playwright tests.

Usage:
  python app.py                 native window (real SD, if found)
  python app.py --serve [port]  UI + API at http://127.0.0.1:port (dev/tests)
  python app.py --mock          synthetic data (no SD/boot9) — combinable with --serve
  python app.py --sd PATH       use this path as the SD root (e.g. the sandbox)
  python app.py --selftest      checks bundled resources, exits 0 when all present
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
from core.sdcard import (NAND_SAVE_IDS, SAVE3DS_NAME, Save3ds, find_console,
                         find_sd_drive, id0_from_movable, list_3ds_roots)
from core.store import Backups, Staging
from core import titledates

ROOT = Path(__file__).parent
UI = ROOT / "ui"
APP_DIR = Path.home() / "3DSort"

# staging sub-state that lives in Launcher.dat (NAND); the rest is SaveData.dat (SD)
LAUNCHER_KEYS = ("nand_pos", "nand_folder", "folder_defs", "cart_pos")


class Api:
    """Single layer consumed by the pywebview js_api bridge and by --serve mode."""

    def __init__(self, save3ds: Save3ds, sd_root: Path | None, workdir: Path,
                 backups: Backups, launcher: Path | None = None,
                 container: Path | None = None):
        self.save3ds = save3ds
        self.sd_root = sd_root
        self.workdir = Path(workdir)
        self.backups = backups
        self.launcher_path = launcher      # flat Launcher.dat (read-only fallback)
        self.container_path = container    # homemenu_save.bin (system save, editable)
        self.console = None
        self.staging = None
        self._names = {}
        self._icons = {}
        self._unknown_holes = {}   # {container: {pos below max with no known owner}}
        self._launcher_writable = False
        self._launcher_raw = None      # Launcher.dat bytes as loaded
        self._launcher_baseline = None  # launcher sub-state at load (for dirty check)
        self._container_sha = None     # container sha at parse (anti-stale gate)

    # ---- lifecycle -------------------------------------------------
    def import_sd(self):
        """(Re)reads the SD layout into the workdir and resets the staging."""
        if self.sd_root is None:
            self.sd_root = find_sd_drive()
        elif not (Path(self.sd_root) / "Nintendo 3DS").is_dir():
            # drive letter can change between runs: re-autodetect
            self.sd_root = find_sd_drive() or self.sd_root
        if self.sd_root is None:
            return {"error": "3DS SD card not found"}
        # the movable dumped on the card names the console that owns it: it is the
        # only way to tell the live id0 from leftovers of older states/consoles
        sd_id0 = self._sd_movable_id0()
        self.console = find_console(self.sd_root, prefer_id0=sd_id0)
        # script goes to the SD BEFORE requiring keys: the dump itself is what
        # brings boot9/movable/container for the app to read (no manual copy)
        self._publish_dump_script()
        err = self._resolve_keys()
        if err:
            return {"error": err}
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
            n = smdh_short_name(e) or twl_short_name(e)  # TWL = DSiWare (NDS banner)
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
        # With a launcher, EVERY occupant is known (games by tid+pos; NAND,
        # folders and cart in the Launcher): a hole is a truly free slot (gate 0C).
        # WITHOUT a launcher, holes may have an invisible owner (inferred NAND
        # apps): they stay reserved and become "System app" placeholders.
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

    def _publish_dump_script(self):
        """Publishes 3DSort_dump.gm9 to the SD on every import. It is what spits
        container + keys into 0:/3DSort: the user never copies a file by hand."""
        scripts = Path(self.sd_root) / "gm9" / "scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        (scripts / "3DSort_dump.gm9").write_text(
            gm9_dump_script(), encoding="ascii", newline="\n")

    def _sd_key_file(self, name: str) -> Path | None:
        """Key dumped on the card by 3DSort_dump (0:/3DSort), then the gm9 output
        folder. Nothing here when the user has not run the script yet."""
        if self.sd_root is None:
            return None
        dirs = (Path(self.sd_root) / "3DSort", Path(self.sd_root) / "gm9" / "out")
        return next((d / name for d in dirs if (d / name).is_file()), None)

    def _sd_movable_id0(self) -> str | None:
        """id0 of the console that owns the movable.sed sitting on the card."""
        movable = self._sd_key_file("movable.sed")
        return id0_from_movable(movable.read_bytes()) if movable else None

    def _resolve_keys(self) -> str | None:
        """Resolves boot9/movable: the SD (0:/3DSort from the dump, then gm9/out)
        takes precedence over the build_api paths. Validates the movable against
        the folder's id0 (old-key trap, CLAUDE.md §5.3). Returns a friendly error
        message or None."""
        if getattr(self.save3ds, "boot9", None) is None:  # mock uses no keys
            return None
        for name, attr in (("boot9.bin", "boot9"), ("movable.sed", "movable")):
            hit = self._sd_key_file(name)
            if hit is not None:
                setattr(self.save3ds, attr, hit)
        missing = [n for n, p in (("boot9.bin", self.save3ds.boot9),
                                  ("movable.sed", self.save3ds.movable))
                   if not Path(p).exists()]
        if missing:
            return ("Console keys not found (" + ", ".join(missing) + "). Run the "
                    "3DSort_dump script in GodMode9 (already on the SD in "
                    "gm9/scripts), then Import from SD again.")
        if (self.console is not None and
                id0_from_movable(Path(self.save3ds.movable).read_bytes())
                != self.console.id0):
            # find_console already preferred the folder matching this movable, so
            # reaching here means the console owning the key has no folder on the
            # card at all: either the key is stale, or the console never booted the
            # HOME menu with this card inserted (nothing to read yet).
            return ("movable.sed does not match this SD card. If this console is new "
                    "to the card, boot the HOME menu once with it inserted, then "
                    "Import from SD again. Otherwise the key is from an older console "
                    "state: re-dump it in GodMode9 (run 3DSort_dump).")
        return None

    def _find_container(self) -> Path | None:
        cands = []
        if self.sd_root is not None:
            sd3 = Path(self.sd_root) / "3DSort"
            if self._pending_inject_info():
                # a write is published: the GENERATED container is the app's truth
                cands.append(sd3 / "homemenu_save_new.bin")
            cands.append(sd3 / "homemenu_save.bin")
        if self.container_path:  # explicit (build_api: sandbox/APP_DIR; mock: tmp)
            cands.append(Path(self.container_path))
        return next((p for p in cands if p.exists()), None)

    def _read_launcher(self) -> bytes | None:
        """Container (editable, via save3ds --nandsave) > flat file (read-only)."""
        self._launcher_writable = False
        self._container_sha = None
        cont = self._find_container()
        if cont is not None:
            import shutil
            nand = self.save3ds.build_nand_tree(self.workdir, cont, self._nand_save_id())
            out = self.workdir / "launcher_read"
            if out.exists():
                shutil.rmtree(out)
            try:
                self.save3ds.nand_extract(self._nand_save_id(), nand, out)
            except RuntimeError:
                # container from another console (or another console state): its CMAC
                # does not verify with the current keys. The SD layout is still fine,
                # so degrade to the read-only fallback instead of failing the import.
                self.container_path = None
            else:
                self.container_path = cont
                self._container_sha = hashlib.sha256(cont.read_bytes()).hexdigest()
                self._launcher_writable = True
                return (out / "Launcher.dat").read_bytes()
        if self.launcher_path and Path(self.launcher_path).exists():
            return Path(self.launcher_path).read_bytes()
        return None

    # ---- reads -------------------------------------------------------
    def _reserved_now(self, st) -> dict:
        """Dynamic reservations: ownerless holes + STAGED NAND/folder/cart positions."""
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
        # same assignment write_sd will do: position per container, skipping reserved
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
        # holes below the maximum: without Launcher.dat the owner is unknown ("System
        # app"); with Launcher.dat they are free grid slots ("hole": the console shows
        # an empty space there). Both stay reserved: nothing gets relocated onto them.
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

    def get_setup_state(self):
        """Why the grid is not available yet, for the first-run wizard.
        Stages: ready | no_sd | no_keys | stale_keys | error."""
        if self.staging is not None:
            return {"stage": "ready", "detail": None}
        try:
            r = self.get_state()
        except Exception as e:   # find_console raises straight through on js_api
            r = {"error": str(e)}
        if "error" not in r:
            return {"stage": "ready", "detail": None}
        msg = r["error"]
        # order matters: the keys message also contains "not found"
        if "Console keys not found" in msg:
            stage = "no_keys"
        elif "does not match this SD" in msg:
            stage = "stale_keys"
        elif "not found" in msg:
            stage = "no_sd"
        else:
            stage = "error"
        return {"stage": stage, "detail": msg}

    def _sd_info(self):
        info = {"region": self.console.region if self.console else None,
                "root": str(self.sd_root) if self.sd_root else None}
        if self.sd_root is not None:
            try:
                import shutil
                du = shutil.disk_usage(self.sd_root)
                info["total_bytes"] = du.total
                info["used_bytes"] = du.used
                info["free_blocks"] = du.free // 131072  # 3DS block = 128 KB
            except OSError:
                pass
        return info

    # ---- mutations (staged) ----------------------------------------------
    def _commit(self, label, **changes):
        self.staging.commit(label, {**self.staging.state, **changes})
        return self.get_state()

    @staticmethod
    def _key(k) -> tuple[str, int | None]:
        """int or 'g:N' -> ('g',N); 'n:N' -> ('n',N); 'f:N' -> ('f',N); 'cart'."""
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
        """{(kind, n): (container, pos)} for every staged entity."""
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
        """Exact place swap between two tiles of any type: nothing else moves."""
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
        """Rebuilds order/folders so assign_positions reproduces the desired
        positions. Valid because every hole below the maximum is reserved: the set
        of free positions per container is exactly the set occupied by the games."""
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
            # explicit position in the destination container: lowest free
            probe = {**st, "nand_pos": {k: v for k, v in nand_pos.items() if k != n},
                     "nand_folder": nand_folder}
            nand_pos[n] = self._next_free(probe, folder)
            return self._commit(f"{verb}: {self._label(st, (kind, n))}",
                                nand_pos=nand_pos, nand_folder=nand_folder)
        raise ValueError("Folders and the Game Card cannot go inside folders.")

    # ---- folders (lifecycle, staged) -------------------------------------
    def folder_create(self, name=None):
        self._require_writable()
        st = self.staging.state
        if name is not None and name != "":
            if len(name.encode("utf-16-le")) > 0x20:
                raise ValueError("Folder name must be 1 to 16 characters.")
        else:
            name = "New folder"
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
        defs[fid] = {"pos": pos, "name": name, "rows": 2}
        return self._commit(f"Created folder {name}" if name != "New folder"
                            else "Created folder", folder_defs=defs)

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
        """Folder members return to home: games at the end of the order, NAND after."""
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
        # defs without the folder BEFORE repositioning members: the freed tile
        # joins the compaction and members take the lowest real positions
        changes = {"folder_defs": defs}
        self._return_members_home(st, fid, changes)
        return self._commit(f"Deleted folder {name}", **changes)

    def sort_preset(self, preset: str):
        labels = {"az": "A → Z", "za": "Z → A",
                  "date_asc": "Release date ↑", "date_desc": "Release date ↓"}
        if preset not in labels:
            raise ValueError(f"Unknown sort preset: {preset}")
        st = self.staging.state
        if preset in ("az", "za"):
            keyed = [(self._names.get(st["tids"][s], ""), s) for s in st["order"]]
            order = [s for _, s in sorted(keyed, key=lambda t: t[0].lower(),
                                          reverse=(preset == "za"))]
        else:
            # Titles without a known release date go LAST in both directions.
            dated, undated = [], []
            for s in st["order"]:
                d = titledates.release_date(st["tids"][s])
                (dated if d else undated).append((d, s))
            dated.sort(key=lambda t: t[0], reverse=(preset == "date_desc"))
            order = [s for _, s in dated] + [s for _, s in undated]
        return self._commit(f"Sorted: {labels[preset]}", order=order)

    def undo(self):
        if self.staging._undo:
            self.staging.undo()
        return self.get_state()

    def redo(self):
        if self.staging._redo:
            self.staging.redo()
        return self.get_state()

    def reset_staging(self):
        """Discards every staged change (each one recoverable via redo)."""
        while self.staging._undo:
            self.staging.undo()
        return self.get_state()

    # ---- SD + NAND ---------------------------------------------------------
    def backup_manual(self):
        self.backups.create(self.workdir / "extract", kind="manual",
                            note="manual backup", extra=self._backup_extra())
        return self.get_state()

    def _backup_extra(self) -> dict:
        """Launcher/container go into the zip outside the extdata tree (__nand__/)."""
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
        if nand_dir.exists():  # remove from extract BEFORE the next import to the SD
            lp = nand_dir / "Launcher.dat"
            restored_launcher = lp.read_bytes() if lp.exists() else None
            shutil.rmtree(nand_dir)
        # safety belt for legacy backups without directory entries in the zip: the
        # extdata must never reach the SD without boss/ (HOME would rebuild the
        # SaveData, Phase 0C)
        (ext / "boss").mkdir(exist_ok=True)
        self._load(ext)
        # a restore is a new state relative to the SD: must stay staged for the WRITE
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
        """Applies the staging to SaveData.dat (and, if needed, Launcher.dat) and
        imports. Backup first, always. All-or-nothing: both files come from the SAME
        snapshot; if the launcher branch fails, staging is NOT cleared and the retry
        is idempotent."""
        n = len(self.staging.staged)
        if n == 0:
            return {"error": "nothing staged"}
        st = self.staging.state
        dirty = self._launcher_dirty(st)
        if dirty:
            self._require_writable()
            cur = hashlib.sha256(Path(self.container_path).read_bytes()).hexdigest()
            if cur != self._container_sha:
                return {"error": "System save changed on disk. Re-dump it in "
                                 "GodMode9 and re-import before writing."}
            # the gate-2 anchor only counts if it came from a fresh GM9 dump
            # (cp --hash). The copy promoted post-inject has no .sha on purpose:
            # any HOME boot drifts volatile NAND bytes (observed in Phase 0C)
            sha_file = Path(str(self.container_path) + ".sha")
            if not sha_file.exists() or sha_file.read_bytes() != bytes.fromhex(cur):
                return {"error": "No fresh GodMode9 dump of the system save "
                                 "(missing or stale homemenu_save.bin.sha). Run "
                                 "3DSort_dump in GodMode9, then Import from SD."}
        ext = self.workdir / "extract"
        self.backups.create(ext, kind="auto", note=f"before writing {n} changes",
                            extra=self._backup_extra())
        sav_path = ext / "user" / "SaveData.dat"
        sd = SaveData(sav_path.read_bytes())
        # theme/settings (0x13B8+) always from the CURRENT card version: the
        # workdir extract may predate changes made on the console (e.g. theme)
        # and neither restore nor write may regress them. Best-effort: with no
        # readable SD, write with what we have.
        try:
            import shutil
            fresh = self.workdir / "write_base"
            if fresh.exists():
                shutil.rmtree(fresh)
            self.save3ds.extract(self.console.extdata_id, self.sd_root, fresh)
            sd.graft_tail((fresh / "user" / "SaveData.dat").read_bytes())
        except Exception:
            pass
        # folders first: apply_order distributes positions per the CURRENT container
        for slot, folder in st["folders"].items():
            sd.set_folder(int(slot), folder)
        sd.apply_order(list(st["order"]), reserved=self._reserved_now(st))
        # always unwrap: 0 in the status array undoes the gift box on every
        # icon (Cthulhu's mechanism); the console re-marks "new" if it wants
        sd.set_all_status(0)
        # gate 0B: a new folder gets its number = current Launcher counter
        # (same source _write_launcher increments; delete leaves an orphan)
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
        """Edits the Launcher.dat inside the container and publishes the inject
        payload to the SD (homemenu_save_new.bin + .sha + GM9 scripts). The real
        NAND only changes when the USER runs the inject script in GodMode9."""
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
        self._publish_dump_script()
        scripts = Path(self.sd_root) / "gm9" / "scripts"
        (scripts / "3DSort_inject.gm9").write_text(
            gm9_inject_script(self.console.id0, save_id),
            encoding="ascii", newline="\n")
        self._pending_path().write_text(json.dumps({
            "sha": digest.hex(), "when": time.strftime("%Y-%m-%d %H:%M:%S"),
            "changes": n_changes}), encoding="utf-8")

    # ---- pending inject (NAND) -------------------------------------------
    def _pending_path(self) -> Path:
        return self.workdir / "pending_inject.json"

    def _pending_inject_info(self) -> dict | None:
        p = self._pending_path()
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def _check_inject_receipt(self) -> bool:
        """The GM9 script receipt confirms the injection: promotes the generated
        container to current dump and clears the pending state."""
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

    def _promote_payload(self, sd3: Path):
        """The generated container becomes the current dump (STRUCTURAL truth).
        The .sha anchors are discarded on purpose: any HOME boot drifts volatile
        NAND bytes (Phase 0C), so only a new 3DSort_dump produces a valid anchor
        for the next launcher write. The inject script goes with them: once the
        payload is consumed the script points at a file that no longer exists, and
        running it later aborts at gate 1 as if a write had broken (real report,
        2026-08-16)."""
        import shutil
        payload = sd3 / "homemenu_save_new.bin"
        if payload.exists():
            shutil.move(str(payload), sd3 / "homemenu_save.bin")
        (sd3 / "homemenu_save_new.bin.sha").unlink(missing_ok=True)
        (sd3 / "homemenu_save.bin.sha").unlink(missing_ok=True)
        self._delete_inject_script()

    def _delete_inject_script(self):
        if self.sd_root is not None:
            (Path(self.sd_root) / "gm9" / "scripts" /
             "3DSort_inject.gm9").unlink(missing_ok=True)

    def verify_inject(self):
        if self._pending_inject_info() is None:
            return self.get_state()
        if self._check_inject_receipt():
            return self.import_sd()
        return {"error": "No inject receipt found. Run the 3DSort_inject script "
                         "in GodMode9, then verify again."}

    def confirm_inject(self):
        """Manual override: the user vouches they injected without a receipt."""
        if self._pending_inject_info() is not None and self.sd_root is not None:
            sd3 = Path(self.sd_root) / "3DSort"
            self._promote_payload(sd3)
            (sd3 / "inject_done.sha").unlink(missing_ok=True)
        self._pending_path().unlink(missing_ok=True)
        return self.import_sd()

    def cancel_inject(self):
        """Abandons a pending inject: removes the published payload, the inject
        script and the marker. The SD layout already written stays (the console
        tolerates a new SaveData with the old launcher). The dump anchor goes too,
        so the next launcher write demands a fresh 3DSort_dump."""
        if self._pending_inject_info() is None:
            return {"error": "No pending inject to cancel."}
        if self.sd_root is not None:
            sd3 = Path(self.sd_root) / "3DSort"
            for name in ("homemenu_save_new.bin", "homemenu_save_new.bin.sha",
                         "homemenu_save.bin.sha", "inject_done.sha"):
                (sd3 / name).unlink(missing_ok=True)
            self._delete_inject_script()
        # Marker last: _find_container prefers the payload while it exists.
        self._pending_path().unlink(missing_ok=True)
        return self.import_sd()

    # ---- settings (SD drive and backups folder) ---------------------------
    def _save_settings(self):
        """Persists the user's choices next to the workdir
        (real: %USERPROFILE%/3DSort/settings.json; mock: tmp). build_api reads it."""
        sp = Path(self.workdir).parent / "settings.json"
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps({
            "sd_root": str(self.sd_root) if self.sd_root else None,
            "backups_dir": str(self.backups.root)}), encoding="utf-8")

    def list_drives(self):
        roots = [str(p) for p in list_3ds_roots()]
        cur = str(self.sd_root) if self.sd_root else None
        if cur and cur not in roots:  # e.g. sandbox outside the default scan
            roots.insert(0, cur)
        return {"drives": [{"root": r, "current": r == cur} for r in roots]}

    def set_sd_root(self, path):
        p = Path(path)
        if not (p / "Nintendo 3DS").is_dir():
            return {"error": f"No 'Nintendo 3DS' folder found in {path}"}
        self.sd_root = p
        self.console = None
        self._save_settings()
        return self.import_sd()  # re-derives console, keys, container, receipt

    def pick_backups_dir(self):
        """Opens the native folder picker and applies the choice.
        Cancelled = state unchanged."""
        path = pick_folder_native(str(self.backups.root))
        if not path:
            return self.get_state()
        return self.set_backups_dir(path)

    def set_backups_dir(self, path):
        if not str(path).strip():
            return {"error": "Backup folder path is empty"}
        try:
            self.backups.move_root(Path(path))
        except OSError as e:
            return {"error": f"Could not move backups: {e}"}
        self._save_settings()
        return self.get_state()


def pick_folder_native(initial: str) -> str | None:
    """Native folder dialog: pywebview when there is a window; otherwise tkinter
    (--serve mode, the backend runs on the same machine as the browser)."""
    try:
        import webview
        if webview.windows:
            r = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG,
                                                      directory=initial)
            return r[0] if r else None
    except Exception:
        pass
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory(initialdir=initial,
                                       title="3DSort - Backup folder")
        root.destroy()
        return path or None
    except Exception:
        return None


# ---- GodMode9 scripts ------------------------------------------------------
# The dump script resolves the console itself ($[SYSID0]/$[REGION]) because it runs
# before the app knows anything: a card can carry leftover id0 folders from older
# consoles, and a script baked with the wrong one sends GodMode9 to a NAND path that
# does not exist. The inject script is still generated per console: by then the keys
# are validated against the right id0, and its sha gates abort on a mismatch anyway.
def gm9_dump_script() -> str:
    """Copies the HOME menu system save to the SD card. cp --hash writes the .sha
    next to it, which is the staleness anchor for the inject script."""
    branches = "".join(
        f'{"if" if i == 0 else "elif"} chk $[REGION] "{region}"\n\tset SAVEID "{save_id}"\n'
        for i, (region, save_id) in enumerate(NAND_SAVE_IDS.items()))
    return f"""# 3DSort: dump the HOME menu system save and console keys to the SD card
{branches}else
\techo "Console region $[REGION] is not supported by 3DSort yet."
\tgoto End
end
set SAVE "1:/data/$[SYSID0]/sysdata/$[SAVEID]/00000000"
cp --overwrite --no_cancel 1:/private/movable.sed 0:/3DSort/movable.sed
cp --overwrite --no_cancel M:/boot9.bin 0:/3DSort/boot9.bin
if not exist $[SAVE]
\techo "HOME menu save not found ($[REGION]). Is this SysNAND, not EmuNAND?"
\tgoto End
end
cp --hash --overwrite --no_cancel $[SAVE] 0:/3DSort/homemenu_save.bin
echo "Dumped save and keys. Edit the layout in 3DSort on the PC, then run 3DSort_inject."
@End
"""


def gm9_inject_script(id0: str, save_id: str) -> str:
    """Injects the edited container. Every sha is a hard gate: the script aborts
    at the first failure, so an inconsistent state never reaches the NAND."""
    return f"""# 3DSort: inject the edited HOME menu system save into the NAND
set SAVE "1:/data/{id0}/sysdata/{save_id}/00000000"
ask "Write the 3DSort layout to the console NAND?"
# gate 1: the payload is intact (the PC-side write finished)
sha 0:/3DSort/homemenu_save_new.bin 0:/3DSort/homemenu_save_new.bin.sha
# gate 2: the NAND is still exactly as dumped (aborts if the HOME menu booted in between)
sha $[SAVE] 0:/3DSort/homemenu_save.bin.sha
allow $[SAVE]
cp --overwrite --no_cancel 0:/3DSort/homemenu_save_new.bin $[SAVE]
# gate 3: the copy arrived bit-perfect; only then fix the CMAC
sha $[SAVE] 0:/3DSort/homemenu_save_new.bin.sha
fixcmac $[SAVE]
# receipt so the app can confirm the injection on the next import
cp --overwrite --no_cancel 0:/3DSort/homemenu_save_new.bin.sha 0:/3DSort/inject_done.sha
echo "Injected. You can boot the HOME menu now."
"""


# ---- mock: same Api, fake crypto ---------------------------------------------
class FakeSave3ds(Save3ds):
    """Simulates extract/import by copying an already 'decrypted' extdata tree.
    On the NAND channel, the mock 'container' is a file whose bytes ARE the Launcher.dat."""

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
    """48x48 prototype-style icon: diagonal gradient + monogram."""
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


# mock NAND apps: (name, real tid, pos, folder): home 0-2 + 8, one inside a folder
MOCK_NAND = [("System Settings", 0x0004001000021000, 0, -1),
             ("Mii Maker", 0x0004001000021700, 1, -1),
             ("Nintendo eShop", 0x0004001000021900, 2, -1),
             ("StreetPass Mii Plaza", 0x0004001000021800, 8, -1),
             ("Health & Safety", 0x0004001020021300, 0, 0)]
MOCK_FOLDERS = [(0, 9, "Homebrew")]  # (id, tile pos on the home grid, name)
MOCK_CART_POS = 17                   # after the 12 games (3-7, 10-16)


def make_mock_extdata(target: Path):
    """Synthetic extdata: 12 games + SMDH of the mock NAND apps in the cache."""
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
    """Synthetic Launcher.dat with the mock NAND apps and folders."""
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
    # bin+sha pair as GM9's cp --hash leaves it (fresh-dump anchor)
    Path(str(path) + ".sha").write_bytes(hashlib.sha256(bytes(buf)).digest())


def build_api(mock: bool, sd_root: Path | None = None,
              no_launcher: bool = False) -> Api:
    if mock:
        tmp = Path(tempfile.mkdtemp(prefix="3dsort-mock-"))
        plain = tmp / "plain"
        make_mock_extdata(plain)
        # fake SD tree so the real find_console flow works
        fake_sd = tmp / "sd"
        (fake_sd / "Nintendo 3DS" / ("0" * 32) / ("1" * 32) / "extdata" /
         "00000000" / "0000008f").mkdir(parents=True)
        container = None
        if not no_launcher:
            # mock container = Launcher.dat bytes (see FakeSave3ds)
            container = tmp / "homemenu_save.bin"
            make_mock_launcher(container)
        return Api(FakeSave3ds(plain), fake_sd, tmp / "work", Backups(tmp / "backups"),
                   container=container)
    workdir = APP_DIR / "work"
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        settings = json.loads((APP_DIR / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        settings = {}
    if sd_root is None and settings.get("sd_root"):  # CLI --sd wins over settings
        sd_root = Path(settings["sd_root"])
    backups_root = Path(settings.get("backups_dir") or APP_DIR / "backups")
    sandbox_keys = ROOT / "sandbox" / "keys"
    launcher = container = None
    if not no_launcher:
        launcher = next((p for p in (sandbox_keys / "Launcher.dat",
                                     APP_DIR / "Launcher.dat") if p.exists()), None)
        container = next((p for p in (sandbox_keys / "homemenu_save.bin",
                                      APP_DIR / "homemenu_save.bin") if p.exists()), None)
    def key(name):  # local fallback; at runtime the SD takes precedence (_resolve_keys)
        cands = (sandbox_keys / name, APP_DIR / name)
        return next((p for p in cands if p.exists()), cands[0])
    return Api(
        Save3ds(ROOT / "tools" / "save3ds" / SAVE3DS_NAME,
                key("boot9.bin"), key("movable.sed")),
        sd_root, workdir, Backups(backups_root), launcher=launcher,
        container=container)


def serve(api: Api, port: int):
    import http.server

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(UI), **kw)

        def do_GET(self):
            """Serves index.html with the SERVE_MODE flag injected. The UI needs
            it to pick a channel: in the native window it must wait for the
            pywebview bridge instead of falling through to fetch (pywebview's own
            HTTP server has no /api route and answers 405)."""
            if self.path.split("?")[0] not in ("/", "/index.html"):
                return super().do_GET()
            html = (UI / "index.html").read_text(encoding="utf-8").replace(
                "<head>", "<head>\n<script>window.SERVE_MODE=true</script>", 1)
            data = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            name = self.path.removeprefix("/api/")
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
            args = json.loads(body).get("args", []) if body else []
            try:
                result = getattr(api, name)(*args)
            except Exception as e:  # error becomes JSON, not a browser stacktrace
                result = {"error": str(e)}
            data = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    print(f"3DSort dev at http://127.0.0.1:{port}")
    http.server.ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()


def selftest() -> int:
    """Checks the bundled resources are reachable. Used to smoke-test the frozen
    exe, where a missing data file would otherwise degrade silently (a missing
    titledates table just turns date sorting into a no-op)."""
    checks = {
        "ui/index.html": (UI / "index.html").is_file(),
        f"tools/save3ds/{SAVE3DS_NAME}": (ROOT / "tools" / "save3ds" / SAVE3DS_NAME).is_file(),
        "core/titledates.json.gz": len(titledates._load()) > 0,
    }
    for name, ok in checks.items():
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
    return 0 if all(checks.values()) else 1


def main():
    args = sys.argv[1:]
    if "--selftest" in args:
        sys.exit(selftest())
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
