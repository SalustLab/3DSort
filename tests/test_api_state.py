"""Estado da Api em modo mock: merge de apps NAND (Launcher.dat) + jogos SD."""
from app import MOCK_CART_POS, build_api

NAND_HOME_POSITIONS = [0, 1, 2, 8]        # apps NAND no home grid do mock
FOLDER_TILE_POS = 9                       # tile da pasta "Homebrew" no home grid
GAME_POSITIONS = [3, 4, 5, 6, 7, 10, 11, 12, 13, 14, 15, 16]


def home(system):
    return [s for s in system if s["folder"] == -1]


def test_state_has_system_items_with_names_and_icons():
    st = build_api(mock=True).get_state()
    assert [s["pos"] for s in home(st["system"])] == NAND_HOME_POSITIONS + [MOCK_CART_POS]
    names = {s["name"] for s in st["system"]}
    assert "System Settings" in names and "Game Card" in names
    assert all(s["icon"] for s in st["system"] if s["key"] != "cart")
    # com o container mock presente, o layout do sistema e editavel
    assert st["launcherWritable"] is True
    assert not any(s["pinned"] for s in st["system"])
    assert all(s["key"] == "cart" or s["key"].startswith("n:") for s in st["system"])


def test_launcher_folder_exposed_with_nand_member():
    st = build_api(mock=True).get_state()
    assert st["folderNames"] == {0: "Homebrew"}
    assert st["folderPos"] == {0: FOLDER_TILE_POS}
    inside = [s for s in st["system"] if s["folder"] == 0]
    assert [(s["pos"], s["name"]) for s in inside] == [(0, "Health & Safety")]


def test_game_items_expose_real_positions():
    st = build_api(mock=True).get_state()
    assert [i["pos"] for i in st["items"]] == GAME_POSITIONS


def test_fallback_without_launcher_infers_gaps():
    api = build_api(mock=True, no_launcher=True)
    st = api.get_state()
    # sem Launcher.dat, o tile da pasta tambem vira lacuna anonima
    assert [s["pos"] for s in st["system"]] == NAND_HOME_POSITIONS + [FOLDER_TILE_POS]
    assert all(s["name"] == "System app" for s in st["system"])
    assert all(s["icon"] is None for s in st["system"])
    assert st["launcherWritable"] is False
    assert all(s["pinned"] for s in st["system"])


def test_write_preserves_position_multiset():
    api = build_api(mock=True)
    st = api.get_state()
    first = st["items"][0]["slot"]
    api.move_item(first, None)  # manda o primeiro jogo para o fim
    api.write_sd()
    st2 = api.import_sd()
    assert [i["pos"] for i in st2["items"]] == GAME_POSITIONS
    assert st2["items"][-1]["slot"] == first


def test_swap_items_exchanges_only_the_two_positions():
    api = build_api(mock=True)
    st = api.get_state()
    a, b = st["items"][0]["slot"], st["items"][5]["slot"]
    before = {i["slot"]: i["pos"] for i in st["items"]}
    st2 = api.swap_items(a, b)
    after = {i["slot"]: i["pos"] for i in st2["items"]}
    assert after[a] == before[b]
    assert after[b] == before[a]
    # ninguem mais se mexe — a razao de existir do swap
    others = {s: p for s, p in before.items() if s not in (a, b)}
    assert {s: after[s] for s in others} == others
    assert st2["staged"][-1].startswith("Swapped")


def test_reset_staging_discards_all_and_allows_redo():
    api = build_api(mock=True)
    st = api.get_state()
    base = [(i["slot"], i["pos"], i["folder"]) for i in st["items"]]
    api.swap_items(base[0][0], base[1][0])
    api.set_folder(base[2][0], 0)
    st2 = api.reset_staging()
    assert st2["staged"] == []
    assert [(i["slot"], i["pos"], i["folder"]) for i in st2["items"]] == base
    assert st2["canRedo"] is True  # reset e recuperavel via redo


def test_folder_move_gets_position_after_nand_member():
    api = build_api(mock=True)
    st = api.get_state()
    slot = st["items"][0]["slot"]
    api.set_folder(slot, 0)
    api.write_sd()
    st2 = api.import_sd()
    it = next(i for i in st2["items"] if i["slot"] == slot)
    # posicao 0 da pasta e do Health & Safety (NAND): jogo entra na 1
    assert (it["folder"], it["pos"]) == (0, 1)
