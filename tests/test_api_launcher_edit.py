"""v1.1: edicao staged do layout do sistema (apps NAND, pastas, Game Card) em mock.

O mock exercita o pipeline completo (swap entre tipos, lifecycle de pastas,
write com payload de injecao + recibo) com FakeSave3ds; so a crypto e fake.
"""
import hashlib
import json
import struct
from pathlib import Path

import pytest

from app import MOCK_CART_POS, build_api
from core.launcher import Launcher
from core.savedata import OFF_FOLDER_NUM

H_AND_S = "n:4"    # Health & Safety, dentro da pasta 0 (pos 0)
SETTINGS = "n:0"   # System Settings, home pos 0
FOLDER = "f:0"     # tile "Homebrew", home pos 9


def positions(st):
    """{key: (folder, pos)} de tudo que tem chave no estado."""
    out = {i["key"]: (i["folder"], i["pos"]) for i in st["items"]}
    out.update({s["key"]: (s["folder"], s["pos"]) for s in st["system"] if s["key"]})
    out.update({f"f:{fid}": (-1, p) for fid, p in st["folderPos"].items()})
    return out


def assert_only_moved(before, after, *keys):
    for k in set(before) | set(after):
        if k not in keys:
            assert after[k] == before[k], f"{k} se moveu sem participar do swap"


def test_swap_game_with_nand_exchanges_exactly():
    api = build_api(mock=True)
    before = positions(api.get_state())
    game = next(k for k, (f, p) in before.items() if k.startswith("g:") and p == 3)
    after = positions(api.swap_items(game, SETTINGS))
    assert after[game] == before[SETTINGS]
    assert after[SETTINGS] == before[game]
    assert_only_moved(before, after, game, SETTINGS)


def test_swap_nand_with_folder_tile():
    api = build_api(mock=True)
    before = positions(api.get_state())
    after = positions(api.swap_items(SETTINGS, FOLDER))
    assert after[SETTINGS] == before[FOLDER]
    assert after[FOLDER] == before[SETTINGS]
    assert_only_moved(before, after, SETTINGS, FOLDER)


def test_swap_cart_with_game():
    api = build_api(mock=True)
    before = positions(api.get_state())
    game = next(k for k, (f, p) in before.items() if k.startswith("g:") and p == 3)
    after = positions(api.swap_items("cart", game))
    assert after["cart"] == (-1, 3)
    assert after[game] == (-1, MOCK_CART_POS)
    assert_only_moved(before, after, "cart", game)


def test_swap_game_into_folder_container():
    api = build_api(mock=True)
    before = positions(api.get_state())
    game = next(k for k, (f, p) in before.items() if k.startswith("g:") and p == 3)
    after = positions(api.swap_items(game, H_AND_S))  # H&S esta na pasta 0, pos 0
    assert after[game] == (0, 0)
    assert after[H_AND_S] == (-1, 3)
    assert_only_moved(before, after, game, H_AND_S)


def test_folder_and_cart_stay_on_home_grid():
    api = build_api(mock=True)
    api.get_state()
    with pytest.raises(ValueError):
        api.swap_items(FOLDER, H_AND_S)  # tile de pasta iria para DENTRO da pasta
    with pytest.raises(ValueError):
        api.swap_items("cart", H_AND_S)
    with pytest.raises(ValueError):
        api.set_folder(SETTINGS + "", 99)  # pasta inexistente


def test_launcher_mutations_need_writable():
    api = build_api(mock=True, no_launcher=True)
    api.get_state()
    with pytest.raises(ValueError):
        api.swap_items(SETTINGS, "cart")
    with pytest.raises(ValueError):
        api.folder_create()


def test_undo_restores_launcher_state_exactly():
    api = build_api(mock=True)
    before = positions(api.get_state())
    api.swap_items(SETTINGS, FOLDER)
    api.set_folder(SETTINGS, 0)
    api.undo()
    api.undo()
    st = api.get_state()
    assert positions(st) == before
    assert st["launcherDirty"] is False


def test_set_folder_nand_in_and_out():
    api = build_api(mock=True)
    api.get_state()
    st = api.set_folder(SETTINGS, 0)
    got = positions(st)
    assert got[SETTINGS] == (0, 1)  # H&S ocupa a pos 0 da pasta; proxima livre = 1
    # a pos 0 liberada no home e tomada pela compactacao dos jogos
    assert min(p for k, (f, p) in got.items() if k.startswith("g:")) == 0
    st = api.set_folder(SETTINGS, -1)
    # de volta ao home: menor posicao livre depois da compactacao dos jogos
    assert positions(st)[SETTINGS] == (-1, 16)


