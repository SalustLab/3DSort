"""Region resolution on a card that carries more than one HOME menu extdata
(the CTRTransfer case: two regions under one id0)."""
import json
from pathlib import Path

import pytest

from app import Api, gm9_dump_script
from core.sdcard import Save3ds, find_consoles
from core.store import Backups

MOVABLE = bytes(0x110) + bytes(16) + bytes(0x20)
ID0 = "ff084737d59d71f775c89e9728d26cd5"


def two_region_sd(tmp_path, jpn_mtime=1_000_000, usa_mtime=2_000_000):
    """A card as a region-changed console leaves it: both HOME menu extdata under
    one id0, the live one written more recently."""
    import os
    sd = tmp_path / "sd"
    for eid, mtime in (("00000082", jpn_mtime), ("0000008f", usa_mtime)):
        d = sd / "Nintendo 3DS" / ID0 / ("b" * 32) / "extdata" / "00000000" / eid
        d.mkdir(parents=True)
        f = d / "00000001"
        f.write_bytes(b"x")
        os.utime(f, (mtime, mtime))
        os.utime(d, (mtime, mtime))
    keys = sd / "3DSort"
    keys.mkdir(parents=True)
    (keys / "movable.sed").write_bytes(MOVABLE)
    (keys / "boot9.bin").write_bytes(b"9")
    return sd


def api_for(sd, tmp_path, region_choices=None):
    s3 = Save3ds(tmp_path / "nope.exe", tmp_path / "no_boot9", tmp_path / "no_movable")
    return Api(s3, sd, tmp_path / "work", Backups(tmp_path / "bk"),
               region_choices=region_choices)


def test_settings_round_trip_the_region_choice(tmp_path):
    sd = two_region_sd(tmp_path)
    api = api_for(sd, tmp_path, region_choices={ID0: "USA"})
    api._save_settings()
    written = json.loads((Path(api.workdir).parent / "settings.json").read_text("utf-8"))
    assert written["region_by_id0"] == {ID0: "USA"}


def test_settings_default_to_empty(tmp_path):
    api = api_for(two_region_sd(tmp_path), tmp_path)
    assert api._region_choices == {}


PICK = "Several HOME menu layouts"


def test_two_regions_without_a_choice_stops_and_asks(tmp_path):
    """Nothing is imported on a guess: the newest-written one is only a
    suggestion, and picking the dead set means editing a layout that no console
    ever reads."""
    api = api_for(two_region_sd(tmp_path), tmp_path)
    assert PICK in api.import_sd()["error"]
    assert api.console is None
    assert [c.region for c in api._candidates] == ["USA", "JPN"]


def test_stored_choice_resolves_without_asking(tmp_path):
    api = api_for(two_region_sd(tmp_path), tmp_path, region_choices={ID0: "JPN"})
    try:
        api.import_sd()          # stops later at the missing save3ds binary
    except FileNotFoundError:
        pass
    assert api.console.region == "JPN"


def test_stale_stored_choice_is_discarded(tmp_path):
    """The user renamed or deleted the old region's extdata by hand: the stored
    answer now names nothing, so ask again rather than fall back silently."""
    sd = two_region_sd(tmp_path)
    (sd / "Nintendo 3DS" / ID0 / ("b" * 32) / "extdata" / "00000000" /
     "00000082").rename(sd / "Nintendo 3DS" / ID0 / ("b" * 32) / "extdata" /
                        "00000000" / "00000082_bak")
    api = api_for(sd, tmp_path, region_choices={ID0: "JPN"})
    try:
        api.import_sd()
    except FileNotFoundError:
        pass
    # one candidate left, so it resolves to it AND forgets the dead answer
    assert api.console.region == "USA"
    assert ID0 not in api._region_choices


def test_single_region_card_never_asks(tmp_path):
    sd = two_region_sd(tmp_path)
    import shutil
    shutil.rmtree(sd / "Nintendo 3DS" / ID0 / ("b" * 32) / "extdata" /
                  "00000000" / "00000082")
    api = api_for(sd, tmp_path)
    try:
        api.import_sd()
    except FileNotFoundError:
        pass
    assert api.console.region == "USA"


def test_nand_save_id_refuses_to_guess(tmp_path):
    """Upstream defaulted to USA with no console resolved. A default here is how
    a wrong save id reaches the write path."""
    api = api_for(two_region_sd(tmp_path), tmp_path)
    with pytest.raises(RuntimeError):
        api._nand_save_id()


