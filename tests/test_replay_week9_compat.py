import copy
import json
from pathlib import Path
import pytest
from scripts import replay_week9_compat as replay
from scripts import review_week9_context as native

FOLDER=replay.ROOT/'outputs/2026-week9-context/20261028T1320Z'

def test_timezone_profile_does_not_use_host_zoneinfo(monkeypatch):
    def forbidden(*args):raise AssertionError('host timezone database consulted')
    monkeypatch.setattr(replay._historical,'ZoneInfo',forbidden)
    data=replay.build(FOLDER)
    assert all(g[s+'_context']['time_zone_shift_hours'] is None for g in data['games'] for s in ['away','home'])
    assert native.timezone_shift is not replay._historical.timezone_shift
    assert replay.main(FOLDER)['model_adjustments']==0

@pytest.mark.parametrize('filename',['capture-manifest.json','derived_context_board.json'])
def test_any_byte_change_rejected_even_if_valid_json(monkeypatch,filename):
    original=Path.read_bytes
    def corrupt(path):
        raw=original(path)
        return raw+b' ' if path==FOLDER/filename else raw
    monkeypatch.setattr(Path,'read_bytes',corrupt)
    with pytest.raises(ValueError,match='exact-byte custody changed'):replay.main(FOLDER)

@pytest.mark.parametrize('kind',['line','forecast_metadata','timezone','status','membership'])
def test_no_substantive_or_provenance_difference_is_tolerated(monkeypatch,kind):
    data=json.loads((FOLDER/'derived_context_board.json').read_bytes())
    if kind=='line':data['games'][0]['locked_total']+=.5
    if kind=='forecast_metadata':data['games'][0]['numerical_adjustments']=[1]
    if kind=='timezone':data['games'][0]['away_context']['time_zone_shift_hours']=0.0
    if kind=='status':data['owner_approval']='APPROVED'
    if kind=='membership':data['games'].pop()
    monkeypatch.setattr(replay._historical,'build',lambda folder:copy.deepcopy(data))
    with pytest.raises(ValueError,match='exact replay mismatch'):replay.main(FOLDER)

def test_missing_capture_checksum_entry_is_not_accepted(monkeypatch):
    original=Path.read_bytes
    def corrupt(path):
        raw=original(path)
        if path==FOLDER/'capture-manifest.json':
            data=json.loads(raw);data['records'].pop();return json.dumps(data).encode()
        return raw
    monkeypatch.setattr(Path,'read_bytes',corrupt)
    with pytest.raises(ValueError,match='custody changed'):replay.main(FOLDER)

def test_unknown_capture_and_writer_rejected():
    with pytest.raises(ValueError,match='unregistered'):replay.build(FOLDER.parent/'unregistered')
    with pytest.raises(ValueError,match='read-only'):replay.main(FOLDER,False)
