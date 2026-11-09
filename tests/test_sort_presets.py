import copy
import json
import pytest
from app import build_api
from core import titledates, titlenames
from core.sort_presets import Presets
from tools.build_titledates import title_names, write_names


def setup(monkeypatch):
    api = build_api(mock=True)
    api.get_state()
    for i, name in enumerate(("Zulu", "Alpha", "Mike")):
        api._names[api.staging.state["tids"][i]] = name
    tids = api.staging.state["tids"]
    monkeypatch.setattr(titledates, "_table", {f"{tids[i]:016x}": date for i, date in enumerate(("2020-01-01", "2020-01-01", "2000-01-01"))})
    monkeypatch.setattr(titlenames, "_table", {f"{tids[0]:016x}": "A commercial name", f"{tids[1]:016x}": "Z commercial name"})
    return api


def save(api, criteria, name="Example"):
    return api.save_sort_preset({"name": name, "criteria": [{"field": f, "direction": d} for f,d in criteria]})["presets"][-1]


def order(api, state, folder=-1):
    keys = {"g:0", "g:1", "g:2"}
    return [i["key"] for i in sorted(state["items"], key=lambda i:i["pos"]) if i["key"] in keys and i["folder"] == folder]


@pytest.mark.parametrize("criteria,expected", [
    ([("internal_title", "asc")], [1,2,0]),
    ([("internal_title", "desc")], [0,2,1]),
    ([("official_title", "asc")], [0,2,1]),
    ([("release_date", "asc"),("internal_title", "desc")], [2,0,1]),
    ([("release_date", "desc"),("internal_title", "asc")], [1,0,2]),
])
def test_order(monkeypatch, criteria, expected):
    api = setup(monkeypatch)
    before = copy.deepcopy(api.staging.state)
    p = save(api, criteria)
    assert api.staging.state == before and not api.staging.staged
    state = api.sort_preset(p["id"])
    assert order(api,state) == [f"g:{i}" for i in expected]
    after = copy.deepcopy(api.staging.state)
    api.undo(); assert api.staging.state == before
    api.redo(); assert api.staging.state == after
    staged = list(api.staging.staged)
    api.sort_preset(p["id"])
    assert api.staging.state == after and api.staging.staged == staged


@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_missing_dates_and_folder_isolation(monkeypatch, direction):
    api = setup(monkeypatch)
    for i in range(3): api.set_folder(f"g:{i}",0)
    tids=api.staging.state["tids"]
    titledates._table.pop(f"{tids[0]:016x}")
    p=save(api,[("release_date",direction)])
    before=copy.deepcopy(api.staging.state)
    state=api.sort_preset(p["id"],4,0)
    assert order(api,state,0) == (["g:2","g:1","g:0"] if direction == "asc" else ["g:1","g:2","g:0"])
    assert not state["launcherDirty"]
    assert api.staging.state["folders"] == before["folders"]
    assert all(api.staging.state["game_pos"][i] == pos for i,pos in before["game_pos"].items() if before["folders"][i] != 0)


def test_stable_ties_and_fallback(monkeypatch):
    api=setup(monkeypatch)
    titlenames._table={}
    p=save(api,[("official_title","asc")])
    assert order(api,api.sort_preset(p["id"])) == ["g:1","g:2","g:0"]
    for tid in api.staging.state["tids"].values(): api._names[tid]="same"
    before=order(api,api.get_state())
    assert order(api,api.sort_preset(p["id"])) == before


@pytest.mark.parametrize("criteria", [[], [{"field":"bad","direction":"asc"}], [{"field":"internal_title","direction":"wrong"}], [{"field":"release_date","direction":"asc"}]*2])
def test_invalid_presets_do_not_stage(monkeypatch,criteria):
    api=setup(monkeypatch)
    before=copy.deepcopy(api.staging.state)
    with pytest.raises(ValueError): api.save_sort_preset({"name":"bad","criteria":criteria})
    with pytest.raises(ValueError): api.sort_preset("custom:missing")
    assert api.staging.state == before and not api.staging.staged