def test_region_candidates_lists_both_with_the_newest_suggested(tmp_path):
    api = api_for(two_region_sd(tmp_path), tmp_path)
    api.import_sd()
    rows = api.region_candidates()["candidates"]
    assert [r["region"] for r in rows] == ["USA", "JPN"]
    assert rows[0]["suggested"] is True and rows[1]["suggested"] is False
    assert rows[0]["saveId"] == "0002008f" and rows[1]["saveId"] == "00020082"
    assert rows[0]["lastUsed"] > rows[1]["lastUsed"]
    # no save3ds binary in this fixture, so the contents could not be read
    assert rows[0]["games"] is None and rows[0]["error"]


def test_region_candidates_does_not_count_the_home_grid_as_a_folder():
    """folder -1 is the home grid (savedata.py OFF_FOLDER), not a folder.
    Counting it read one folder too many on every card: the real card reported
    2 where the console shows 1, and this mock card reported 1 where it has
    none."""
    from app import build_api
    api = build_api(mock=True)
    api.get_state()
    assert set(api.staging.state["folders"].values()) == {-1}, "mock card shape"
    row = api.region_candidates()["candidates"][0]
    assert row["error"] is None
    assert row["folders"] == 0


def test_set_region_stores_the_choice_and_reimports(tmp_path):
    api = api_for(two_region_sd(tmp_path), tmp_path)
    api.import_sd()
    try:
        api.set_region("JPN")
    except FileNotFoundError:
        pass                      # missing save3ds binary, past the point tested
    assert api.console.region == "JPN"
    assert api._region_choices[ID0] == "JPN"


def test_set_region_rejects_a_region_not_on_the_card(tmp_path):
    api = api_for(two_region_sd(tmp_path), tmp_path)
    api.import_sd()
    assert "No EUR" in api.set_region("EUR")["error"]


def test_set_region_refused_while_an_inject_is_pending(tmp_path):
    """The published payload was built for the other region's save id. Switching
    now would leave a file on the card aimed at a NAND path the user is no longer
    editing."""
    api = api_for(two_region_sd(tmp_path), tmp_path)
    api.import_sd()
    api._pending_path().parent.mkdir(parents=True, exist_ok=True)
    api._pending_path().write_text(json.dumps(
        {"sha": "00", "when": "now", "changes": 1, "badgeDependent": False}),
        encoding="utf-8")
    err = api.set_region("JPN")["error"]
    assert "inject" in err.lower()
    assert api._region_choices == {}


def test_setup_stage_is_pick_region(tmp_path):
    api = api_for(two_region_sd(tmp_path), tmp_path)
    assert api.get_setup_state()["stage"] == "pick_region"


def test_setup_stage_asks_for_keys_before_the_region(tmp_path):
    """The picker shows what is inside each layout, so it is worth nothing until
    the dump has put boot9 and movable on the card."""
    sd = two_region_sd(tmp_path)
    (sd / "3DSort" / "boot9.bin").unlink()
    api = api_for(sd, tmp_path)
    assert api.get_setup_state()["stage"] == "no_keys"


def resolved_api(sd, tmp_path, region="USA"):
    api = api_for(sd, tmp_path, region_choices={ID0: region})
    api._candidates = find_consoles(sd, prefer_id0=ID0)
    api.console = api._resolve_console()
    return api


def test_find_container_prefers_the_picked_regions_dump(tmp_path):
    """The new dump script writes one file per save id. The picked region's is
    the container; homemenu_save.bin stays as the anchor the inject script reads,
    so the picked pair is promoted into it."""
    sd = two_region_sd(tmp_path)
    api = resolved_api(sd, tmp_path)
    sd3 = sd / "3DSort"
    (sd3 / "homemenu_save_00020082.bin").write_bytes(b"JPN-container")
    (sd3 / "homemenu_save_0002008f.bin").write_bytes(b"USA-container")
    (sd3 / "homemenu_save_0002008f.bin.sha").write_bytes(b"\x01" * 32)
    assert api._find_container().read_bytes() == b"USA-container"
    assert (sd3 / "homemenu_save.bin").read_bytes() == b"USA-container"
    assert (sd3 / "homemenu_save.bin.sha").read_bytes() == b"\x01" * 32


