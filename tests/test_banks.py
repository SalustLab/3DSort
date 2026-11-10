"""Discovery uses temporary cards only."""
from core.banks import discover


def test_ordinary_card(tmp_path):
    (tmp_path / "Nintendo 3DS").mkdir()
    assert discover(tmp_path) == {"detected": False, "banks": [], "warnings": []}


def test_slots_and_names_are_read_only(tmp_path):
    bank = tmp_path / "3DSBank"
    (bank / "Slot1" / ("a" * 32)).mkdir(parents=True)
    (tmp_path / "Nintendo 3DS").mkdir()
    ini = bank / "3DSBank.ini"
    raw = b"[3DSBANK]\nFOLDER_SLOT = 0\nSLOT_NAME_0 = Favorites\n"
    ini.write_bytes(raw)
    result = discover(tmp_path)
    assert result["detected"]
    assert result["banks"][0]["slot"] is None
    assert result["banks"][0]["name"] == "Active bank"  # uncertainty lives in slot=None, not the label
    assert result["banks"][1]["slot"] == 1
    assert not any(b["editable"] for b in result["banks"])
    assert ini.read_bytes() == raw


def test_contradictory_slot_is_unknown(tmp_path):
    bank = tmp_path / "3DSBank"
    (bank / "Slot0").mkdir(parents=True)
    (tmp_path / "Nintendo 3DS").mkdir()
    (bank / "3DSBank.ini").write_text("[3DSBANK]\nFOLDER_SLOT=0\n")
    assert discover(tmp_path)["banks"][0]["slot"] is None


def test_unrelated_directories_are_not_installation(tmp_path):
    (tmp_path / "3DSBank" / "Slot40").mkdir(parents=True)
    assert not discover(tmp_path)["detected"]


def test_inaccessible_slot_does_not_abort_discovery(tmp_path, monkeypatch):
    from pathlib import Path
    bank = tmp_path / "3DSBank"
    blocked = bank / "Slot1"
    blocked.mkdir(parents=True)
    (bank / "Slot2" / ("a" * 32)).mkdir(parents=True)
    original = Path.iterdir

    def enumerate_path(path):
        if path == blocked:
            raise PermissionError("Synthetic denied directory")
        return original(path)

    monkeypatch.setattr(Path, "iterdir", enumerate_path)
    result = discover(tmp_path)
    assert result["detected"]
    assert [b["id"] for b in result["banks"]] == ["slot:1", "slot:2"]
    assert any("Slot 1" in w for w in result["warnings"])


def test_missing_active_directory_does_not_hide_slots(tmp_path):
    (tmp_path / "3DSBank" / "Slot3" / ("a" * 32)).mkdir(parents=True)
    result = discover(tmp_path)
    assert result["detected"]
    assert [b["id"] for b in result["banks"]] == ["slot:3"]
    assert not any(b["active"] for b in result["banks"])
