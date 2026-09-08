"""Exact positions, collection editing and recovery over synthetic extdata."""
import copy
import struct
from pathlib import Path

import pytest

from app import Api, build_api
from core import badges
from core.badges import Badges
from core.savedata import OFF_POS, SaveData


def positions(state):
    return {i["key"]: (i["folder"], i["pos"]) for i in state["items"] + state["system"] if i["key"]}


def test_move_into_gap_preserves_every_other_item_and_roundtrips():
    api = build_api(mock=True)
    before = positions(api.get_state())
    changed = positions(api.move_to_position("g:0", -1, 80))
    assert changed["g:0"] == (-1, 80)
    assert {k: v for k, v in changed.items() if k != "g:0"} == {k: v for k, v in before.items() if k != "g:0"}
    assert positions(api.undo()) == before
    assert positions(api.redo()) == changed
    assert "error" not in api.write_sd()
    assert positions(api.import_sd()) == changed


def test_presets_preserve_positions_and_containers():
    api = build_api(mock=True)
    api.get_state()
    api.set_folder("g:1", 0)
    api.move_to_position("g:0", -1, 95)
    before = api.get_state()
    for preset in ("az", "za", "date_asc", "date_desc"):
        after = api.sort_preset(preset)
        # presets keep every game in its container and close the gaps (owner decision)
        assert {i["key"]: i["folder"] for i in after["items"]} == {i["key"]: i["folder"] for i in before["items"]}
        home = sorted(i["pos"] for i in after["items"] if i["folder"] == -1)
        assert home[-1] < 95 and len(home) == len(set(home))


@pytest.mark.parametrize("folder,pos", [(-1, 360), (-1, -1), (0, 60), (59, 0), (-1, 0), (-1, True)])
def test_rejected_destination_never_changes_staging(folder, pos):
    api = build_api(mock=True)
    api.get_state()
    original = copy.deepcopy(api.staging.state)
    with pytest.raises(ValueError):
        api.move_to_position("g:0", folder, pos)
    assert api.staging.state == original
    assert not api.staging.staged


def test_no_launcher_keeps_unknown_holes_reserved():
    api = build_api(mock=True, no_launcher=True)
    api.get_state()
    with pytest.raises(ValueError, match="HOME menu dump"):
        api.move_to_position("g:0", -1, 40)
    with pytest.raises(ValueError):
        api.compact_games()
    api.swap_items("g:0", "g:1")
    assert "error" not in api.write_sd()


@pytest.fixture
def badge_api():
    api = build_api(mock=True, mock_badges=True)
    state = api.get_state()
    assert state["badges"]["writable"], state["badges"]["error"]
    return api


def test_badge_occurrences_stock_and_undo(badge_api):
    api = badge_api
    for p in range(20, 25):
        api.place_badge(0, -1, p)
    before = copy.deepcopy(api.staging.state)
    with pytest.raises(ValueError, match="copies"):
        api.place_badge(0, -1, 25)
    assert api.staging.state == before
    api.remove_badge("b:0")
    assert api.get_state()["badges"]["catalog"][0]["available"] == 1
    api.undo()
    assert api.get_state()["badges"]["catalog"][0]["available"] == 0


def test_composite_moves_and_removes_as_group(badge_api):
    api = badge_api
    api.place_badge(4, -1, 20, 4)
    assert {b["pos"] for b in api.get_state()["badges"]["placed"]} == {20, 21, 24, 25}
    api.move_to_position("b:0", -1, 40, 4)
    assert {b["pos"] for b in api.get_state()["badges"]["placed"]} == {40, 41, 44, 45}
    # a single piece swaps like any badge (console semantics); undo restores the group
    state = api.swap_items("b:0", "g:0")
    assert positions(state)["g:0"] == (-1, 40)
    api.undo()
    api.remove_badge("b:0", 4)
    assert not api.get_state()["badges"]["placed"]
    api.undo()
    assert len(api.get_state()["badges"]["placed"]) == 4