def test_folder_create_rename_delete_lifecycle():
    api = build_api(mock=True)
    api.get_state()
    st = api.folder_create()
    assert st["folderNames"][1] == "New folder"
    assert st["folderPos"][1] == MOCK_CART_POS + 1  # depois de tudo no home
    st = api.folder_rename(1, "Games")
    assert st["folderNames"][1] == "Games"
    with pytest.raises(ValueError):
        api.folder_rename(1, "X" * 17)
    with pytest.raises(ValueError):
        api.folder_rename(1, "")
    st = api.folder_delete(1)
    assert 1 not in st["folderNames"]
    api.undo()  # volta o delete
    assert api.get_state()["folderNames"][1] == "Games"


def test_write_mirrors_folder_baptism_number_and_counter():
    # gate 0B: create escreve nº de batismo no SaveData e incrementa o contador
    # do Launcher; delete deixa ambos orfaos (igual ao console)
    api = build_api(mock=True)
    api.get_state()
    api.folder_create()  # fid 1 (mock ja tem fid 0; contador mock = 2)
    api.write_sd()
    sd_out = (api.workdir / "extract" / "user" / "SaveData.dat").read_bytes()
    assert struct.unpack_from("<I", sd_out, OFF_FOLDER_NUM + 1 * 4)[0] == 2
    sd3 = Path(api.sd_root) / "3DSort"
    payload = sd3 / "homemenu_save_new.bin"
    assert Launcher(payload.read_bytes()).next_folder_number == 3
    # fecha o ciclo de inject e apaga a pasta: campos ficam orfaos
    (sd3 / "inject_done.sha").write_bytes(hashlib.sha256(payload.read_bytes()).digest())
    api.verify_inject()
    # re-dump simulado: escrita de launcher exige ancora fresca pos-promote
    (sd3 / "homemenu_save.bin.sha").write_bytes(
        hashlib.sha256((sd3 / "homemenu_save.bin").read_bytes()).digest())
    api.folder_delete(1)
    api.write_sd()
    sd_out = (api.workdir / "extract" / "user" / "SaveData.dat").read_bytes()
    assert struct.unpack_from("<I", sd_out, OFF_FOLDER_NUM + 1 * 4)[0] == 2
    assert Launcher(payload.read_bytes()).next_folder_number == 3


def test_status0_game_visible_and_position_protected():
    # gate 0C (console real): jogo nunca aberto tem status 0, o console exibe.
    # Regressao da colisao: folder_create deve cair DEPOIS dele, nao em cima.
    from core.savedata import OFF_FOLDER, OFF_POS, OFF_STATUS, OFF_TID
    api = build_api(mock=True)
    sav = api.save3ds.plain / "user" / "SaveData.dat"
    buf = bytearray(sav.read_bytes())
    struct.pack_into("<Q", buf, OFF_TID + 30 * 8, 0x00040000DEAD0000)
    struct.pack_into("<b", buf, OFF_STATUS + 30, 0)
    struct.pack_into("<h", buf, OFF_POS + 30 * 2, MOCK_CART_POS + 1)
    struct.pack_into("<b", buf, OFF_FOLDER + 30, -1)
    sav.write_bytes(bytes(buf))
    st = api.import_sd()
    it = next(i for i in st["items"] if i["slot"] == 30)
    assert it["pos"] == MOCK_CART_POS + 1
    st = api.folder_create()
    assert st["folderPos"][1] == MOCK_CART_POS + 2


def test_folder_delete_returns_members_home():
    api = build_api(mock=True)
    st = api.get_state()
    game = st["items"][0]["slot"]
    api.set_folder(game, 0)
    st = api.folder_delete(0)
    assert st["folderNames"] == {}
    got = positions(st)
    # jogo membro volta para o fim dos jogos; H&S (NAND) depois de todos
    assert got[f"g:{game}"][0] == -1
    assert got[H_AND_S] == (-1, 16)
    # jogos compactam na pos 9 liberada pelo tile da pasta
    game_pos = sorted(p for k, (f, p) in got.items() if k.startswith("g:"))
    assert game_pos == [3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15]


