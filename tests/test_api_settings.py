"""Functional SETTINGS: switching the SD drive and the backups folder (mock)."""
import json
from pathlib import Path

from app import build_api


def make_fake_sd(root: Path) -> Path:
    (root / "Nintendo 3DS" / ("2" * 32) / ("3" * 32) / "extdata" /
     "00000000" / "0000008f").mkdir(parents=True)
    return root


def test_list_drives_includes_current():
    api = build_api(mock=True)
    api.get_state()
    r = api.list_drives()
    cur = [d for d in r["drives"] if d["current"]]
    assert len(cur) == 1 and cur[0]["root"] == str(api.sd_root)


def test_set_sd_root_switches_and_reimports(tmp_path):
    api = build_api(mock=True)
    api.get_state()
    api.folder_create()  # staged, must vanish with the re-import
    new_sd = make_fake_sd(tmp_path / "sd2")
    st = api.set_sd_root(str(new_sd))
    assert "error" not in st
    assert st["sd"]["root"] == str(new_sd)
    assert st["staged"] == []


def test_set_sd_root_invalid_path_keeps_current(tmp_path):
    api = build_api(mock=True)
    api.get_state()
    old = api.sd_root
    r = api.set_sd_root(str(tmp_path / "nope"))
    assert "error" in r and "Nintendo 3DS" in r["error"]
    assert api.sd_root == old


def test_set_backups_dir_moves_backups(tmp_path):
    api = build_api(mock=True)
    api.get_state()
    api.backup_manual()
    old_hist = api.backups.history()
    assert len(old_hist) == 1
    old_root = Path(api.backups.root)
    new_dir = tmp_path / "bk_new"
    st = api.set_backups_dir(str(new_dir))
    assert st["backups_dir"] == str(new_dir)
    assert [e["id"] for e in api.backups.history()] == [old_hist[0]["id"]]
    assert (new_dir / old_hist[0]["file"]).exists()
    assert not (old_root / old_hist[0]["file"]).exists()
    api.backup_manual()  # new backup lands in the new folder
    assert len(list(new_dir.glob("*.3dsl"))) == 2


def test_set_backups_dir_same_dir_is_noop():
    api = build_api(mock=True)
    api.get_state()
    st = api.set_backups_dir(str(api.backups.root))
    assert "error" not in st
    assert st["backups_dir"] == str(api.backups.root)


def test_set_backups_dir_empty_rejected():
    api = build_api(mock=True)
    api.get_state()
    assert "error" in api.set_backups_dir("   ")


def test_pick_backups_dir_applies_selection(tmp_path, monkeypatch):
    import app
    api = build_api(mock=True)
    api.get_state()
    monkeypatch.setattr(app, "pick_folder_native",
                        lambda initial: str(tmp_path / "picked"))
    st = api.pick_backups_dir()
    assert st["backups_dir"] == str(tmp_path / "picked")


def test_pick_backups_dir_cancel_keeps_current(monkeypatch):
    import app
    api = build_api(mock=True)
    api.get_state()
    old = str(api.backups.root)
    monkeypatch.setattr(app, "pick_folder_native", lambda initial: None)
    st = api.pick_backups_dir()
    assert "error" not in st and st["backups_dir"] == old


def test_settings_persisted_next_to_workdir(tmp_path):
    api = build_api(mock=True)
    api.get_state()
    new_sd = make_fake_sd(tmp_path / "sd2")
    api.set_sd_root(str(new_sd))
    api.set_backups_dir(str(tmp_path / "bk"))
    data = json.loads((Path(api.workdir).parent / "settings.json")
                      .read_text(encoding="utf-8"))
    assert data["sd_root"] == str(new_sd)
    assert data["backups_dir"] == str(tmp_path / "bk")
