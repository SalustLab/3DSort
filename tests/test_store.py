import json

import pytest

from core.store import Staging, Backups


def test_commit_undo_redo():
    s = Staging({"order": [1, 2, 3]})
    s.commit("Moved A", {"order": [2, 1, 3]})
    s.commit("Moved B", {"order": [3, 2, 1]})
    assert s.state == {"order": [3, 2, 1]}
    assert s.staged == ["Moved A", "Moved B"]
    s.undo()
    assert s.state == {"order": [2, 1, 3]}
    assert s.staged == ["Moved A"]
    s.redo()
    assert s.state == {"order": [3, 2, 1]}
    assert s.staged == ["Moved A", "Moved B"]


def test_undo_redo_empty_raise():
    s = Staging({})
    with pytest.raises(IndexError):
        s.undo()
    with pytest.raises(IndexError):
        s.redo()


def test_new_commit_clears_redo():
    s = Staging({"v": 0})
    s.commit("a", {"v": 1})
    s.undo()
    s.commit("b", {"v": 2})
    with pytest.raises(IndexError):
        s.redo()


def test_clear_after_write():
    s = Staging({"v": 0})
    s.commit("a", {"v": 1})
    s.clear()
    assert s.staged == []
    with pytest.raises(IndexError):
        s.undo()
    assert s.state == {"v": 1}


def test_backup_create_restore_and_history(tmp_path):
    src = tmp_path / "extdata"
    (src / "user").mkdir(parents=True)
    (src / "user" / "SaveData.dat").write_bytes(b"AAA")
    (src / "icon").write_bytes(b"II")
    b = Backups(tmp_path / "backups")
    ref = b.create(src, kind="auto", note="antes do write")
    (src / "user" / "SaveData.dat").write_bytes(b"BBB")
    entries = b.history()
    assert len(entries) == 1
    assert entries[0]["kind"] == "auto"
    assert entries[0]["id"] == ref["id"]
    b.restore(ref["id"], src)
    assert (src / "user" / "SaveData.dat").read_bytes() == b"AAA"
    assert (src / "icon").read_bytes() == b"II"


def test_backup_keeps_last_n(tmp_path):
    src = tmp_path / "x"
    src.mkdir()
    (src / "f").write_bytes(b"1")
    b = Backups(tmp_path / "backups", keep=3)
    ids = [b.create(src, kind="auto", note=str(i))["id"] for i in range(5)]
    left = {e["id"] for e in b.history()}
    assert left == set(ids[-3:])


def test_history_survives_reopen(tmp_path):
    src = tmp_path / "x"
    src.mkdir()
    (src / "f").write_bytes(b"1")
    Backups(tmp_path / "b").create(src, kind="manual", note="n")
    assert len(Backups(tmp_path / "b").history()) == 1
