"""Group edits are atomic and preserve the existing save/write invariants."""
import copy
import pytest
from app import build_api
from core import layout


@pytest.fixture
def api():
    instance = build_api(mock=True, mock_badges=True)
    instance.get_state()
    return instance


def home_games(api):
    return sorted((i for i in api.get_state()['items'] if i['folder'] == -1), key=lambda i: i['pos'])


def test_group_free_cells_undo_redo_write_roundtrip(api):
    games = home_games(api)[:3]
    keys = [i['key'] for i in games]
    before = copy.deepcopy(api.staging.state)
    api.place_badge(0, -1, 81)
    before = copy.deepcopy(api.staging.state)
    count = len(api.staging.staged)
    result = api.move_games(list(reversed(keys)), -1, 80)
    assert [i['pos'] for i in sorted((i for i in result['items'] if i['key'] in keys), key=lambda i: keys.index(i['key']))] == [80, 82, 83]
    changed = copy.deepcopy(api.staging.state)
    assert len(api.staging.staged) == count + 1
    api.undo()
    assert api.staging.state == before
    api.redo()
    assert api.staging.state == changed
    assert 'error' not in api.write_sd()
    api.import_sd()
    assert layout.entities(api.staging.state) == layout.entities(changed)


@pytest.mark.parametrize('indices,target', [([0, 1], 5), ([4, 5], 0), ([0, 3], 2)])
def test_insert_preserves_cells_other_entities_and_order(api, indices, target):
    games = home_games(api)
    selected = [games[i]['key'] for i in indices]
    before = layout.entities(api.staging.state)
    movable = sorted((k for k in before if k[0] in ('g', 'n') and before[k][0] == -1), key=lambda k: before[k][1])
    parsed = [api._key(k) for k in selected]
    expected = [k for k in movable if k not in parsed]
    index = expected.index(api._key(games[target]['key']))
    expected[index:index] = parsed
    api.move_games(selected, -1, before_key=games[target]['key'])
    after = layout.entities(api.staging.state)
    assert sorted(movable, key=lambda k: after[k][1]) == expected
    assert sorted(before[k][1] for k in movable) == sorted(after[k][1] for k in movable)
    assert {k: v for k, v in before.items() if k not in movable} == {k: v for k, v in after.items() if k not in movable}
    layout.validate(api.staging.state)


def test_folders_and_back(api):
    keys = [i['key'] for i in home_games(api)[:3]]
    api.move_games(keys, 0)
    assert all(i['folder'] == 0 for i in api.get_state()['items'] if i['key'] in keys)
    api.move_games(keys, -1)
    assert all(i['folder'] == -1 for i in api.get_state()['items'] if i['key'] in keys)
    layout.validate(api.staging.state)


@pytest.mark.parametrize('keys,folder,pos,before_key', [
    (['g:0', 'g:1'], -1, 359, None), (['g:0', 'g:0'], -1, 80, None),
    (['g:0', 'g:999'], -1, 80, None), (['g:0', 'cart'], -1, 80, None),
    (['g:0', 'g:1'], 59, 0, None), ([], -1, 0, None),
    (['g:0', 'g:1'], -1, True, None), (['g:0', 'g:1'], -1, 0, 'f:0')])
def test_rejections_are_atomic(api, keys, folder, pos, before_key):
    before = copy.deepcopy(api.staging.state)
    with pytest.raises(ValueError):
        api.move_games(keys, folder, pos, before_key)
    assert api.staging.state == before
    assert not api.staging.staged


def test_missing_launcher_allows_only_occupied_game_reorder():
    api = build_api(mock=True, no_launcher=True)
    api.get_state()
    games = home_games(api)
    keys = [i['key'] for i in games[:2]]
    api.move_games(keys, -1, before_key=games[4]['key'])
    with pytest.raises(ValueError, match='HOME menu dump'):
        api.move_games(keys, -1, 80)
