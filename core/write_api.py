"""Prepare, back up, write and verify multiple extdata with explicit recovery."""
import copy
import hashlib
import json
import os
import shutil
from pathlib import Path

from core import badges, layout
from core.savedata import SaveData
from core.launcher import Launcher
from core.sdcard import find_console


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree_hashes(root):
    return {p.relative_to(root).as_posix() + ("/" if p.is_dir() else ""):
            None if p.is_dir() else digest(p) for p in Path(root).rglob("*")}


class WriteApi:
    def _connected_card_error(self, expected=None):
        """Recheck mounted console identity; a drive letter can be reused."""
        expected = expected or {
            "sd": str(Path(self.sd_root).resolve()),
            "id0": self.console.id0, "id1": self.console.id1,
        }
        try:
            current = find_console(self.sd_root, prefer_id0=self._sd_movable_id0())
            matches = (expected["sd"] == str(Path(self.sd_root).resolve()) and
                       expected["id0"] == current.id0 and expected["id1"] == current.id1 and
                       current.extdata_id == self.console.extdata_id)
        except (OSError, ValueError):
            matches = False
        if not matches:
            return "Card changed or disconnected. Reconnect the original card before writing or recovering."
        return None

    @staticmethod
    def _layout_signature(raw):
        return [(e.slot, e.tid, e.pos, e.folder) for e in SaveData(raw).entries]

    def _transaction_dir(self):
        return self.workdir / "transaction"

    def _recovery_info(self):
        path = self._transaction_dir() / "journal.json"
        if not path.exists():
            return None
        try:
            j = json.loads(path.read_text("utf-8"))
            return {"backup": j["backup"], "phase": j["phase"], "error": j.get("error")}
        except (ValueError, KeyError):
            return {"error": "Recovery journal is unreadable. Keep the backup and contact support."}

    def _save_journal(self, j):
        path = self._transaction_dir() / "journal.json"
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as stream:
            json.dump(j, stream)
            stream.flush()
            os.fsync(stream.fileno())
        tmp.replace(path)

    def write_sd(self):
        if self._recovery_info():
            return self.recover_write("complete")
        if not self.staging.staged:
            return {"error": "nothing staged"}
        if self._badge_error:
            return {"error": self._badge_error}
        card_error = self._connected_card_error()
        if card_error:
            return {"error": card_error}
        present = any(p.name.lower() == badges.EXTDATA_ID[-8:]
                      for p in self.console.extdata_dir.parent.iterdir())
        if present != self._badge_present:
            return {"error": "Badge collection changed on the card. Import from SD before writing."}
        st = copy.deepcopy(self.staging.state)
        self._select_badge_source(st)
        layout.validate(st, self._unknown_holes)
        if self._badges:
            self._badges.validate(st["badge_layout"])
        dirty = self._launcher_dirty(st)
        if dirty:
            self._require_writable()
            cur = digest(self.container_path)
            if cur != self._container_sha:
                return {"error": "System save changed on disk. Re-dump it in GodMode9 and re-import before writing."}
            sha = Path(str(self.container_path) + ".sha")
            if not sha.exists() or sha.read_bytes() != bytes.fromhex(cur):
                return {"error": "No fresh GodMode9 dump. Run 3DSort_dump, then Import from SD."}
        tx = self._transaction_dir()
        if tx.exists():
            shutil.rmtree(tx)
        tx.mkdir(parents=True)
        home = tx / "base_home"
        # No best-effort fallback: a fresh readable base is mandatory for a safe backup.
        self.save3ds.extract(self.console.extdata_id, self.sd_root, home)
        fresh_raw = (home / "user" / "SaveData.dat").read_bytes()
        if self._layout_signature(fresh_raw) != self._home_baseline:
            return {"error": "HOME layout changed on the card. Import from SD before writing."}
        sources = {"home": self.console.extdata_id}
        extra = self._backup_extra()
        extra["__layout__/manifest.json"] = json.dumps({
            "version": 2, "has_badges": self._badges is not None,
            "badge_layout_validated": badges.HARDWARE_VALIDATED,
            "synthetic": bool(getattr(self.save3ds, "synthetic", False))}).encode("utf-8")
        if present:
            base_badges = tx / "base_badges"
            self.save3ds.extract(badges.EXTDATA_ID, self.sd_root, base_badges)
            # Compare the live files with the import baseline, even during restore
            # and even for an empty collection: badges placed by HOME after the
            # import live in this extdata, not in SaveData.dat.
            if tree_hashes(base_badges) != self._badge_file_baseline:
                return {"error": "Badge collection changed on the card. Import from SD before writing."}
        if self._badges:
            extra = {k: v for k, v in extra.items() if not k.startswith("__badges__/")}
            extra.update({"__badges__/" + p.relative_to(base_badges).as_posix(): p
                          for p in base_badges.rglob("*")})
            desired_badges = tx / "desired_badges"
            shutil.copytree(self.workdir / "badge_sources" / st["badge_source"], desired_badges)
            (desired_badges / "user" / "BadgeMngFile.dat").write_bytes(
                self._badges.serialize(self._badge_layout_to_file(st["badge_layout"], st["folder_defs"]),
                                       validated=getattr(self.save3ds, "synthetic", False)))
            badges.Badges((desired_badges / "user" / "BadgeData.dat").read_bytes(),
                          (desired_badges / "user" / "BadgeMngFile.dat").read_bytes())
            if tree_hashes(desired_badges) != tree_hashes(base_badges):
                sources["badges"] = badges.EXTDATA_ID
        desired = tx / "desired_home"
        shutil.copytree(home, desired)
        sd = SaveData(bytes.fromhex(st["save_raw"]))
        sd.graft_tail(fresh_raw)
        for slot, pos in st["game_pos"].items():
            sd.set_folder(slot, st["folders"][slot])
            sd.set_position(slot, pos)
        sd.set_all_status(0)
        new_fids = sorted(set(st["folder_defs"]) - set(self._launcher_baseline["folder_defs"]))
        if new_fids and self._launcher_raw:
            n0 = Launcher(self._launcher_raw).next_folder_number
            for i, fid in enumerate(new_fids):
                sd.set_folder_number(fid, n0 + i)
        (desired / "user" / "SaveData.dat").write_bytes(sd.serialize())
        (desired / "boss").mkdir(exist_ok=True)
        # Build the complete NAND payload before any SD import.
        if dirty:
            self._write_launcher(st, len(self.staging.staged), destination=tx / "payload")
        backup = self.backups.create(home, kind="auto", note="before writing staged layout", extra=extra)
        j = dict(version=1, sd=str(Path(self.sd_root).resolve()), id0=self.console.id0,
                 id1=self.console.id1, backup=backup["id"], phase="prepared", sources=sources,
                 completed=[], files={}, dirty=dirty, state=st)
        for name in sources:
            j[name] = {side: tree_hashes(tx / f"{side}_{name}") for side in ("base", "desired")}
        if dirty:
            for p in (tx / "payload").rglob("*"):
                if not p.is_file():
                    continue
                rel = p.relative_to(tx / "payload").as_posix()
                target = self.workdir / rel if rel == "pending_inject.json" else Path(self.sd_root) / rel
                old = tx / "old_payload" / rel
                if target.exists():
                    old.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, old)
                j["files"][rel] = {"desired": digest(p), "base": digest(old) if old.exists() else None}
        self._save_journal(j)
        return self._run_transaction(j, "complete")

    def recover_write(self, action):
        if action not in ("complete", "restore"):
            raise ValueError("Choose complete or restore.")
        path = self._transaction_dir() / "journal.json"
        if not path.exists():
            return {"error": "No interrupted write to recover."}
        j = json.loads(path.read_text("utf-8"))
        if (j.get("version") != 1 or j["sd"] != str(Path(self.sd_root).resolve()) or
                j["id0"] != self.console.id0 or j["id1"] != self.console.id1):
            return {"error": "Recovery belongs to a different card. Reconnect the original card."}
        card_error = self._connected_card_error(j)
        if card_error:
            return {"error": card_error}
        return self._run_transaction(j, action)

    def _run_transaction(self, j, action):
        tx = self._transaction_dir()
        side = "desired" if action == "complete" else "base"
        try:
            # Verify all local recovery material before the first write.
            for name in j["sources"]:
                if tree_hashes(tx / f"{side}_{name}") != j[name][side]:
                    raise ValueError("Recovery files changed. Restore the saved backup manually.")
            for rel, hashes in j["files"].items():
                src = tx / ("payload" if action == "complete" else "old_payload") / rel
                if hashes[side] is not None and (not src.exists() or digest(src) != hashes[side]):
                    raise ValueError("Recovery payload changed. Keep the saved backup.")
            j.update(phase=action, error=None)
            self._save_journal(j)
            for name, eid in j["sources"].items():
                self.save3ds.import_(eid, self.sd_root, tx / f"{side}_{name}")
                verify = tx / f"verify_{name}"
                if verify.exists():
                    shutil.rmtree(verify)
                self.save3ds.extract(eid, self.sd_root, verify)
                if tree_hashes(verify) != j[name][side]:
                    raise ValueError(f"Verification failed for {name}. Recover this write before using the card.")
                j["completed"].append(name)
                self._save_journal(j)
            # Marker last: a pending injection is advertised only after its files exist.
            for rel in sorted(j["files"], key=lambda r: r == "pending_inject.json"):
                hashes = j["files"][rel]
                target = self.workdir / rel if rel == "pending_inject.json" else Path(self.sd_root) / rel
                if hashes[side] is None:
                    target.unlink(missing_ok=True)
                else:
                    source = tx / ("payload" if action == "complete" else "old_payload") / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                    if digest(target) != hashes[side]:
                        raise ValueError("Payload verification failed.")
            for name, dest in (("home", "extract"), ("badges", "badges")):
                if name in j["sources"]:
                    shutil.copytree(tx / f"{side}_{name}", self.workdir / dest, dirs_exist_ok=True)
            (tx / "journal.json").unlink()
            return self.import_sd()
        except Exception as exc:
            j["error"] = str(exc)
            self._save_journal(j)
            return {"error": f"Write interrupted: {exc}. Open SYNC to complete or restore the backup."}
