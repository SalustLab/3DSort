"""Bank integration uses synthetic cards and a path-sensitive extraction helper."""
import shutil
from pathlib import Path
import pytest
from app import build_api, BANK_MUTATIONS, make_mock_extdata
from core.write_api import tree_hashes


def bank_api():
    api = build_api(mock=True)
    api.import_sd()
    slot = api.sd_root / "3DSBank" / "Slot1"
    home = slot / ("0" * 32) / ("1" * 32) / "extdata" / "00000000" / "0000008f"
    make_mock_extdata(home)
    # An inactive collection really differs from the active one.
    from core.savedata import SaveData
    raw = bytearray((home / "user" / "SaveData.dat").read_bytes())
    import struct
    struct.pack_into("<Q", raw, 8, 0x0004000000abcdef)
    (home / "user" / "SaveData.dat").write_bytes(raw)
    (slot.parent / "3DSBank.ini").write_text("[3DSBANK]\nSLOT_NAME_1=Archive\n")
    original = api.save3ds.extract
    def extract(eid, root, out):
        if Path(root) != api.sd_root:
            source = Path(root) / "Nintendo 3DS" / ("0" * 32) / ("1" * 32) / "extdata" / "00000000" / eid[-8:]
            shutil.copytree(source, out)
        else:
            original(eid, root, out)
    api.save3ds.extract = extract
    return api, home


def test_switching_and_original_bytes():
    api, home = bank_api()
    before = tree_hashes(api.sd_root)
    active = api.get_state()
    inactive = api.select_bank("slot:1")
    assert "error" not in inactive, inactive
    assert inactive["banks"]["readOnly"]
    assert inactive["items"][0]["tid"] == "0004000000abcdef"
    assert inactive["items"] != active["items"]
    assert not inactive["system"]
    assert not inactive["launcherWritable"]
    assert not inactive["canUndo"]
    assert tree_hashes(api.sd_root) == before
    restored = api.select_bank("active")
    assert restored["items"] == active["items"]
    assert not restored["canUndo"]


@pytest.mark.parametrize("method", sorted(BANK_MUTATIONS))
def test_direct_mutations_rejected(method):
    import inspect
    api, home = bank_api()
    api.select_bank("slot:1")
    before = tree_hashes(api.sd_root)
    fn = getattr(api, method)
    args = [None for p in inspect.signature(fn).parameters.values() if p.default is inspect.Parameter.empty]
    result = fn(*args)
    assert "read-only" in result["error"]
    assert tree_hashes(api.sd_root) == before


def test_confirmation_and_failed_selection_preserve_staging():
    api, home = bank_api()
    api.move_item(0)
    staged = api.staging
    assert api.select_bank("slot:1")["needsConfirm"]
    assert api.staging is staged
    shutil.rmtree(home)
    assert "error" in api.select_bank("slot:1", True)
    assert api.staging is staged
    assert api._selected_bank == "active"
    assert "error" in api.select_bank(str(home), True)


def test_recovery_blocks_switch():
    api, home = bank_api()
    transaction = api._transaction_dir()
    transaction.mkdir()
    (transaction / "journal.json").write_text("invalid")
    assert "pending" in api.select_bank("slot:1")["error"]


def test_external_active_rename_blocks_mutation():
    api, home = bank_api()
    (api.sd_root / "Nintendo 3DS").rename(api.sd_root / "removed")
    assert "changed" in api.move_item(0)["error"]


def test_ordinary_card_metadata_is_backward_compatible():
    api = build_api(mock=True)
    state = api.import_sd()
    assert not state["banks"]["detected"]
    assert not state["banks"]["readOnly"]
    assert api.move_item(0)["canUndo"]


def test_ambiguous_region_and_id1_refused():
    api, home = bank_api()
    other = home.parent / "00000098"
    shutil.copytree(home, other)
    assert "ambiguous" in api.select_bank("slot:1")["error"]
    shutil.rmtree(other)
    other_id1 = home.parents[2].parent / ("2" * 32)
    shutil.copytree(home.parents[2], other_id1)
    assert "ambiguous" in api.select_bank("slot:1")["error"]