def test_badge_geometry_and_collisions_are_atomic(badge_api):
    api = badge_api
    for pos in (3, 7, 359):
        with pytest.raises(ValueError):
            api.place_badge(4, -1, pos, 4)
        assert not api.get_state()["badges"]["placed"]
    api.place_badge(0, -1, 25)
    before = copy.deepcopy(api.staging.state)
    with pytest.raises(ValueError):
        api.place_badge(4, -1, 20, 4)
    assert api.staging.state == before


def test_decoration_tracks_folder_and_is_returned_on_delete(badge_api):
    api = badge_api
    api.decorate_folder(0, 0)
    assert api.get_state()["badges"]["placed"][0]["decoration"] == 0
    api.swap_items("f:0", "g:0")
    assert api.get_state()["badges"]["placed"][0]["decoration"] == 0
    api.decorate_folder(0, 1)
    assert api.get_state()["badges"]["catalog"][0]["available"] == 5
    api.folder_delete(0)
    assert not api.get_state()["badges"]["placed"]


def test_badges_write_without_nand_and_restore(badge_api):
    api = badge_api
    raw_data = api._badges.data
    api.place_badge(0, -1, 20)
    state = api.write_sd()
    assert "error" not in state, state
    assert state["pendingInject"] is None
    assert state["badges"]["placed"][0]["pos"] == 20
    assert api._badges.data == raw_data
    bid = state["history"][0]["id"]
    api.restore_backup(bid)
    assert api.get_state()["staged"]
    assert not api.get_state()["badges"]["placed"]
    assert "error" not in api.write_sd()
    assert not api.import_sd()["badges"]["placed"]


def test_badge_writer_is_open_after_hardware_validation(badge_api):
    """Gate opened 2026-09-07 after the console cases in docs/BADGES_TESTING.md:
    real (non-synthetic) cards with badge extdata are editable and writable."""
    api = badge_api
    api.place_badge(0, -1, 20)
    assert badges.HARDWARE_VALIDATED
    api._badges.serialize(api.staging.state["badge_layout"])   # no validated= opt-in needed
    api.save3ds.synthetic = False
    state = api.import_sd()
    assert state["badges"]["writable"] and state["spatialWritable"]
    api.swap_items("g:0", "g:1")
    assert "error" not in api.write_sd()


def test_external_badge_change_blocks_before_any_write(badge_api, monkeypatch):
    api = badge_api
    api.place_badge(0, -1, 20)
    path = api.save3ds.plain.parent / "badge_plain" / "user" / "BadgeData.dat"
    raw = bytearray(path.read_bytes())
    raw[0] ^= 1
    path.write_bytes(raw)
    monkeypatch.setattr(api.save3ds, "import_", lambda *a: pytest.fail("must not write"))
    assert "changed" in api.write_sd()["error"]


@pytest.mark.parametrize("action", ["complete", "restore"])
def test_interrupted_write_recovers_after_restart(badge_api, monkeypatch, action):
    api = badge_api
    api.move_to_position("g:0", -1, 70)
    api.place_badge(0, -1, 20)
    original = api.save3ds.import_
    def fail_badges(eid, *args):
        if eid == badges.EXTDATA_ID:
            raise OSError("simulated card removal")
        original(eid, *args)
    monkeypatch.setattr(api.save3ds, "import_", fail_badges)
    assert "interrupted" in api.write_sd()["error"]
    assert api.get_state()["staged"]
    assert api.get_state()["recovery"]
    monkeypatch.setattr(api.save3ds, "import_", original)
    restarted = Api(api.save3ds, api.sd_root, api.workdir, api.backups, container=api.container_path)
    assert restarted.get_state()["recovery"]
    state = restarted.recover_write(action)
    assert "error" not in state, state
    assert state["recovery"] is None
    assert positions(state)["g:0"] == (-1, 70 if action == "complete" else 3)
    assert len(state["badges"]["placed"]) == (1 if action == "complete" else 0)


