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
    assert result["banks"][0]["name"] == "Favorites"
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