def test_folder_empty_keeps_folder():
    api = build_api(mock=True)
    api.get_state()
    st = api.folder_empty(0)
    assert st["folderNames"] == {0: "Homebrew"}
    assert positions(st)[H_AND_S][0] == -1


def test_launcher_write_requires_fresh_dump_after_promote():
    # 0C (console real): qualquer boot do HOME drifta bytes volateis da NAND,
    # entao a copia promovida pos-inject NAO e ancora valida. Escrita de
    # launcher exige .sha de dump fresco ao lado do container.
    api = build_api(mock=True)
    api.get_state()
    api.swap_items(SETTINGS, FOLDER)
    api.write_sd()
    sd3 = Path(api.sd_root) / "3DSort"
    payload = sd3 / "homemenu_save_new.bin"
    (sd3 / "inject_done.sha").write_bytes(hashlib.sha256(payload.read_bytes()).digest())
    api.verify_inject()
    # promote descarta as ancoras de proposito
    assert not (sd3 / "homemenu_save.bin.sha").exists()
    assert not (sd3 / "homemenu_save_new.bin.sha").exists()
    api.swap_items(SETTINGS, FOLDER)
    st = api.write_sd()
    assert "3DSort_dump" in st["error"]
    # re-dump simulado (o cp --hash do GM9 regenera o par bin+sha)
    (sd3 / "homemenu_save.bin.sha").write_bytes(
        hashlib.sha256((sd3 / "homemenu_save.bin").read_bytes()).digest())
    st = api.write_sd()
    assert "error" not in st and st["pendingInject"] is not None


def test_write_keeps_theme_changed_on_console_after_import():
    # usuario troca o tema NO CONSOLE depois do import: o write nao pode
    # regredir (enxerto da regiao 0x13B8+ a partir do cartao no momento do write)
    api = build_api(mock=True)
    st = api.get_state()
    sav = api.save3ds.plain / "user" / "SaveData.dat"
    buf = bytearray(sav.read_bytes())
    buf[0x13B8] = 0x42  # "tema" novo gravado pelo console apos o import
    sav.write_bytes(bytes(buf))
    api.swap_items(st["items"][0]["slot"], st["items"][1]["slot"])
    api.write_sd()
    out = (api.workdir / "extract" / "user" / "SaveData.dat").read_bytes()
    assert out[0x13B8] == 0x42


def test_every_write_unwraps_all_icons():
    # mecanismo do Cthulhu, sempre ligado: todo write zera o array de status
    # (0 = desembrulhado sempre; o console re-marca "novo" sozinho se quiser)
    from core.savedata import OFF_STATUS
    api = build_api(mock=True)
    st = api.get_state()
    api.swap_items(st["items"][0]["slot"], st["items"][1]["slot"])
    api.write_sd()
    sav = (api.workdir / "extract" / "user" / "SaveData.dat").read_bytes()
    assert sav[OFF_STATUS:OFF_STATUS + 360] == b"\x00" * 360


def test_gap_is_free_when_launcher_present_and_reserved_without():
    # 0C: com launcher todo dono e conhecido (tid+pos no SD; NAND/pastas/cart no
    # Launcher) — buraco e vaga livre real, nao reserva eterna. Sem launcher a
    # reserva continua (donos invisiveis sao possiveis).
    from core.savedata import OFF_FOLDER, OFF_POS, OFF_TID

    def craft_gap(api):  # jogo em MOCK_CART_POS+2 deixa buraco em +1
        sav = api.save3ds.plain / "user" / "SaveData.dat"
        buf = bytearray(sav.read_bytes())
        struct.pack_into("<Q", buf, OFF_TID + 30 * 8, 0x00040000DEAD0000)
        struct.pack_into("<h", buf, OFF_POS + 30 * 2, MOCK_CART_POS + 2)
        struct.pack_into("<b", buf, OFF_FOLDER + 30, -1)
        sav.write_bytes(bytes(buf))

    api = build_api(mock=True)
    craft_gap(api)
    st = api.import_sd()
    assert not any(s.get("hole") for s in st["system"])
    a, b = st["items"][0]["slot"], st["items"][1]["slot"]
    st = api.swap_items(a, b)  # qualquer mutacao redistribui posicoes
    poss = sorted(p for k, (f, p) in positions(st).items() if k.startswith("g:"))
    assert MOCK_CART_POS + 1 in poss and MOCK_CART_POS + 2 not in poss

    api2 = build_api(mock=True, no_launcher=True)
    craft_gap(api2)
    st = api2.import_sd()
    assert MOCK_CART_POS + 1 in [s["pos"] for s in st["system"]]  # placeholder