def test_corrupt_recovery_material_is_never_written(badge_api, monkeypatch):
    api = badge_api
    api.place_badge(0, -1, 20)
    monkeypatch.setattr(api.save3ds, "import_", lambda *a: (_ for _ in ()).throw(OSError("removed")))
    api.write_sd()
    target = api.workdir / "transaction" / "desired_badges" / "user" / "BadgeMngFile.dat"
    target.write_bytes(b"bad")
    monkeypatch.setattr(api.save3ds, "import_", lambda *a: pytest.fail("must not write"))
    assert "Recovery files changed" in api.recover_write("complete")["error"]


@pytest.mark.parametrize("action", ["write", "complete", "restore", "restart"])
def test_replaced_card_is_rechecked_before_writing(badge_api, monkeypatch, action):
    api = badge_api
    api.place_badge(0, -1, 20)
    if action != "write":
        monkeypatch.setattr(api.save3ds, "import_", lambda *a: (_ for _ in ()).throw(OSError("removed")))
        assert "interrupted" in api.write_sd()["error"]
    # The drive root stays the same, but a different console's id1 is mounted.
    id1 = Path(api.sd_root) / "Nintendo 3DS" / api.console.id0 / api.console.id1
    id1.rename(id1.with_name("c" * 32))
    monkeypatch.setattr(api.save3ds, "import_", lambda *a: pytest.fail("must not write"))
    if action == "restart":
        restarted = Api(api.save3ds, api.sd_root, api.workdir, api.backups, container=api.container_path)
        monkeypatch.setattr(restarted, "_publish_dump_script", lambda *a: pytest.fail("must not publish"))
        result = restarted.import_sd()
    else:
        result = api.write_sd() if action == "write" else api.recover_write(action)
    assert "Card changed" in result["error"]


def test_restore_collection_source_is_undoable(badge_api):
    api = badge_api
    bid = api.backup_manual()["history"][0]["id"]
    path = api.save3ds.plain.parent / "badge_plain" / "user" / "BadgeData.dat"
    data = bytearray(path.read_bytes())
    off = 0x35E80 + 0x8A
    data[off:off + 10] = "Moon\0".encode("utf-16-le")
    path.write_bytes(data)
    assert api.import_sd()["badges"]["catalog"][0]["name"] == "Moon"
    assert api.restore_backup(bid)["badges"]["catalog"][0]["name"] == "Sun"
    assert api.undo()["badges"]["catalog"][0]["name"] == "Moon"
    assert api.redo()["badges"]["catalog"][0]["name"] == "Sun"
    state = api.write_sd()
    assert "error" not in state, state
    assert state["badges"]["catalog"][0]["name"] == "Sun"


def test_legacy_backup_keeps_badges_and_collisions_can_be_fixed(badge_api):
    api = badge_api
    # Old archives have no badge section. They must not erase the live badges.
    backup = api.backups.create(api.workdir / "extract", "manual", "legacy")
    api.move_to_position("g:0", -1, 50)
    api.move_to_position("g:1", -1, 51)
    api.place_badge(0, -1, 3)
    api.place_badge(1, -1, 4)
    assert "error" not in api.write_sd()
    state = api.restore_backup(backup["id"])
    assert len(state["badges"]["placed"]) == 2
    assert len(state["layoutErrors"]) == 2
    with pytest.raises(ValueError):
        api.write_sd()
    api.move_to_position("g:0", -1, 50)
    assert len(api.get_state()["layoutErrors"]) == 1
    api.move_to_position("g:1", -1, 51)
    assert not api.get_state()["layoutErrors"]
    assert "error" not in api.write_sd()


