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
    assert any("snapshot" in w for w in api.get_state()["banks"]["warnings"])
