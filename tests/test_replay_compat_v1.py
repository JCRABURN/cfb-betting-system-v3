"""Exact replay controls; no tolerated numerical/identity changes."""
import builtins
import copy
import hashlib
from pathlib import Path
import pytest
from scripts import replay_compat_v1 as compat
from scripts import build_week7_postgame_audit as native

@pytest.mark.parametrize('values,expected',[
    ([1e16,1.0,-1e16],1.0),([1e16,-1e16,1.0],1.0),
    ([True,False,True],2),([],0),([1,2,3],6),([.1]*10,1.0),
    ([1e16,1,-1e16],0.0),
])
def test_explicit_sum_is_runtime_independent(values,expected):
    assert compat.compensated_sum(values)==expected
    assert type(compat.compensated_sum(values)) is type(expected)

@pytest.mark.parametrize('values',[[float('nan')],[float('inf')],['1'],[1e308,1e308]])
def test_nonfinite_unsupported_or_overflow_fails_closed(values):
    with pytest.raises(ValueError):compat.compensated_sum(values)

def test_no_process_or_native_module_patch():
    assert 'sum' not in vars(native)
    assert builtins.sum is sum
    assert compat.week7.main.__code__ is native.main.__code__
    assert compat.week7.main.__globals__ is not native.main.__globals__
    compat.verify_legacy_code()

def test_altered_protected_code_rejected(monkeypatch):
    original=Path.read_bytes
    def changed(path):
        raw=original(path)
        return raw+b'\n# altered\n' if path.name=='build_week7_postgame_audit.py' else raw
    monkeypatch.setattr(Path,'read_bytes',changed)
    with pytest.raises(ValueError,match='protected legacy code changed'):compat.verify_legacy_code()

@pytest.fixture(scope='module')
def week7_payload():
    return compat.week7.evaluate()

@pytest.mark.parametrize('field',['raw_projection','locked_line','confidence','research_rank','result'])
def test_substantive_changes_cannot_pass_exact_replay(monkeypatch,field,week7_payload):
    def changed():
        data,tables=copy.deepcopy(week7_payload);r=tables['week7_ats_audit.csv'][0]
        r[field]='LOSS' if field=='result' and r[field]!='LOSS' else 'WIN' if field=='result' else r[field]+1
        return data,tables
    monkeypatch.setattr(compat.week7,'evaluate',changed)
    with pytest.raises(ValueError,match='ledger replay mismatch'):compat.week7.main(True)

@pytest.mark.parametrize('change',[1.0,1e-12])
def test_even_small_unsupported_metric_change_is_rejected(monkeypatch,change,week7_payload):
    def changed():
        data,tables=copy.deepcopy(week7_payload)
        data['diagnostics']['ATS']['projection_metrics']['mae']+=change
        return data,tables
    monkeypatch.setattr(compat.week7,'evaluate',changed)
    with pytest.raises(ValueError,match='diagnostics replay mismatch'):compat.week7.main(True)

def test_cross_week_research_exact_bytes_and_custody():
    assert compat.strict.verify_research()['exact_custody_checks']==419
    assert compat.week8.main(True)['grading_status']=='COMPLETE_52_ATS_52_TOTALS'
    assert compat.week8_research.main(True)['status']=='RESEARCH_ONLY_NOT_DEPLOYED'

def test_new_cli_manifest_expected_inventory_not_derived_from_untrusted_values(monkeypatch):
    original=compat.week8.read_json
    def changed(path):
        value=original(path)
        if path.name=='week8_postgame_manifest.json':
            value=copy.deepcopy(value);value['output_sha256']={};value['clv_status']='COMPLETE'
        return value
    monkeypatch.setattr(compat.week8,'read_json',changed)
    with pytest.raises(ValueError,match='contradiction'):compat.week8.main(True)
