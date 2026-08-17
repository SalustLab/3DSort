"""v1.1: staged editing of the system layout (NAND apps, folders, Game Card) in mock.

The mock exercises the full pipeline (swaps between types, folder lifecycle,
write with injection payload + receipt) with FakeSave3ds; only the crypto is fake.
"""
import hashlib
import json
import struct
from pathlib import Path

import pytest

from app import MOCK_CART_POS, build_api
from core.launcher import Launcher
from core.savedata import OFF_FOLDER_NUM

H_AND_S = "n:4"    # Health & Safety, inside folder 0 (pos 0)
SETTINGS = "n:0"   # System Settings, home pos 0
FOLDER = "f:0"     # "Homebrew" tile, home pos 9


def positions(st):
    """{key: (folder, pos)} for everything in the state that has a key."""
    out = {i["key"]: (i["folder"], i["pos"]) for i in st["items"]}
    out.update({s["key"]: (s["folder"], s["pos"]) for s in st["system"] if s["key"]})
    out.update({f"f:{fid}": (-1, p) for fid, p in st["folderPos"].items()})
    return out


def assert_only_moved(before, after, *keys):
    for k in set(before) | set(after):
        if k not in keys:
            assert after[k] == before[k], f"{k} moved without being part of the swap"


def test_swap_game_with_nand_exchanges_exactly():
    api = build_api(mock=True)
    before = positions(api.get_state())
    game = next(k for k, (f, p) in before.items() if k.startswith("g:") and p == 3)
    after = positions(api.swap_items(game, SETTINGS))
    assert after[game] == before[SETTINGS]
    assert after[SETTINGS] == before[game]
    assert_only_moved(before, after, game, SETTINGS)


def test_swap_nand_with_folder_tile():
    api = build_api(mock=True)
    before = positions(api.get_state())
    after = positions(api.swap_items(SETTINGS, FOLDER))
    assert after[SETTINGS] == before[FOLDER]
    assert after[FOLDER] == before[SETTINGS]
    assert_only_moved(before, after, SETTINGS, FOLDER)


def test_swap_cart_with_game():
    api = build_api(mock=True)
    before = positions(api.get_state())
    game = next(k for k, (f, p) in before.items() if k.startswith("g:") and p == 3)
    after = positions(api.swap_items("cart", game))
    assert after["cart"] == (-1, 3)
    assert after[game] == (-1, MOCK_CART_POS)
    assert_only_moved(before, after, "cart", game)


def test_swap_game_into_folder_container():
    api = build_api(mock=True)
    before = positions(api.get_state())
    game = next(k for k, (f, p) in before.items() if k.startswith("g:") and p == 3)
    after = positions(api.swap_items(game, H_AND_S))  # H&S is in folder 0, pos 0
    assert after[game] == (0, 0)
    assert after[H_AND_S] == (-1, 3)
    assert_only_moved(before, after, game, H_AND_S)


def test_folder_and_cart_stay_on_home_grid():
    api = build_api(mock=True)
    api.get_state()
    with pytest.raises(ValueError):
        api.swap_items(FOLDER, H_AND_S)  # folder tile would go INSIDE the folder
    with pytest.raises(ValueError):
        api.swap_items("cart", H_AND_S)
    with pytest.raises(ValueError):
        api.set_folder(SETTINGS + "", 99)  # nonexistent folder


def test_launcher_mutations_need_writable():
    api = build_api(mock=True, no_launcher=True)
    api.get_state()
    with pytest.raises(ValueError):
        api.swap_items(SETTINGS, "cart")
    with pytest.raises(ValueError):
        api.folder_create()


def test_undo_restores_launcher_state_exactly():
    api = build_api(mock=True)
    before = positions(api.get_state())
    api.swap_items(SETTINGS, FOLDER)
    api.set_folder(SETTINGS, 0)
    api.undo()
    api.undo()
    st = api.get_state()
    assert positions(st) == before
    assert st["launcherDirty"] is False


