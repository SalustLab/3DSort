"""A pending NAND inject belongs to the card it was written for.

Up to v1.4.0 the marker was a single workdir file: write card A with a system
layout change, switch to card B, and B showed "NAND inject pending" for A's
payload. Cancel or Mark as done on B then dropped A's pending inject, and A's
next import read the pre-inject dump as if the inject never happened.
"""
import json
from pathlib import Path

from app import build_api

SETTINGS = "n:0"   # System Settings, home pos 0
FOLDER = "f:0"     # "Homebrew" tile, home pos 9


def second_card(api, id1="2" * 32):
    """Another SD card used in the same console: same id0, its own id1."""
    sd = Path(api.sd_root).parent / f"sd-{id1[:4]}"
    (sd / "Nintendo 3DS" / ("0" * 32) / id1 / "extdata" / "00000000" / "0000008f").mkdir(parents=True)
    return sd


def write_launcher_change(api):
    api.get_state()
    api.swap_items(SETTINGS, FOLDER)
    st = api.write_sd()
    assert st["pendingInject"] is not None
    return st


def test_pending_inject_is_not_shown_on_another_card():
    api = build_api(mock=True)
    card_a = Path(api.sd_root)
    write_launcher_change(api)
    st = api.set_sd_root(str(second_card(api)))
    assert "error" not in st
    assert st["pendingInject"] is None
    st = api.set_sd_root(str(card_a))
    assert st["pendingInject"] is not None


def test_another_card_cannot_cancel_or_confirm_the_pending_inject():
    api = build_api(mock=True)
    card_a = Path(api.sd_root)
    write_launcher_change(api)
    api.set_sd_root(str(second_card(api)))
    assert "No pending inject" in api.cancel_inject()["error"]
    api.confirm_inject()   # nothing pending on this card: must not touch card A's
    st = api.set_sd_root(str(card_a))
    assert st["pendingInject"] is not None
    assert (card_a / "3DSort" / "homemenu_save_new.bin").is_file()


def test_each_card_keeps_its_own_pending_inject():
    api = build_api(mock=True)
    first = write_launcher_change(api)["pendingInject"]
    api.set_sd_root(str(second_card(api)))
    assert api.get_state()["pendingInject"] is None
    a_marker = api.workdir / "pending_inject" / f"{'0' * 32}_{'1' * 32}.json"
    assert a_marker.is_file()
    assert json.loads(a_marker.read_text(encoding="utf-8"))["sha"] == first["sha"]
    assert not (api.workdir / "pending_inject" / f"{'0' * 32}_{'2' * 32}.json").exists()


def test_legacy_marker_is_adopted_only_by_its_own_card():
    api = build_api(mock=True)
    card_a = Path(api.sd_root)
    write_launcher_change(api)
    # Recreate the v1.4.0 layout: one shared marker in the workdir.
    marker = api._pending_path()
    legacy = api.workdir / "pending_inject.json"
    marker.replace(legacy)
    card_b = second_card(api)
    st = api.set_sd_root(str(card_b))
    assert st["pendingInject"] is None
    assert legacy.exists(), "another card must leave the old marker for its owner"
    st = api.set_sd_root(str(card_a))
    assert st["pendingInject"] is not None
    assert not legacy.exists()


def test_legacy_marker_with_a_stale_payload_is_not_adopted():
    api = build_api(mock=True)
    write_launcher_change(api)
    marker = api._pending_path()
    legacy = api.workdir / "pending_inject.json"
    info = json.loads(marker.read_text(encoding="utf-8"))
    marker.unlink()
    legacy.write_text(json.dumps({**info, "sha": "00" * 32}), encoding="utf-8")
    assert api.import_sd()["pendingInject"] is None
    assert legacy.exists()
