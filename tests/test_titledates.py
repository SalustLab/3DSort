"""Release-date table (core/titledates.py) and the date sort presets."""
import gzip
import json

import pytest

from app import build_api
from core import titledates

MOCK_TID = 0x0004000000030000  # mock game slot 0; slot i = base + i*0x100


@pytest.fixture(autouse=True)
def reset_table():
    """Each test starts with an unloaded table and restores the module after."""
    titledates._table = None
    yield
    titledates._table = None


def test_release_date_reads_bundled_gz(tmp_path, monkeypatch):
    gz = tmp_path / "dates.json.gz"
    with gzip.open(gz, "wt", encoding="utf-8") as f:
        json.dump({"0004000000030000": "2011-12-04"}, f)
    monkeypatch.setattr(titledates, "TABLE_PATH", gz)
    assert titledates.release_date(MOCK_TID) == "2011-12-04"
    assert titledates.release_date(0xDEAD) is None


def test_missing_table_means_undated(tmp_path, monkeypatch):
    monkeypatch.setattr(titledates, "TABLE_PATH", tmp_path / "missing.gz")
    assert titledates.release_date(MOCK_TID) is None


def _game_order(st):
    """Mock game tids on the home grid, in visual (position) order."""
    return [i["tid"] for i in sorted(st["items"], key=lambda i: i["pos"])]


def test_sort_by_release_date_counts_day_month_year(monkeypatch):
    api = build_api(mock=True)
    st = api.get_state()
    tids = _game_order(st)
    a, b, c, d = tids[0], tids[1], tids[2], tids[3]
    # Same year+month (day decides), same year (month decides), year decides.
    monkeypatch.setattr(titledates, "_table", {
        a: "2011-12-04", b: "2011-12-03", c: "2011-11-30", d: "2010-12-31"})

    st = api.sort_preset("date_asc")
    got = _game_order(st)
    assert got[:4] == [d, c, b, a]
    assert set(got[4:]) == set(tids[4:])  # undated go last

    st = api.sort_preset("date_desc")
    got = _game_order(st)
    assert got[:4] == [a, b, c, d]
    assert set(got[4:]) == set(tids[4:])  # undated last in BOTH directions


def test_unknown_preset_is_a_friendly_error():
    api = build_api(mock=True)
    api.get_state()
    with pytest.raises(ValueError):
        api.sort_preset("nope")