def test_set_folder_nand_in_and_out():
    api = build_api(mock=True)
    api.get_state()
    st = api.set_folder(SETTINGS, 0)
    got = positions(st)
    assert got[SETTINGS] == (0, 1)  # H&S occupies pos 0 in the folder; next free = 1
    # the pos 0 freed on home is taken by the compaction of the games
    assert min(p for k, (f, p) in got.items() if k.startswith("g:")) == 0
    st = api.set_folder(SETTINGS, -1)
    # back to home: lowest free position after the compaction of the games
    assert positions(st)[SETTINGS] == (-1, 16)


def test_folder_create_rename_delete_lifecycle():
    api = build_api(mock=True)
    api.get_state()
    st = api.folder_create()
    assert st["folderNames"][1] == "New folder"
    assert st["folderPos"][1] == MOCK_CART_POS + 1  # after everything on home
    st = api.folder_rename(1, "Games")
    assert st["folderNames"][1] == "Games"
    with pytest.raises(ValueError):
        api.folder_rename(1, "X" * 17)
    with pytest.raises(ValueError):
        api.folder_rename(1, "")
    st = api.folder_delete(1)
    assert 1 not in st["folderNames"]
    api.undo()  # undoes the delete
    assert api.get_state()["folderNames"][1] == "Games"


def test_folder_create_with_name():
    api = build_api(mock=True)
    api.get_state()
    st = api.folder_create("Games")
    assert st["folderNames"][1] == "Games"
    with pytest.raises(ValueError):
        api.folder_create("X" * 17)  # 17 UTF-16 units > 0x20 bytes
    st = api.folder_create("")  # empty from the UI modal = default name
    assert st["folderNames"][2] == "New folder"


def test_write_mirrors_folder_baptism_number_and_counter():
    # gate 0B: create writes the baptism number to the SaveData and increments the
    # Launcher counter; delete leaves both orphaned (same as the console)
    api = build_api(mock=True)
    api.get_state()
    api.folder_create()  # fid 1 (mock already has fid 0; mock counter = 2)
    api.write_sd()
    sd_out = (api.workdir / "extract" / "user" / "SaveData.dat").read_bytes()
    assert struct.unpack_from("<I", sd_out, OFF_FOLDER_NUM + 1 * 4)[0] == 2
    sd3 = Path(api.sd_root) / "3DSort"
    payload = sd3 / "homemenu_save_new.bin"
    assert Launcher(payload.read_bytes()).next_folder_number == 3
    # close the inject cycle and delete the folder: fields become orphaned
    (sd3 / "inject_done.sha").write_bytes(hashlib.sha256(payload.read_bytes()).digest())
    api.verify_inject()
    # simulated re-dump: launcher write requires a fresh anchor post-promote
    (sd3 / "homemenu_save.bin.sha").write_bytes(
        hashlib.sha256((sd3 / "homemenu_save.bin").read_bytes()).digest())
    api.folder_delete(1)
    api.write_sd()
    sd_out = (api.workdir / "extract" / "user" / "SaveData.dat").read_bytes()
    assert struct.unpack_from("<I", sd_out, OFF_FOLDER_NUM + 1 * 4)[0] == 2
    assert Launcher(payload.read_bytes()).next_folder_number == 3


def test_status0_game_visible_and_position_protected():
    # gate 0C (real console): a never-opened game has status 0, the console shows it.
    # Collision regression: folder_create must land AFTER it, not on top of it.
    from core.savedata import OFF_FOLDER, OFF_POS, OFF_STATUS, OFF_TID
    api = build_api(mock=True)
    sav = api.save3ds.plain / "user" / "SaveData.dat"
    buf = bytearray(sav.read_bytes())
    struct.pack_into("<Q", buf, OFF_TID + 30 * 8, 0x00040000DEAD0000)
    struct.pack_into("<b", buf, OFF_STATUS + 30, 0)
    struct.pack_into("<h", buf, OFF_POS + 30 * 2, MOCK_CART_POS + 1)
    struct.pack_into("<b", buf, OFF_FOLDER + 30, -1)
    sav.write_bytes(bytes(buf))
    st = api.import_sd()
    it = next(i for i in st["items"] if i["slot"] == 30)
    assert it["pos"] == MOCK_CART_POS + 1
    st = api.folder_create()
    assert st["folderPos"][1] == MOCK_CART_POS + 2