def test_folder_empty_moves_composites_together(badge_api):
    api = badge_api
    api.place_badge_in_folder(4, 0)
    api.decorate_folder(0, 0)
    state = api.folder_empty(0, 4)
    assert len(state["badges"]["placed"]) == 5
    assert all(b["folder"] == -1 for b in state["badges"]["placed"])
    assert sum(b["decoration"] == 0 for b in state["badges"]["placed"]) == 1
    api.undo()
    state = api.folder_delete(0, 4)
    assert len(state["badges"]["placed"]) == 4
    assert not state["layoutErrors"]


def test_composite_crosses_containers_with_different_rows(badge_api):
    api = badge_api
    api.place_badge(4, -1, 20, 4)
    state = api.set_folder("b:0", 0, 4)
    assert all(b["folder"] == 0 for b in state["badges"]["placed"])
    state = api.set_folder("b:0", -1, 4)
    assert all(b["folder"] == -1 for b in state["badges"]["placed"])


@pytest.mark.parametrize("phase", ["home", "badges", "verification", "payload"])
def test_failure_at_each_write_stage_is_recoverable(badge_api, monkeypatch, phase):
    import shutil
    api = badge_api
    api.place_badge(0, -1, 20)
    api.swap_items("n:0", "g:0")
    original_import, original_extract, original_copy = api.save3ds.import_, api.save3ds.extract, shutil.copy2
    def fail_import(eid, *args):
        original_import(eid, *args)
        if (phase == "home" and eid == api.console.extdata_id) or (phase == "badges" and eid == badges.EXTDATA_ID):
            raise OSError("write interrupted after import")
    def fail_extract(eid, root, dest):
        original_extract(eid, root, dest)
        if phase == "verification" and Path(dest).name == "verify_badges":
            (Path(dest) / "user" / "BadgeMngFile.dat").write_bytes(b"corrupt")
    def fail_copy(src, dst, *args, **kw):
        if phase == "payload" and Path(dst).name == "homemenu_save_new.bin" and Path(dst).is_relative_to(api.sd_root):
            raise OSError("payload publish interrupted")
        return original_copy(src, dst, *args, **kw)
    monkeypatch.setattr(api.save3ds, "import_", fail_import)
    monkeypatch.setattr(api.save3ds, "extract", fail_extract)
    monkeypatch.setattr(shutil, "copy2", fail_copy)
    state = api.write_sd()
    assert "interrupted" in state["error"]
    assert api.get_state()["recovery"] and api.get_state()["staged"]
    assert "error" in api.undo()
    assert "error" in api.cancel_inject()
    monkeypatch.setattr(api.save3ds, "import_", original_import)
    monkeypatch.setattr(api.save3ds, "extract", original_extract)
    monkeypatch.setattr(shutil, "copy2", original_copy)
    state = api.recover_write("complete")
    assert "error" not in state, state
    assert state["pendingInject"]["badgeDependent"]
    assert "error" in api.cancel_inject()


def test_badge_extdata_without_files_is_an_empty_collection_not_a_lock():
    """Hardware-observed (GYTB opened once without a badges folder): the badge
    extdata exists with icon + boss/ + an EMPTY user/. That is not a collection
    to protect; the card must stay editable and writable."""
    api = build_api(mock=True)
    api.get_state()
    plain = api.save3ds.plain.parent / "badge_plain"
    (plain / "user").mkdir(parents=True)
    (plain / "boss").mkdir()
    (plain / "icon").write_bytes(b"synthetic")
    (api.console.extdata_dir.parent / "000014d1").mkdir()
    state = api.import_sd()
    assert state["badges"]["error"] is None
    assert state["badges"]["catalog"] == [] and not state["badges"]["writable"]
    assert state["spatialWritable"]
    api.move_to_position("g:0", -1, 40)
    assert "error" not in api.write_sd()
    # a collection appearing AFTER the import (GYTB run) still forces a re-import
    api.move_to_position("g:1", -1, 41)
    (plain / "user" / "BadgeMngFile.dat").write_bytes(b"\0" * badges.MNG_SIZE)
    assert "changed" in api.write_sd()["error"]


