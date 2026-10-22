"""Prevent mixing pre-injection NAND positions with post-write SD positions."""
import hashlib
from pathlib import Path
import pytest
from app import Api, build_api


def setup():
    api = build_api(mock=True)
    api.get_state()
    sd3 = Path(api.sd_root) / '3DSort'
    sd3.mkdir(exist_ok=True)
    regional = sd3 / f'homemenu_save_{api._nand_save_id()}.bin'
    regional.write_bytes(Path(api.container_path).read_bytes())
    Path(str(regional) + '.sha').write_bytes(hashlib.sha256(regional.read_bytes()).digest())
    api.import_sd()
    return api, sd3, regional


def positions(state):
    return {i['key']: (i['folder'], i['pos']) for i in state['items'] + state['system'] if i['key']}


def test_injection_survives_import_and_restart_with_regional_dump():
    api, sd3, regional = setup()
    expected = positions(api.swap_items('g:0', 'n:0'))
    assert 'error' not in api.write_sd()
    payload = sd3 / 'homemenu_save_new.bin'
    desired = payload.read_bytes()
    (sd3 / 'inject_done.sha').write_bytes(hashlib.sha256(desired).digest())
    assert positions(api.verify_inject()) == expected
    assert regional.read_bytes() == desired
    assert not Path(str(regional) + '.sha').exists()
    assert not (sd3 / 'homemenu_save.bin.sha').exists()
    for _ in range(2):
        result = api.import_sd()
        assert positions(result) == expected
        assert not result['layoutErrors']
    restarted = Api(api.save3ds, api.sd_root, api.workdir, api.backups)
    assert positions(restarted.get_state()) == expected
    restarted.swap_items('g:0', 'n:0')
    assert '3DSort_dump' in restarted.write_sd()['error']
    # Fresh dump with identical bytes must restore the missing canonical SHA.
    Path(str(regional) + '.sha').write_bytes(hashlib.sha256(desired).digest())
    restarted.import_sd()
    assert (sd3 / 'homemenu_save.bin.sha').read_bytes() == hashlib.sha256(desired).digest()
    restarted.swap_items('g:0', 'n:0')
    assert 'error' not in restarted.write_sd()


def test_pending_import_does_not_overwrite_anchor():
    api, sd3, regional = setup()
    api.swap_items('g:0', 'n:0')
    api.write_sd()
    original = (sd3 / 'homemenu_save.bin').read_bytes()
    regional.write_bytes(b'changed dump')
    assert api._find_container().name == 'homemenu_save_new.bin'
    assert (sd3 / 'homemenu_save.bin').read_bytes() == original
    (sd3 / 'homemenu_save_new.bin').unlink()
    with pytest.raises(ValueError, match='payload is missing'):
        api._find_container()


def test_missing_regional_sha_clears_canonical_anchor():
    api, sd3, regional = setup()
    Path(str(regional) + '.sha').unlink()
    api._find_container()
    assert not (sd3 / 'homemenu_save.bin.sha').exists()


def test_payload_must_match_receipt_before_promotion():
    api, sd3, regional = setup()
    original = regional.read_bytes()
    api.swap_items('g:0', 'n:0')
    api.write_sd()
    payload = sd3 / 'homemenu_save_new.bin'
    (sd3 / 'inject_done.sha').write_bytes(hashlib.sha256(payload.read_bytes()).digest())
    payload.write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='payload changed'):
        api.verify_inject()
    assert regional.read_bytes() == original
    assert api._pending_path().exists()


def test_previous_card_path_is_not_a_fallback(tmp_path):
    api, _, _ = setup()
    api._fallback_container = None
    old = api.container_path
    api.sd_root = tmp_path
    assert old.exists()
    assert api._find_container() is None


def test_new_console_dump_after_injection_is_not_replaced():
    api, sd3, regional = setup()
    api.swap_items('g:0', 'n:0')
    api.write_sd()
    payload = sd3 / 'homemenu_save_new.bin'
    (sd3 / 'inject_done.sha').write_bytes(hashlib.sha256(payload.read_bytes()).digest())
    # A subsequent console dump includes changed volatile bytes.
    from core.launcher import Launcher
    fresh = Launcher(payload.read_bytes())
    fresh.set_cart_pos(70)
    regional.write_bytes(fresh.serialize())
    Path(str(regional) + '.sha').write_bytes(hashlib.sha256(regional.read_bytes()).digest())
    result = api.verify_inject()
    assert next(i for i in result['system'] if i['key'] == 'cart')['pos'] == 70
    assert regional.read_bytes() == fresh.serialize()