def test_folder_delete_returns_members_home():
    api = build_api(mock=True)
    st = api.get_state()
    game = st["items"][0]["slot"]
    api.set_folder(game, 0)
    st = api.folder_delete(0)
    assert st["folderNames"] == {}
    got = positions(st)
    # member game goes back to the end of the games; H&S (NAND) after all of them
    assert got[f"g:{game}"][0] == -1
    assert got[H_AND_S] == (-1, 16)
    # games compact into pos 9 freed by the folder tile
    game_pos = sorted(p for k, (f, p) in got.items() if k.startswith("g:"))
    assert game_pos == [3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15]


def test_folder_empty_keeps_folder():
    api = build_api(mock=True)
    api.get_state()
    st = api.folder_empty(0)
    assert st["folderNames"] == {0: "Homebrew"}
    assert positions(st)[H_AND_S][0] == -1


def test_launcher_write_requires_fresh_dump_after_promote():
    # 0C (real console): any HOME boot drifts volatile bytes in the NAND,
    # so the copy promoted post-inject is NOT a valid anchor. Launcher
    # writes require the .sha of a fresh dump next to the container.
    api = build_api(mock=True)
    api.get_state()
    api.swap_items(SETTINGS, FOLDER)
    api.write_sd()
    sd3 = Path(api.sd_root) / "3DSort"
    payload = sd3 / "homemenu_save_new.bin"
    (sd3 / "inject_done.sha").write_bytes(hashlib.sha256(payload.read_bytes()).digest())
    api.verify_inject()
    # promote discards the anchors on purpose
    assert not (sd3 / "homemenu_save.bin.sha").exists()
    assert not (sd3 / "homemenu_save_new.bin.sha").exists()
    api.swap_items(SETTINGS, FOLDER)
    st = api.write_sd()
    assert "3DSort_dump" in st["error"]
    # simulated re-dump (GM9's cp --hash regenerates the bin+sha pair)
    (sd3 / "homemenu_save.bin.sha").write_bytes(
        hashlib.sha256((sd3 / "homemenu_save.bin").read_bytes()).digest())
    st = api.write_sd()
    assert "error" not in st and st["pendingInject"] is not None


def test_write_keeps_theme_changed_on_console_after_import():
    # user changes the theme ON THE CONSOLE after the import: the write must not
    # regress it (graft of the 0x13B8+ region from the card at write time)
    api = build_api(mock=True)
    st = api.get_state()
    sav = api.save3ds.plain / "user" / "SaveData.dat"
    buf = bytearray(sav.read_bytes())
    buf[0x13B8] = 0x42  # new "theme" written by the console after the import
    sav.write_bytes(bytes(buf))
    api.swap_items(st["items"][0]["slot"], st["items"][1]["slot"])
    api.write_sd()
    out = (api.workdir / "extract" / "user" / "SaveData.dat").read_bytes()
    assert out[0x13B8] == 0x42


def test_every_write_unwraps_all_icons():
    # Cthulhu's mechanism, always on: every write zeroes the status array
    # (0 = always unwrapped; the console re-marks "new" on its own if it wants)
    from core.savedata import OFF_STATUS
    api = build_api(mock=True)
    st = api.get_state()
    api.swap_items(st["items"][0]["slot"], st["items"][1]["slot"])
    api.write_sd()
    sav = (api.workdir / "extract" / "user" / "SaveData.dat").read_bytes()
    assert sav[OFF_STATUS:OFF_STATUS + 360] == b"\x00" * 360