def test_incompatible_save_preserves_active_view():
    api, home = bank_api()
    active = api.get_state()["items"]
    (home / "user" / "SaveData.dat").write_bytes(b"invalid")
    assert "error" in api.select_bank("slot:1")
    assert api.get_state()["items"] == active


def test_external_inactive_change_is_reported():
    api, home = bank_api()
    api.select_bank("slot:1")
    shutil.rmtree(home)
    banks = api.get_state()["banks"]
    # Actionable: shown in the header. Discovery diagnostics stay in "warnings".
    assert any("re-import" in a.lower() for a in banks["alerts"])
    assert not any("snapshot" in w for w in banks["warnings"])


def test_active_bank_alerts_only_when_action_is_needed():
    api, _ = bank_api()
    assert api.get_state()["banks"]["alerts"] == []
    api._bank_anchor = ("replaced",)  # directory identity no longer matches the import
    assert any("re-import" in a.lower() for a in api.get_state()["banks"]["alerts"])


# ---- console identity: a card can hold several ID0 folders (multi-console) ----
# Synthetic movable with zero KeyY -> this known ID0 (same vector as test_sdcard).
MOVABLE = bytes(0x110) + bytes(16) + bytes(0x20)
LIVE_ID0 = "ff084737d59d71f775c89e9728d26cd5"


def _identity_api():
    """Bank fixture whose inactive extraction reads whichever ID0 was isolated, plus
    the console's movable on the card. The fixture slot's own ID0 is unrelated."""
    api, home = bank_api()
    (api.sd_root / "3DSort").mkdir(exist_ok=True)
    (api.sd_root / "3DSort" / "movable.sed").write_bytes(MOVABLE)
    def extract(eid, root, out):
        if Path(root) == api.sd_root:
            return original_extract(eid, root, out)
        homes = [p for p in Path(root).rglob(eid[-8:]) if p.is_dir()]
        assert len(homes) == 1, homes  # the isolated tree holds exactly one candidate
        shutil.copytree(homes[0], out)
    original_extract = api.save3ds.extract
    api.save3ds.extract = extract
    return api, home


def _add_slot_id0(home, id0, tid):
    slot = home.parents[4]  # .../3DSBank/Slot1
    target = slot / id0 / ("1" * 32) / "extdata" / "00000000" / "0000008f"
    make_mock_extdata(target)
    import struct
    raw = bytearray((target / "user" / "SaveData.dat").read_bytes())
    struct.pack_into("<Q", raw, 8, tid)
    (target / "user" / "SaveData.dat").write_bytes(raw)


def test_inactive_bank_never_shows_another_consoles_layout():
    api, _ = _identity_api()  # slot holds only an ID0 the movable does not own
    active = api.get_state()["items"]
    result = api.select_bank("slot:1")
    assert "error" in result
    assert api.get_state()["items"] == active and not api.get_state()["banks"]["readOnly"]


def test_inactive_bank_picks_the_movable_id0_among_several():
    api, home = _identity_api()
    _add_slot_id0(home, LIVE_ID0, 0x0004000000c0ffee)
    state = api.select_bank("slot:1")
    assert "error" not in state, state
    assert state["items"][0]["tid"] == "0004000000c0ffee"  # not the unrelated folder's 0004000000abcdef


def test_inactive_bank_without_movable_evidence_refuses_several_id0():
    api, home = bank_api()  # no movable on the card
    _add_slot_id0(home, LIVE_ID0, 0x0004000000c0ffee)
    assert "ambiguous" in api.select_bank("slot:1")["error"]


def test_returning_to_active_reestablishes_identity_guard():
    api, _ = bank_api()
    api.select_bank("slot:1")
    api._bank_anchor = None  # whatever the inactive session left behind
    state = api.select_bank("active")
    assert "error" not in state
    assert api._bank_anchor is not None and api._bank_anchor == api._active_anchor()
    (api.sd_root / "Nintendo 3DS").rename(api.sd_root / "Nintendo 3DS.old")  # external bank switch
    assert "changed" in api.place_badge(0, 0)["error"]
    assert "changed" in api.write_sd()["error"]