def _decorate_mock_file(api, badge, pos):
    """Write a HOME-style decoration record (folder 0xF0FF, pos = folder tile's
    HOME position) into the mock card's BadgeMngFile.dat before an import."""
    path = api.save3ds.plain.parent / "badge_plain" / "user" / "BadgeMngFile.dat"
    raw = bytearray(path.read_bytes())
    L, I = badges.LAYOUT, badges.INFO
    slot = next(n for n in range(360) if raw[L + n * 24:L + (n + 1) * 24] in (bytes(24), badges.EMPTY_RECORD))
    raw[L + slot * 24:L + slot * 24 + 16] = raw[I + badge * 0x28:I + badge * 0x28 + 16]
    struct.pack_into("<II", raw, L + slot * 24 + 16, pos, badges.DECORATION)
    struct.pack_into("<H", raw, I + badge * 0x28 + 0x10, struct.unpack_from("<H", raw, I + badge * 0x28 + 0x10)[0] + 1)
    struct.pack_into("<I", raw, 12, struct.unpack_from("<I", raw, 12)[0] + 1)
    path.write_bytes(raw)


def test_file_decoration_resolves_to_the_folder_at_that_home_position(badge_api):
    """Cases 06/07 on the console: the record stores the folder TILE position."""
    api = badge_api
    _decorate_mock_file(api, 1, 9)  # mock folder 0 sits at HOME position 9
    state = api.import_sd()
    assert state["badges"]["error"] is None and state["spatialWritable"]
    assert [b["decoration"] for b in state["badges"]["placed"]] == [0]
    # the decoration follows its folder when the folder tile moves
    api.swap_items("f:0", "g:0")
    new_pos = api.staging.state["folder_defs"][0]["pos"]
    assert new_pos != 9
    assert "error" not in api.write_sd()
    raw = (api.save3ds.plain.parent / "badge_plain" / "user" / "BadgeMngFile.dat").read_bytes()
    records = [struct.unpack_from("<II", raw, badges.LAYOUT + n * 24 + 16) for n in range(360)]
    assert (new_pos, badges.DECORATION) in records and (9, badges.DECORATION) not in records
    assert [b["decoration"] for b in api.get_state()["badges"]["placed"]] == [0]
    api.folder_delete(0)
    assert api.get_state()["badges"]["placed"] == []


def test_file_decoration_without_a_known_folder_locks_the_card(badge_api):
    api = badge_api
    _decorate_mock_file(api, 1, 250)  # no folder tile at HOME position 250
    state = api.import_sd()
    assert state["badges"]["error"] and "250" in state["badges"]["error"]
    assert not state["spatialWritable"]
    with pytest.raises(ValueError):
        api.swap_items("g:0", "g:1")


def test_composite_pieces_are_independent_badges_like_on_the_console(badge_api):
    """Hardware + Badge Arcade documentation (2026-09-07): HOME has no composite
    concept. Every piece of a mega badge is its own badge in the tray and its own
    placement record; players arrange (or scatter, or swap) pieces by hand.
    Group moves are an app convenience that must degrade to single pieces."""
    api = badge_api
    state = api.place_badge(4, -1, 20)           # Window 2x2 -> 20, 21, 24, 25 (4 rows)
    pieces = {b["pos"]: b["key"] for b in state["badges"]["placed"]}
    assert sorted(pieces) == [20, 21, 24, 25]
    # a single piece can be swapped with a game, like any badge on the console
    state = api.swap_items(pieces[25], "g:0")
    placed = {b["key"]: b for b in state["badges"]["placed"]}
    assert placed[pieces[25]]["pos"] == 3 and positions(state)["g:0"] == (-1, 25)
    # the scattered piece moves alone; the three still-adjacent ones are not touched
    state = api.move_to_position(pieces[25], -1, 40)
    placed = {b["key"]: b for b in state["badges"]["placed"]}
    assert placed[pieces[25]]["pos"] == 40 and [placed[pieces[p]]["pos"] for p in (20, 21, 24)] == [20, 21, 24]
    # removing a scattered piece removes only that piece
    state = api.remove_badge(pieces[25])
    assert sorted(b["pos"] for b in state["badges"]["placed"]) == [20, 21, 24]
    # the remaining three are no longer a complete group either: they move alone
    state = api.move_to_position(pieces[20], -1, 60)
    assert sorted(b["pos"] for b in state["badges"]["placed"]) == [21, 24, 60]
    assert "error" not in api.write_sd()