def test_gap_is_free_when_launcher_present_and_reserved_without():
    # 0C: with launcher every owner is known (tid+pos on SD; NAND/folders/cart in
    # the Launcher) -- a gap is a real free slot, not an eternal reservation.
    # Without launcher the reservation stays (invisible owners are possible).
    from core.savedata import OFF_FOLDER, OFF_POS, OFF_TID

    def craft_gap(api):  # game at MOCK_CART_POS+2 leaves a gap at +1
        sav = api.save3ds.plain / "user" / "SaveData.dat"
        buf = bytearray(sav.read_bytes())
        struct.pack_into("<Q", buf, OFF_TID + 30 * 8, 0x00040000DEAD0000)
        struct.pack_into("<h", buf, OFF_POS + 30 * 2, MOCK_CART_POS + 2)
        struct.pack_into("<b", buf, OFF_FOLDER + 30, -1)
        sav.write_bytes(bytes(buf))

    api = build_api(mock=True)
    craft_gap(api)
    st = api.import_sd()
    assert not any(s.get("hole") for s in st["system"])
    a, b = st["items"][0]["slot"], st["items"][1]["slot"]
    st = api.swap_items(a, b)  # any mutation redistributes positions
    poss = sorted(p for k, (f, p) in positions(st).items() if k.startswith("g:"))
    assert MOCK_CART_POS + 1 in poss and MOCK_CART_POS + 2 not in poss

    api2 = build_api(mock=True, no_launcher=True)
    craft_gap(api2)
    st = api2.import_sd()
    assert MOCK_CART_POS + 1 in [s["pos"] for s in st["system"]]  # placeholder


def test_restore_backup_ensures_boss_dir():
    # safety belt for legacy backups (zip without directory entries): extdata
    # imported without boss/ makes the HOME rebuild the whole SaveData (Phase 0C)
    api = build_api(mock=True)
    st = api.get_state()
    a, b = st["items"][0]["slot"], st["items"][1]["slot"]
    api.swap_items(a, b)
    api.write_sd()  # auto backup comes from the mock, which has no boss/
    bid = api.backups.history()[-1]["id"]
    api.restore_backup(bid)
    assert (api.workdir / "extract" / "boss").is_dir()


def test_write_sd_only_leaves_no_pending_inject():
    api = build_api(mock=True)
    st = api.get_state()
    a, b = st["items"][0]["slot"], st["items"][1]["slot"]
    api.swap_items(a, b)
    st = api.write_sd()
    assert st["pendingInject"] is None
    assert st["staged"] == []


def test_write_launcher_dirty_publishes_payload_and_verifies():
    api = build_api(mock=True)
    before = positions(api.get_state())
    api.swap_items(SETTINGS, FOLDER)
    st = api.write_sd()
    assert st["pendingInject"] is not None
    sd3 = Path(api.sd_root) / "3DSort"
    payload = sd3 / "homemenu_save_new.bin"
    assert payload.exists() and (sd3 / "homemenu_save_new.bin.sha").exists()
    scripts = Path(api.sd_root) / "gm9" / "scripts"
    assert (scripts / "3DSort_dump.gm9").exists()
    inject = (scripts / "3DSort_inject.gm9").read_text(encoding="ascii")
    assert "fixcmac" in inject and "allow" in inject and "inject_done.sha" in inject
    # without the receipt, verify fails
    assert "error" in api.verify_inject()
    # GM9 receipt = sha of the payload; then verify promotes and clears the pending
    (sd3 / "inject_done.sha").write_bytes(hashlib.sha256(payload.read_bytes()).digest())
    st = api.verify_inject()
    assert st["pendingInject"] is None
    got = positions(st)
    assert got[SETTINGS] == before[FOLDER]
    assert got[FOLDER] == before[SETTINGS]
    assert (sd3 / "homemenu_save.bin").exists() and not payload.exists()