def test_persistence_and_recovery(tmp_path,monkeypatch):
    api=setup(monkeypatch)
    p=save(api,[("internal_title","asc")])
    path=api._sort_presets.path
    assert Presets(path).custom == [p]
    import subprocess, sys
    result = subprocess.run([sys.executable, "-c", "import json,sys; from core.sort_presets import Presets; print(json.dumps(Presets(sys.argv[1]).custom))", str(path)], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == [p]
    p["name"]="Edited"
    api.save_sort_preset(p)
    assert Presets(path).custom[0]["name"] == "Edited"
    api.delete_sort_preset(p["id"])
    assert Presets(path).custom == []
    path.write_text("broken")
    store=Presets(path)
    assert store.warning and len(store.library()["presets"]) == 4
    store.write([])
    assert next(path.parent.glob("sort-presets.json.recovery-*")).read_text() == "broken"
    monkeypatch.setattr("core.sort_presets.os.replace",lambda *a: (_ for _ in ()).throw(OSError("failed")))
    with pytest.raises(OSError): store.write([p])
    assert store.custom == [] and Presets(path).custom == []


def test_regional_catalog_and_reproducible_generation(tmp_path):
    sources=[[{"TitleID":"0004000000000001","Name":"  Regional   Name "}, {"TitleID":"0004000000000001","Name":"Another Name"}], [{"TitleID":"0004000000000001","Name":"Conflict"},{"TitleID":"0004000000000002","Name":"Other Region"}]]
    table=title_names(sources)
    assert table == {"0004000000000001":"Another Name","0004000000000002":"Other Region"}
    a,b=tmp_path/'a.gz',tmp_path/'b.gz'
    write_names(sources,a); write_names(sources,b)
    assert a.read_bytes() == b.read_bytes()


@pytest.mark.parametrize("data", [[], None, {"version":2,"presets":[]}, {"version":1,"presets":[{}]}, {"version":True,"presets":[]}])
def test_malformed_configuration(tmp_path,data):
    path=tmp_path/"sort-presets.json"
    path.write_text(json.dumps(data))
    store=Presets(path)
    assert store.warning and len(store.library()["presets"]) == 4


def test_builtins_protected(monkeypatch):
    api=setup(monkeypatch)
    for p in api.list_sort_presets()["presets"]:
        with pytest.raises(ValueError): api.save_sort_preset(p)
        with pytest.raises(ValueError): api.delete_sort_preset(p["id"])
    assert not api.staging.staged


@pytest.mark.parametrize("direction",["asc","desc"])
def test_custom_sort_mixed_dsiware(monkeypatch,direction):
    import app
    nand=[n for n in app.MOCK_NAND if n[2] != 8]+[("Castlevania",0x0004800443415341,8,-1)]
    monkeypatch.setattr(app,"MOCK_NAND",nand)
    api=setup(monkeypatch)
    for key in ("g:0","g:1","n:4"): api.set_folder(key,0)
    p=save(api,[("internal_title",direction)])
    state=api.sort_preset(p["id"],4,0)
    members=sorted((i for i in state["items"]+state["system"] if i["folder"]==0),key=lambda i:i["pos"])
    assert [i["name"] for i in members] == ["Health & Safety"] + (["Alpha","Castlevania","Zulu"] if direction=="asc" else ["Zulu","Castlevania","Alpha"])


def test_invalid_scope_preserves_undo(monkeypatch):
    api=setup(monkeypatch)
    p=save(api,[("internal_title","asc")])
    api.sort_preset(p["id"])
    before=copy.deepcopy((api.staging.state,api.staging._undo,api.staging._redo,api.staging.staged))
    for folder in (True,"0",-1,60,59):
        with pytest.raises(ValueError): api.sort_preset(p["id"],4,folder)
    assert (api.staging.state,api.staging._undo,api.staging._redo,api.staging.staged) == before


@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_secondary_key_for_missing_dates(monkeypatch, direction):
    api = setup(monkeypatch)
    titledates._table = {}
    preset = save(api, [("release_date", direction), ("internal_title", "asc")])
    assert order(api, api.sort_preset(preset["id"])) == ["g:1", "g:2", "g:0"]


def test_custom_badges_reserved_cells_and_global_membership(monkeypatch):
    api = build_api(mock=True, mock_badges=True)
    api.get_state()
    api.set_folder("g:0", 0)
    api.place_badge(4, -1, 20, 4)
    api._unknown_holes[-1] = {19}
    membership = copy.deepcopy(api.staging.state["folders"])
    preset = save(api, [("internal_title", "desc")])
    state = api.sort_preset(preset["id"])
    assert api.staging.state["folders"] == membership
    pieces = sorted(b["pos"] for b in state["badges"]["placed"])
    assert pieces == [pieces[0], pieces[0]+1, pieces[0]+4, pieces[0]+5]
    assert 19 not in pieces
    games = sorted((i for i in state["items"] if i["folder"] == -1), key=lambda i:i["pos"])
    assert [i["name"].lower() for i in games] == sorted((i["name"].lower() for i in games), reverse=True)


def test_api_restart_loads_presets(monkeypatch):
    from app import Api
    api = setup(monkeypatch)
    preset = save(api, [("official_title", "desc")])
    restarted = Api(api.save3ds, api.sd_root, api.workdir, api.backups, container=api.container_path)
    assert restarted.list_sort_presets()["presets"][-1] == preset
    restarted.get_state()
    assert order(restarted, restarted.sort_preset(preset["id"])) == ["g:1", "g:2", "g:0"]


def test_official_final_tid_fallback(monkeypatch):
    api = setup(monkeypatch)
    titlenames._table = {}
    for tid in api.staging.state["tids"].values():
        api._names[tid] = ""
    preset = save(api, [("official_title", "asc")])
    result = api.sort_preset(preset["id"])
    games = sorted((i for i in result["items"] if i["folder"] == -1), key=lambda i:i["pos"])
    assert [i["tid"] for i in games] == sorted(i["tid"] for i in games)

@pytest.mark.parametrize('first_direction,second_direction,expected', [
    ('asc', 'asc', [1, 0, 2]),
    ('asc', 'desc', [0, 1, 2]),
    ('desc', 'asc', [2, 1, 0]),
    ('desc', 'desc', [2, 0, 1]),
])
def test_three_key_priority_and_independent_directions(monkeypatch, first_direction, second_direction, expected):
    api = setup(monkeypatch)
    for i in range(3):
        api.set_folder(f'g:{i}', 0)
    tids = api.staging.state['tids']
    monkeypatch.setattr(titlenames, '_table', {f'{tids[i]:016x}': name for i, name in enumerate(('A', 'A', 'B'))})
    monkeypatch.setattr(titledates, '_table', {f'{tids[i]:016x}': '2000-01-01' for i in range(3)})
    preset = save(api, [('official_title', first_direction), ('internal_title', second_direction), ('release_date', 'desc')])
    result = api.sort_preset(preset['id'], 4, 0)
    assert order(api, result, 0) == [f'g:{i}' for i in expected]
    assert not result['launcherDirty']


def test_sort_without_launcher_preserves_reserved_cells(monkeypatch):
    api = build_api(mock=True, no_launcher=True)
    api.get_state()
    before = copy.deepcopy(api.staging.state)
    for i, name in enumerate(('Zulu', 'Alpha', 'Mike')):
        api._names[before['tids'][i]] = name
    result = api.sort_preset('az')
    assert order(api, result) == ['g:1', 'g:2', 'g:0']
    assert sorted(api.staging.state['game_pos'].values()) == sorted(before['game_pos'].values())
    assert not result['launcherDirty']