def test_folder_create_with_icon_and_named_labels(badge_api):
    api = badge_api
    state = api.folder_create("Gems", 1)                 # Leaf (#1) as the folder icon
    fid = max(state["folderNames"])
    assert state["folderNames"][fid] == "Gems"
    assert [b["decoration"] for b in state["badges"]["placed"]] == [fid]
    assert state["staged"][-1] == "Created folder Gems with icon Leaf"
    state = api.undo()
    assert fid not in state["folderNames"] and not state["badges"]["placed"]
    api.redo()
    assert "error" not in api.write_sd()
    assert [b["decoration"] for b in api.get_state()["badges"]["placed"]] == [fid]
    # staged labels name what moved and where (cells are 1-based like the UI)
    assert api.place_badge(0, -1, 20)["staged"][-1] == "Placed Sun at cell 21"
    label = api.move_to_position("g:0", -1, 40)["staged"][-1]
    assert label.startswith("Moved ") and label.endswith(" to cell 41")
    assert api.decorate_folder(fid, None)["staged"][-1] == "Removed the icon of Gems"
    assert api.remove_badge("b:1")["staged"][-1] == "Returned Sun to the collection"
    import inspect
    assert inspect.getfullargspec(api.folder_create).args == ["self", "name", "decoration"]


def test_mock_temp_tree_is_removed_at_exit(monkeypatch):
    """A test session once left 54 GB of 3dsort-mock-* trees in %TEMP%."""
    import atexit
    registered = []
    monkeypatch.setattr(atexit, "register", lambda fn, *a, **kw: registered.append((fn, a)))
    api = build_api(mock=True, mock_badges=True)
    tmp = api.save3ds.plain.parent
    assert any(a and a[0] == tmp for _, a in registered)
    fn, args = next((fn, a) for fn, a in registered if a and a[0] == tmp)
    fn(*args, ignore_errors=True)
    assert not tmp.exists()


def _home_cells(state):
    cells = {i["pos"] for i in state["items"] if i["folder"] == -1}
    cells |= {s["pos"] for s in state["system"] if s["folder"] == -1 and not s.get("hole")}
    cells |= {b["pos"] for b in state["badges"]["placed"] if b["folder"] == -1 and b["decoration"] is None}
    cells |= set(state["folderPos"].values())
    return cells


def test_compact_pulls_every_item_forward_and_only_dirties_the_launcher_when_it_moves(badge_api):
    """Owner decision: Compact closes every gap on the grid (games, badges, folders,
    system apps, Game Card) keeping the order; the inject is needed only when a
    folder/system item actually moved."""
    api = badge_api
    api.place_badge(0, -1, 200)                  # a single badge far away
    api.place_badge(4, -1, 60)                   # a 2x2 group at 60, 61, 64, 65 (4 rows)
    state = api.compact_games(-1, 4)
    cells = sorted(_home_cells(state))
    # everything pulled in right after the Game Card (17): the 2x2 block takes the
    # first area where it fits (18, 19, 22, 23) and the single badge the next free
    # cell (20); only block geometry may leave a hole, never stray items far away
    assert cells == list(range(21)) + [22, 23], f"unexpected layout: {cells}"
    assert state["launcherDirty"] is False       # NAND at 0,1,2,8, folder at 9, cart at 17 never moved
    assert len(state["badges"]["placed"]) == 5
    quad = sorted(b["pos"] for b in state["badges"]["placed"] if b["badge"] in (4, 5, 6, 7))
    assert quad == [18, 19, 22, 23]
    assert state["staged"][-1] == "Compacted the home grid"
    # a folder tile with a gap before it moves, and that requires the inject
    api.reset_staging()
    api.move_to_position("g:1", -1, 50)          # cell 4 empty, folder at 9 is behind the gap
    state = api.compact_games(-1, 4)
    assert state["folderPos"][0] < 9 and state["launcherDirty"] is True
    assert sorted(_home_cells(state)) == list(range(len(_home_cells(state))))


