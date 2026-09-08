"""Staged spatial editing shared by both application transports."""
import copy
import hashlib
import shutil
from pathlib import Path
from collections import Counter

from core import layout
from core import badges
from core.badges import SHAPES
from core import titledates


class LayoutApi:
    def _load_badges(self):
        self._badges, self._badge_error, self._badge_writable = None, None, False
        self._badge_source = None
        self._badge_baseline = None
        self._badge_file_baseline = None
        root = self.console.extdata_dir.parent
        present = any(p.name.lower() == badges.EXTDATA_ID[-8:] for p in root.iterdir())
        self._badge_present = present
        dest = self.workdir / "badges"
        if dest.exists():
            shutil.rmtree(dest)
        if not present:
            return
        try:
            self.save3ds.extract(badges.EXTDATA_ID, self.sd_root, dest)
            from core.write_api import tree_hashes
            self._badge_file_baseline = tree_hashes(dest)
            if not (dest / "user" / "BadgeMngFile.dat").exists():
                # Hardware-observed: GYTB opened without a badges folder creates the
                # extdata with icon + boss/ + an EMPTY user/. No collection to protect.
                return
            self._badges = badges.Badges((dest / "user" / "BadgeData.dat").read_bytes(),
                                        (dest / "user" / "BadgeMngFile.dat").read_bytes())
            self._badge_baseline = copy.deepcopy(self._badges.layout)
            self._remember_badges(dest)
            self._badge_writable = badges.HARDWARE_VALIDATED or getattr(self.save3ds, "synthetic", False)
            if not self._badge_writable:
                self._badge_error = badges.VALIDATION_MESSAGE
        except (OSError, ValueError, RuntimeError) as exc:
            self._badge_error = f"Badge data could not be read safely: {exc}"

    def _remember_badges(self, directory):
        token = hashlib.sha256(self._badges.data + self._badges.raw).hexdigest()
        target = self.workdir / "badge_sources" / token
        if not target.exists():
            shutil.copytree(directory, target)
        self._badge_sources[token] = self._badges
        self._badge_source = token

    def _select_badge_source(self, st):
        token = st.get("badge_source")
        if token is None:
            self._badges, self._badge_source = None, None
            return
        if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
            raise ValueError("Invalid badge collection reference.")
        if token not in self._badge_sources:
            path = self.workdir / "badge_sources" / token / "user"
            candidate = badges.Badges((path / "BadgeData.dat").read_bytes(), (path / "BadgeMngFile.dat").read_bytes())
            if hashlib.sha256(candidate.data + candidate.raw).hexdigest() != token:
                raise ValueError("Cached badge collection changed. Re-import the card.")
            self._badge_sources[token] = candidate
        self._badges, self._badge_source = self._badge_sources[token], token

    def _prune_badge_sources(self):
        # A fresh import has discarded undo/redo. Old collection buffers can now
        # be removed; restore snapshots keep their sources until that import.
        if self._recovery_info():
            return
        root = self.workdir / "badge_sources"
        if root.exists():
            for path in root.iterdir():
                if (path.name != self._badge_source and len(path.name) == 64 and
                        all(c in "0123456789abcdef" for c in path.name) and
                        path.is_dir() and path.resolve().parent == root.resolve()):
                    shutil.rmtree(path)
        self._badge_sources = {k: v for k, v in self._badge_sources.items() if k == self._badge_source}

    # The file stores a decoration as the folder TILE's HOME position (hardware-
    # proven, docs/BADGES_TESTING.md cases 06/07); staging stores the folder id so
    # the decoration follows its folder when the tile moves.
    @staticmethod
    def _badge_layout_from_file(layout, folder_defs):
        by_pos = {d["pos"]: fid for fid, d in folder_defs.items()}
        out = copy.deepcopy(layout)
        for b in out.values():
            if b.get("decoration") is not None:
                if b["decoration"] not in by_pos:
                    raise ValueError(f"Folder decoration at HOME position {b['decoration']} has no "
                                     "known folder. Import a HOME menu dump first.")
                b["decoration"] = by_pos[b["decoration"]]
        return out

    @staticmethod
    def _badge_layout_to_file(layout, folder_defs):
        out = copy.deepcopy(layout)
        for b in out.values():
            if b.get("decoration") is not None:
                b["decoration"] = folder_defs[b["decoration"]]["pos"]
        return out

    def _badge_state(self, st):
        if not self._badges:
            return dict(catalog=[], placed=[], writable=False, error=self._badge_error, revision=None)
        counts = Counter(b["badge"] for b in st["badge_layout"].values())
        catalog = [{**b, "available": b["quantity"] - counts[n], "placed": counts[n],
                    "shape": list(SHAPES[b["sub"]])} for n, b in self._badges.catalog.items()]
        placed = [{**b, "key": f"b:{n}", "slot": n,
                   "name": self._badges.catalog[b["badge"]]["name"]} for n, b in st["badge_layout"].items()]
        return dict(catalog=catalog, placed=placed, writable=self._badge_writable and self._launcher_raw is not None,
                    error=self._badge_error, revision=self._badge_source)

    def _entity_pos(self, st):
        return layout.entities(st)

    def _next_free(self, st, container, taken=()):
        return layout.first_free(st, container, self._unknown_holes, taken)

    def _spatial_ready(self):
        if self._launcher_raw is None:
            raise ValueError("Import a HOME menu dump before using empty positions.")
        if self._badge_error:
            raise ValueError(self._badge_error)

    def _editable_key(self, key):
        k = self._key(key)
        if k not in self._entity_pos(self.staging.state):
            raise ValueError("Item does not exist on the grid.")
        if k[0] in ("n", "f", "cart"):
            self._require_writable()
        if k[0] == "b":
            self._require_badges()
        return k

    def move_to_position(self, key, folder, pos, rows=4):
        self._spatial_ready()
        k = self._editable_key(key)
        if type(folder) is not int or type(pos) is not int:
            raise ValueError("Destination must use integer positions.")
        if folder != -1 and folder not in self.staging.state["folder_defs"]:
            raise ValueError("Destination folder does not exist.")
        st = copy.deepcopy(self.staging.state)
        group = [k[1]] if k[0] == "b" else []
        if k[0] == "b":
            source_folder = st["badge_layout"][k[1]]["folder"]
            source_rows = st["folder_defs"].get(source_folder, {}).get("rows", rows)
            group = self._badge_group(st, k[1], source_rows)
        if len(group) > 1:
            badge = st["badge_layout"][k[1]]["badge"]
            _, _, dx, dy = SHAPES[self._badges.catalog[badge]["sub"]]
            dest_rows = st["folder_defs"].get(folder, {}).get("rows", rows)
            anchor = pos - dx * dest_rows - dy
            targets = self._badge_targets(badge, folder, anchor, dest_rows)
            by_badge = {st["badge_layout"][n]["badge"]: n for n in group}
            for b, dest in targets.items():
                layout.place(st, ("b", by_badge[b]), folder, dest)
        else:
            layout.place(st, k, folder, pos)
        return self._commit(f"Moved {self._label(self.staging.state, k)} to {self._cell(st, folder, pos)}", **st)

    def swap_items(self, a, b):
        ka, kb = self._editable_key(a), self._editable_key(b)
        st = copy.deepcopy(self.staging.state)
        # Pieces of a multi-part badge are independent badges on the console
        # (players arrange or swap them by hand), so any piece can be swapped.
        ca, pa = self._entity_pos(st)[ka]
        cb, pb = self._entity_pos(st)[kb]
        layout.place(st, ka, cb, pb)
        layout.place(st, kb, ca, pa)
        names = self._label(self.staging.state, ka), self._label(self.staging.state, kb)
        return self._commit(f"Swapped {names[0]} <-> {names[1]}", **st)

    def move_item(self, slot, before_slot=None):
        """Compatibility API: reorder games within their existing occupied cells."""
        st = copy.deepcopy(self.staging.state)
        if slot not in st["game_pos"] or (before_slot is not None and before_slot not in st["game_pos"]):
            raise ValueError("Game does not exist.")
        folder = st["folders"][slot]
        if before_slot is not None and st["folders"][before_slot] != folder:
            return self.set_folder(slot, st["folders"][before_slot])
        games = sorted((s for s in st["game_pos"] if st["folders"][s] == folder), key=st["game_pos"].get)
        positions = sorted(st["game_pos"][s] for s in games)
        games.remove(slot)
        games.insert(games.index(before_slot) if before_slot in games else len(games), slot)
        st["game_pos"].update(zip(games, positions))
        return self._commit("Moved game", **st)

    def set_folder(self, key, folder, rows=4):
        self._spatial_ready()
        k = self._editable_key(key)
        st = copy.deepcopy(self.staging.state)
        if folder != -1 and (type(folder) is not int or not 0 <= folder < 60 or
                             (st["folder_defs"] and folder not in st["folder_defs"])):
            raise ValueError("Destination folder does not exist.")
        if k[0] in ("f", "cart"):
            raise ValueError("Folders and the Game Card cannot go inside folders.")
        if self._entity_pos(st)[k][0] == folder:
            return self.get_state()
        if k[0] == "b":
            for pos in range(layout.capacity(folder)):
                try:
                    return self.move_to_position(key, folder, pos, rows)
                except ValueError as exc:
                    error = exc
            raise ValueError("No free area for this badge in the destination.") from error
        layout.place(st, k, folder, self._next_free(st, folder))
        name = self._label(self.staging.state, k)
        return self._commit(f"Moved {name} into {st['folder_defs'][folder]['name']}" if folder != -1
                            else f"Moved {name} back to the home grid", **st)

    def _return_members_home(self, st, fid, changes, home_rows=4):
        result = copy.deepcopy({**st, **changes})
        members = sorted(((k, p) for k, (f, p) in self._entity_pos(st).items() if f == fid), key=lambda t: t[1])
        handled = set()
        for k, _ in members:
            if k in handled:
                continue
            group = self._badge_group(st, k[1], st["folder_defs"][fid]["rows"]) if k[0] == "b" else []
            if len(group) > 1:
                badge = st["badge_layout"][k[1]]["badge"]
                by_badge = {st["badge_layout"][n]["badge"]: n for n in group}
                fitted = False
                for pos in range(layout.HOME_CAPACITY):
                    probe = copy.deepcopy(result)
                    try:
                        targets = self._badge_targets(badge, -1, pos, home_rows)
                        used = {p for f, p in self._entity_pos(result).values() if f == -1}
                        if used.intersection(targets.values()):
                            continue
                        for b, dest in targets.items():
                            layout.place(probe, ("b", by_badge[b]), -1, dest)
                    except ValueError:
                        continue
                    result, fitted = probe, True
                    break
                if not fitted:
                    raise ValueError("No free area for this folder's badges on the home grid.")
                handled.update(("b", n) for n in group)
                continue
            layout.place(result, k, -1, self._next_free(result, -1))
        if fid not in result["folder_defs"]:
            result["badge_layout"] = {n: b for n, b in result.get("badge_layout", {}).items()
                                      if b.get("decoration") != fid}
        changes.update(result)

    def sort_preset(self, preset, rows=4):
        """Games sorted by name or release date, then every container compacted
        (owner decision 2026-09-07: presets leave no gaps and pull stray items in)."""
        if preset not in ("az", "za", "date_asc", "date_desc"):
            raise ValueError(f"Unknown sort preset: {preset}")
        st = copy.deepcopy(self.staging.state)
        for folder in set(st["folders"].values()):
            slots = sorted((s for s in st["game_pos"] if st["folders"][s] == folder), key=st["game_pos"].get)
            positions = [st["game_pos"][s] for s in slots]
            if preset in ("az", "za"):
                ordered = sorted(slots, key=lambda s: self._names.get(st["tids"][s], "").lower(), reverse=preset == "za")
            else:
                dates = {s: titledates.release_date(st["tids"][s]) for s in slots}
                ordered = sorted((s for s in slots if dates[s]), key=dates.get, reverse=preset == "date_desc")
                ordered += [s for s in slots if not dates[s]]
            st["game_pos"].update(zip(ordered, positions))
            if self._launcher_raw is not None:
                # Layout by type (owner decision): system apps, Game Card, folders,
                # badges by name, then the sorted games. Folders and badges up front
                # are what a user who organises with them wants to reach first.
                ents = layout.entities(st)
                rank = {"n": 0, "cart": 1, "f": 2}
                system = sorted((k for k, (f, _) in ents.items() if f == folder and k[0] in rank),
                                key=lambda k: (rank[k[0]], ents[k][1]))
                badges_ = sorted((k for k, (f, _) in ents.items() if f == folder and k[0] == "b"),
                                 key=lambda k: (self._label(st, k).lower(), ents[k][1]))
                self._compact_container(st, folder, rows, system + badges_ + [("g", s) for s in ordered])
        return self._commit(f"Sorted: {preset}", **st)

    def _compact_container(self, st, folder, rows, items=None):
        """Every item of `folder` into the lowest free cells, in the given order or
        by position: games, badges, and (with a writable launcher) system apps,
        folder tiles and the Game Card. Aligned multi-piece badges move as a
        block; pieces without their group move alone (console semantics).
        Decorations and unknown holes are untouched. The launcher only becomes
        dirty if a system/folder/cart item really changed cell."""
        rows = st["folder_defs"][folder]["rows"] if folder != -1 else rows
        movable = {"g", "b"} | ({"n", "f", "cart"} if self._launcher_writable else set())
        ents = layout.entities(st)
        if items is None:
            items = sorted((k for k, (f, _) in ents.items() if f == folder), key=lambda k: ents[k][1])
        items = [(k, ents[k][1]) for k in items]
        taken = set(self._unknown_holes.get(folder, ())) | {p for k, p in items if k[0] not in movable}
        capacity = layout.capacity(folder)
        handled = set()
        for k, _ in items:
            if k in handled or k[0] not in movable:
                continue
            group = self._badge_group(st, k[1], rows) if k[0] == "b" else []
            if len(group) > 1:
                anchor = st["badge_layout"][group[0]]["badge"]
                by_badge = {st["badge_layout"][n]["badge"]: n for n in group}
                for cell in range(capacity):
                    try:
                        targets = self._badge_targets(anchor, folder, cell, rows)
                    except ValueError:
                        continue
                    if taken.isdisjoint(targets.values()):
                        for b, dest in targets.items():
                            layout.place(st, ("b", by_badge[b]), folder, dest)
                        taken.update(targets.values())
                        break
                else:
                    raise ValueError("No room to compact a multi-piece badge in this grid.")
                handled.update(("b", n) for n in group)
                continue
            cell = next(c for c in range(capacity) if c not in taken)
            layout.place(st, k, folder, cell)
            taken.add(cell)
            handled.add(k)

    def compact_games(self, folder=-1, rows=4):
        self._spatial_ready()
        st = copy.deepcopy(self.staging.state)
        if folder != -1 and folder not in st["folder_defs"]:
            raise ValueError("Folder does not exist.")
        self._compact_container(st, folder, rows)
        where = "the home grid" if folder == -1 else st["folder_defs"][folder]["name"]
        return self._commit(f"Compacted {where}", **st)

    def _require_badges(self):
        if not self._badges or not self._badge_writable:
            raise ValueError(self._badge_error or "No editable badge collection is available.")
        self._spatial_ready()

    def get_badge_images(self, ids):
        if not self._badges:
            return {}
        if not isinstance(ids, list) or len(ids) > 32 or any(type(n) is not int for n in ids):
            raise ValueError("Request at most 32 badge images at a time.")
        return {n: self._badges.image(n) for n in ids}

    def _badge_targets(self, badge, folder, pos, rows):
        if type(rows) is not int or not 1 <= rows <= 6:
            raise ValueError("Grid rows must be between 1 and 6.")
        if folder != -1:
            rows = self.staging.state["folder_defs"].get(folder, {}).get("rows", rows)
        pieces = self._badges.pieces(badge)
        w, h, _, _ = SHAPES[self._badges.catalog[badge]["sub"]]
        if type(pos) is not int or pos < 0 or pos % rows + h > rows:
            raise ValueError("The badge does not fit at this position.")
        targets = {n: pos + SHAPES[self._badges.catalog[n]["sub"]][2] * rows +
                   SHAPES[self._badges.catalog[n]["sub"]][3] for n in pieces}
        if max(targets.values()) >= layout.capacity(folder):
            raise ValueError("The badge extends past the end of the grid.")
        return targets

    def _badge_group(self, st, slot, rows):
        """Pieces of a multi-part badge that sit in their expected cells around
        `slot` (app convenience: they move together). Hardware-proven 2026-09-07:
        the console itself treats every piece as an independent badge, so when
        the siblings are missing, scattered or seen at another row setting the
        piece is handled alone instead of failing."""
        b = st["badge_layout"][slot]
        if b.get("decoration") is not None:
            return [slot]
        _, _, dx, dy = SHAPES[self._badges.catalog[b["badge"]]["sub"]]
        try:
            targets = self._badge_targets(b["badge"], b["folder"], b["pos"] - dx * rows - dy, rows)
        except ValueError:
            return [slot]
        group = []
        for badge, pos in targets.items():
            candidates = [n for n, item in st["badge_layout"].items()
                          if item["badge"] == badge and item["folder"] == b["folder"]
                          and item["pos"] == pos and item.get("decoration") is None]
            if len(candidates) != 1:
                return [slot]
            group += candidates
        return group

    def place_badge(self, badge, folder, pos, rows=4):
        self._require_badges()
        if badge not in self._badges.catalog:
            raise ValueError("Badge does not exist.")
        st = copy.deepcopy(self.staging.state)
        if folder != -1 and folder not in st["folder_defs"]:
            raise ValueError("Folder does not exist.")
        targets = self._badge_targets(badge, folder, pos, rows)
        free = [n for n in range(360) if n not in st["badge_layout"]]
        if len(free) < len(targets):
            raise ValueError("The badge layout is full.")
        for slot, (n, p) in zip(free, targets.items()):
            st["badge_layout"][slot] = dict(badge=n, folder=folder, pos=p, decoration=None)
        return self._commit(f"Placed {self._badges.catalog[badge]['name']} at {self._cell(st, folder, pos)}", **st)

    def place_badge_in_folder(self, badge, folder, rows=4):
        self._require_badges()
        if badge not in self._badges.catalog:
            raise ValueError("Badge does not exist.")
        counts = Counter(b["badge"] for b in self.staging.state["badge_layout"].values())
        if any(counts[n] >= self._badges.catalog[n]["quantity"] for n in self._badges.pieces(badge)):
            raise ValueError("No copies of this badge are available.")
        if folder != -1 and folder not in self.staging.state["folder_defs"]:
            raise ValueError("Folder does not exist.")
        for pos in range(layout.capacity(folder)):
            try:
                return self.place_badge(badge, folder, pos, rows)
            except ValueError:
                continue
        raise ValueError("No free area for this badge in the destination.")

    def remove_badge(self, key, rows=4):
        self._require_badges()
        kind, slot = self._key(key)
        st = copy.deepcopy(self.staging.state)
        if kind != "b" or slot not in st["badge_layout"]:
            raise ValueError("Badge occurrence does not exist.")
        name = self._label(st, (kind, slot))
        for n in self._badge_group(st, slot, rows):
            del st["badge_layout"][n]
        return self._commit(f"Returned {name} to the collection", **st)

    def _decoration_layout(self, st, fid, badge):
        """badge_layout of `st` with folder `fid` decorated by `badge` (None = no icon)."""
        self._require_badges()
        layout_ = {n: b for n, b in st["badge_layout"].items() if b.get("decoration") != fid}
        if badge is not None:
            if badge not in self._badges.catalog or self._badges.catalog[badge]["sub"]:
                raise ValueError("Choose a single-piece badge to decorate a folder.")
            slot = next((n for n in range(360) if n not in layout_), None)
            if slot is None:
                raise ValueError("The badge layout is full.")
            layout_[slot] = dict(badge=badge, folder=-1, pos=0, decoration=fid)
        return layout_

    def decorate_folder(self, fid, badge=None):
        st = copy.deepcopy(self.staging.state)
        if fid not in st["folder_defs"]:
            raise ValueError("Folder does not exist.")
        st["badge_layout"] = self._decoration_layout(st, fid, badge)
        folder = st["folder_defs"][fid]["name"]
        label = (f"Icon of {folder}: {self._badges.catalog[badge]['name']}" if badge is not None
                 else f"Removed the icon of {folder}")
        return self._commit(label, **st)

    @staticmethod
    def _cell(st, folder, pos):
        """UI wording for a destination: cells are 1-based like the grid labels."""
        where = f"cell {pos + 1}"
        return where if folder == -1 else f"{where} in {st['folder_defs'][folder]['name']}"