def test_restore_backup_ensures_boss_dir():
    # cinto para backups legados (zip sem entries de diretorio): extdata
    # importado sem boss/ faz o HOME reconstruir o SaveData inteiro (Fase 0C)
    api = build_api(mock=True)
    st = api.get_state()
    a, b = st["items"][0]["slot"], st["items"][1]["slot"]
    api.swap_items(a, b)
    api.write_sd()  # backup auto vem do mock, que nao tem boss/
    bid = api.backups.history()[-1]["id"]
    api.restore_backup(bid)
    assert (api.workdir / "extract" / "boss").is_dir()


def test_write_sd_only_leaves_no_pending_inject():
    api = build_api(mock=True)
    st = api.get_state()
    a, b = st["items"][0]["slot"], st["items"][1]["slot"]
    api.swap_items(a, b)
    st = api.write_sd()
    assert st["pendingInject"] is None
    assert st["staged"] == []


def test_write_launcher_dirty_publishes_payload_and_verifies():
    api = build_api(mock=True)
    before = positions(api.get_state())
    api.swap_items(SETTINGS, FOLDER)
    st = api.write_sd()
    assert st["pendingInject"] is not None
    sd3 = Path(api.sd_root) / "3DSort"
    payload = sd3 / "homemenu_save_new.bin"
    assert payload.exists() and (sd3 / "homemenu_save_new.bin.sha").exists()
    scripts = Path(api.sd_root) / "gm9" / "scripts"
    assert (scripts / "3DSort_dump.gm9").exists()
    inject = (scripts / "3DSort_inject.gm9").read_text(encoding="ascii")
    assert "fixcmac" in inject and "allow" in inject and "inject_done.sha" in inject
    # sem recibo, verify falha
    assert "error" in api.verify_inject()
    # recibo do GM9 = sha do payload; ai verify promove e limpa o pendente
    (sd3 / "inject_done.sha").write_bytes(hashlib.sha256(payload.read_bytes()).digest())
    st = api.verify_inject()
    assert st["pendingInject"] is None
    got = positions(st)
    assert got[SETTINGS] == before[FOLDER]
    assert got[FOLDER] == before[SETTINGS]
    assert (sd3 / "homemenu_save.bin").exists() and not payload.exists()


def test_stale_container_blocks_launcher_write():
    api = build_api(mock=True)
    api.get_state()
    api.swap_items(SETTINGS, FOLDER)
    raw = bytearray(Path(api.container_path).read_bytes())
    raw[-1] ^= 0xFF  # container mudou no disco depois do parse
    Path(api.container_path).write_bytes(bytes(raw))
    r = api.write_sd()
    assert "error" in r and "Re-dump" in r["error"]
    assert api.get_state()["staged"]  # staging preservado para retry


def test_freed_position_is_reusable_after_write():
    """Jogo movido para pasta libera uma posicao: com launcher presente ela e
    vaga livre REAL (sem placeholder 'Empty slot') e volta a ser usada (0C)."""
    api = build_api(mock=True)
    st = api.get_state()
    game = st["items"][-1]["slot"]  # ultimo jogo do home (pos 16)
    api.set_folder(game, 0)
    api.write_sd()
    st = api.import_sd()
    assert not any(s.get("hole") for s in st["system"])
    assert 16 not in {i["pos"] for i in st["items"]}
    # a vaga liberada volta ao conjunto usado quando o jogo retorna ao home
    st = api.set_folder(game, -1)
    poss = sorted(p for k, (f, p) in positions(st).items()
                  if k.startswith("g:") and f == -1)
    assert 16 in poss and max(poss) == 16


def test_backup_includes_launcher_and_restore_stages_it():
    api = build_api(mock=True)
    before = positions(api.get_state())
    api.swap_items(SETTINGS, FOLDER)
    st = api.write_sd()  # backup auto guarda o launcher PRE-escrita
    bid = st["history"][0]["id"]
    st = api.restore_backup(bid)
    assert st["staged"][-1].startswith("Restored backup")
    assert st["launcherDirty"] is True  # restaurar o layout antigo exige novo write
    assert positions(st) == before