def test_find_container_falls_back_to_an_old_dump(tmp_path):
    """A card last dumped by the upstream script has only homemenu_save.bin. It
    may be the wrong region, which the CMAC check now reports instead of hiding."""
    sd = two_region_sd(tmp_path)
    api = resolved_api(sd, tmp_path)
    (sd / "3DSort" / "homemenu_save.bin").write_bytes(b"old-dump")
    assert api._find_container().read_bytes() == b"old-dump"


def test_launcher_error_explains_a_cmac_failure(tmp_path):
    """Upstream swallowed this: the grid then showed every system app pinned and
    no folders, which looks like a layout rather than a failure."""
    sd = two_region_sd(tmp_path)
    api = resolved_api(sd, tmp_path)
    (sd / "3DSort" / "homemenu_save.bin").write_bytes(b"wrong-region-container")

    class Boom(Save3ds):
        def build_nand_tree(self, workdir, container, save_id):
            return Path(workdir) / "nand"

        def nand_extract(self, save_id, nand_root, out_dir):
            raise RuntimeError("Signature mismatch")

    api.save3ds = Boom(tmp_path / "x.exe", tmp_path / "b9", tmp_path / "mv")
    api._read_launcher()
    assert api.container_path is None
    assert "0002008f" in api._launcher_error
    assert "USA" in api._launcher_error


def test_card_identity_guard_accepts_a_non_suggested_pick(tmp_path):
    """The guard re-derived the console with find_console and demanded it equal
    self.console, so picking the OLDER region - the whole reason the picker
    exists - made every write fail with 'Card changed or disconnected'. The
    guard's job is the CARD's identity, not a second opinion on the region."""
    sd = two_region_sd(tmp_path)
    api = resolved_api(sd, tmp_path, region="JPN")   # not the ranking winner
    assert api.console.region == "JPN"
    assert api._connected_card_error() is None


def test_card_identity_guard_still_catches_a_swapped_card(tmp_path):
    """The other half: a different card under the same drive letter, or the
    picked extdata gone, must still be refused."""
    sd = two_region_sd(tmp_path)
    api = resolved_api(sd, tmp_path, region="JPN")
    import shutil
    shutil.rmtree(sd / "Nintendo 3DS" / ID0 / ("b" * 32) / "extdata" /
                  "00000000" / "00000082")
    assert "Card changed" in api._connected_card_error()


def test_backup_records_the_region_it_came_from(tmp_path):
    from core.store import Backups
    src = tmp_path / "ext" / "user"
    src.mkdir(parents=True)
    (src / "SaveData.dat").write_bytes(b"x")
    bk = Backups(tmp_path / "bk")
    entry = bk.create(tmp_path / "ext", kind="manual", note="n",
                      meta={"extdataId": "000000000000008f"})
    assert entry["extdataId"] == "000000000000008f"
    assert bk.history()[0]["extdataId"] == "000000000000008f"


def test_restore_refuses_a_backup_from_the_other_region(tmp_path):
    """A backup holds one region's SaveData.dat. Restoring it while the other
    region is picked would stage USA's layout for a write into the JPN extdata:
    the SD game tids match across regions, the system apps and folder ids do
    not."""
    from app import build_api
    api = build_api(mock=True)
    api.get_state()
    entry = api.backup_manual()["history"][0]
    # the backup was taken under the mock card's own region; pretend the user
    # has since switched to the other one
    api.backups._hist.write_text(json.dumps(
        {**entry, "extdataId": "000000000000008f"}) + "\n", encoding="utf-8")
    api.console = api.console.__class__(api.console.sd_root, api.console.id0,
                                        api.console.id1, "JPN",
                                        "000000000000082")
    err = api.restore_backup(entry["id"])["error"]
    assert "different HOME menu layout" in err


def test_write_launcher_refuses_an_unverified_container(tmp_path):
    """The three GM9 sha gates already fail safe, but aborting a script on the
    console is a worse message than refusing on the PC."""
    sd = two_region_sd(tmp_path)
    api = resolved_api(sd, tmp_path)
    api.container_path = sd / "3DSort" / "homemenu_save.bin"
    api.container_path.write_bytes(b"unverified")
    api._launcher_writable = False
    api._launcher_error = "does not decrypt as the USA save (0002008f)"
    with pytest.raises(RuntimeError, match="0002008f"):
        api._write_launcher({}, 0)