def test_consumed_inject_script_is_removed(monkeypatch):
    """Real trap (2026-08-16, user's console): after the payload is consumed the
    inject script stayed on the card pointing at a file that no longer exists.
    Running it later aborted at gate 1, which reads as 'the write broke' when in
    fact nothing was pending. A script must never outlive its payload."""
    scripts_of = lambda api: Path(api.sd_root) / "gm9" / "scripts" / "3DSort_inject.gm9"

    for closer in ("verify_inject", "confirm_inject"):
        api = build_api(mock=True)
        api.get_state()
        api.swap_items(SETTINGS, FOLDER)
        api.write_sd()
        sd3 = Path(api.sd_root) / "3DSort"
        payload = sd3 / "homemenu_save_new.bin"
        assert scripts_of(api).exists(), closer
        if closer == "verify_inject":
            (sd3 / "inject_done.sha").write_bytes(
                hashlib.sha256(payload.read_bytes()).digest())
        getattr(api, closer)()
        assert not payload.exists(), closer
        assert not scripts_of(api).exists(), f"{closer} left an orphan inject script"
        # the dump script stays: it is what the user needs next
        assert (Path(api.sd_root) / "gm9" / "scripts" / "3DSort_dump.gm9").exists()


def test_cancel_inject_clears_pending_and_payload():
    """Cancel discards the published payload and the inject script. The mock
    container lives in tmp, so the 'forces a fresh dump' part (deleting
    homemenu_save.bin.sha) is only observable in the real flow."""
    api = build_api(mock=True)
    api.get_state()
    api.swap_items(SETTINGS, FOLDER)
    api.write_sd()
    sd3 = Path(api.sd_root) / "3DSort"
    scripts = Path(api.sd_root) / "gm9" / "scripts"
    assert (sd3 / "homemenu_save_new.bin").exists()
    st = api.cancel_inject()
    assert "error" not in st and "items" in st  # full state
    assert st["pendingInject"] is None and st["staged"] == []
    assert not (sd3 / "homemenu_save_new.bin").exists()
    assert not (sd3 / "homemenu_save_new.bin.sha").exists()
    assert not (scripts / "3DSort_inject.gm9").exists()
    assert not api._pending_path().exists()
    assert (scripts / "3DSort_dump.gm9").exists()  # dump script stays: needed next


def test_cancel_inject_without_pending_errors():
    api = build_api(mock=True)
    api.get_state()
    assert "error" in api.cancel_inject()


def test_write_still_works_after_cancel_inject():
    api = build_api(mock=True)
    api.get_state()
    api.swap_items(SETTINGS, FOLDER)
    api.write_sd()
    api.cancel_inject()
    st = api.get_state()
    a, b = st["items"][0]["slot"], st["items"][1]["slot"]
    api.swap_items(a, b)
    st = api.write_sd()
    assert "error" not in st and st["staged"] == []


def test_stale_container_blocks_launcher_write():
    api = build_api(mock=True)
    api.get_state()
    api.swap_items(SETTINGS, FOLDER)
    raw = bytearray(Path(api.container_path).read_bytes())
    raw[-1] ^= 0xFF  # container changed on disk after the parse
    Path(api.container_path).write_bytes(bytes(raw))
    r = api.write_sd()
    assert "error" in r and "Re-dump" in r["error"]
    assert api.get_state()["staged"]  # staging preserved for retry


def test_freed_position_is_reusable_after_write():
    """A game moved into a folder frees a position: with launcher present it is
    a REAL free slot (no 'Empty slot' placeholder) and gets used again (0C)."""
    api = build_api(mock=True)
    st = api.get_state()
    game = st["items"][-1]["slot"]  # last game on home (pos 16)
    api.set_folder(game, 0)
    api.write_sd()
    st = api.import_sd()
    assert not any(s.get("hole") for s in st["system"])
    assert 16 not in {i["pos"] for i in st["items"]}
    # the freed slot returns to the used set when the game goes back home
    st = api.set_folder(game, -1)
    poss = sorted(p for k, (f, p) in positions(st).items()
                  if k.startswith("g:") and f == -1)
    assert 16 in poss and max(poss) == 16


def test_backup_includes_launcher_and_restore_stages_it():
    api = build_api(mock=True)
    before = positions(api.get_state())
    api.swap_items(SETTINGS, FOLDER)
    st = api.write_sd()  # auto backup stores the PRE-write launcher
    bid = st["history"][0]["id"]
    st = api.restore_backup(bid)
    assert st["staged"][-1].startswith("Restored backup")
    assert st["launcherDirty"] is True  # restoring the old layout requires a new write
    assert positions(st) == before