def test_presets_order_system_cart_folders_badges_then_games(badge_api):
    """Owner decision: a preset leaves the grid readable by type. System apps,
    then the Game Card, then folders (relative order kept), then the badges by
    name with blocks intact, then the games in the preset order. No gaps."""
    api = badge_api
    api.place_badge(1, -1, 120)                  # Leaf, far away
    api.place_badge(4, -1, 60)                   # Window 2x2 block
    api.place_badge(0, -1, 200)                  # Sun
    state = api.sort_preset("az", 4)
    cells = sorted(_home_cells(state))
    assert cells == list(range(24)), f"gaps left: {cells}"
    system = sorted(((s["pos"], s["key"]) for s in state["system"] if s["folder"] == -1 and not s.get("hole")))
    assert [p for p, _ in system] == [0, 1, 2, 3, 4]          # NAND 0,1,2 + the one from cell 8, then the Game Card
    assert system[-1][1] == "cart"
    assert state["folderPos"][0] == 5                          # folder right after the Game Card
    badges = sorted(state["badges"]["placed"], key=lambda b: b["pos"])
    assert [b["name"] for b in badges[:2]] == ["Leaf", "Sun"] and [b["pos"] for b in badges[:2]] == [6, 7]
    assert sorted(b["pos"] for b in badges[2:]) == [8, 9, 12, 13]     # Window block, first area that fits
    games = sorted((i for i in state["items"] if i["folder"] == -1), key=lambda i: i["pos"])
    assert [g["pos"] for g in games] == [10, 11] + list(range(14, 24))  # games fill what the block left
    assert [g["name"] for g in games] == sorted((g["name"] for g in games), key=str.lower)
    assert state["launcherDirty"] is True        # system items moved: inject expected


def test_newly_installed_badges_force_reimport(monkeypatch):
    api = build_api(mock=True)
    api.get_state()
    api.move_to_position("g:0", -1, 40)
    (api.console.extdata_dir.parent / "000014d1").mkdir()
    monkeypatch.setattr(api.save3ds, "import_", lambda *args: pytest.fail("must not write"))
    assert "changed" in api.write_sd()["error"]


def test_serialized_api_preserves_native_bridge_signatures():
    import inspect
    api = build_api(mock=True)
    assert inspect.getfullargspec(api.move_to_position).args == ["self", "key", "folder", "pos", "rows"]
    assert inspect.getfullargspec(api.place_badge).args == ["self", "badge", "folder", "pos", "rows"]


def test_failed_preparation_never_imports_to_sd(badge_api, monkeypatch):
    api = badge_api
    api.place_badge(0, -1, 20)
    api.swap_items("n:0", "g:0")
    monkeypatch.setattr(api, "_write_launcher", lambda *a, **kw: (_ for _ in ()).throw(OSError("prepare failed")))
    monkeypatch.setattr(api.save3ds, "import_", lambda *a: pytest.fail("must prepare everything first"))
    with pytest.raises(OSError, match="prepare failed"):
        api.write_sd()
    assert api.get_state()["staged"]
    assert api.get_state()["recovery"] is None
