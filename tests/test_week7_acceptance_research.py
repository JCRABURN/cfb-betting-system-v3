"""Independent acceptance checks; original graders/cards remain untouched."""
import copy
import hashlib
import json
from dataclasses import replace

import pytest

from scripts import build_week7_postgame_audit as original
from scripts import research_week7_acceptance as research


def test_all_118_week7_selections_independently_regrade_from_pregame_lines():
    rows=research.load_modern(7)
    assert len(rows)==118
    for market,wins in [('ATS',26),('TOTAL',33)]:
        pool=[r for r in rows if r.market==market]
        assert len({r.game_id for r in pool})==59
        assert sum(r.result=='WIN' for r in pool)==wins
    under=next(r for r in rows if r.market=='TOTAL' and r.game_id=='401860923')
    assert (under.line,under.actual,under.cover,under.result)==(69.5,93,-23.5,'LOSS')


def test_owner_approved_five_reconcile_exact_ids_markets_lines_and_scores():
    rows={(r.market,r.game_id):r for r in research.load_modern(7)}
    approval=research.read(original.APPROVAL)
    expected=[('Air Force',1.5,11.5,'WIN'),('Indiana',3.5,-.5,'LOSS'),
              ('Georgia State',12.5,-14.5,'LOSS'),('Nebraska',7.5,4.5,'WIN'),('under',69.5,-23.5,'LOSS')]
    actual=[]
    for item in approval['selections']:
        r=rows[item['market'],str(item['game_id'])]
        assert item['correct_splashsports_locked_line']==r.line
        assert item['within_market_research_rank']==r.rank
        assert item['research_score_not_calibrated']==pytest.approx(r.score)
        actual.append((r.selection,r.line,r.cover,r.result))
    assert actual==expected


def test_every_rank_belongs_to_exactly_one_nonoverlapping_segment():
    for week,size in [(5,56),(6,58),(7,59)]:
        for market in ('ATS','TOTAL'):
            rows=[r for r in research.load_modern(week) if r.market==market]
            sets=[{r.game_id for r in rows if research.segment(r.rank)==band} for band in ('1-5','6-10','11+')]
            assert [len(s) for s in sets]==[5,5,size-10]
            assert not (sets[0]&sets[1] or sets[0]&sets[2] or sets[1]&sets[2])
            assert len(set.union(*sets))==size


def test_missing_duplicate_and_contaminated_inputs_fail(monkeypatch):
    original_read=research.read
    def altered(path):
        rows=original_read(path)
        if str(path).endswith('cfbd-week7-games.derived.json'):
            rows[0]['completed']=True
        return rows
    monkeypatch.setattr(research,'read',altered)
    with pytest.raises(ValueError,match='outcome'):research.load_modern(7)
    with pytest.raises(ValueError,match='duplicate'):research.unique([{'game_id':1},{'game_id':1}])


def test_push_unit_returns_and_error_sign_are_explicit():
    row=research.load_modern(7)[0]
    rows=[replace(row,result='WIN',actual=12,projection=10),replace(row,result='LOSS',actual=8,projection=10),replace(row,result='PUSH',actual=10,projection=10)]
    m=research.metrics(rows)
    assert m['hit_rate']==.5 and m['pushes']==1
    assert m['units_minus110']==pytest.approx(-1/11)
    assert m['roi']==pytest.approx(-1/33)
    assert m['bias_actual_minus_prediction']==0
    assert research.metrics([])['hit_rate'] is None
    assert research.metrics([rows[2]])['hit_rate'] is None
    assert research.auc([1,1],[True,False])==.5
    assert research.pearson([1,1],[0,1]) is None


def test_eol_diagnosis_does_not_accept_real_content_changes():
    digest=hashlib.sha256(b'a\r\nb\r\n').hexdigest()
    assert research.eol_identity(b'a\nb\n',digest)=='CRLF_VARIANT_ONLY'
    assert research.eol_identity(b'a\r\nb\r\n',digest)=='EXACT'
    assert research.eol_identity(b'a\nc\n',digest)=='CONTENT_MISMATCH'


def test_week5_eol_issue_is_isolated_from_week6_and_week7_exact_custody():
    checks=research.custody()['checks']
    assert len(checks)==419
    assert all(r['status']=='EXACT' for r in checks if not r['group'].startswith('week5'))
    assert all(r['status']!='CONTENT_MISMATCH' for r in checks)


def test_week7_raw_components_are_pregame_and_reproduce_all_projections():
    d=research.read(original.FROZEN/'week7_raw_model_components.json')
    fitted=d['totals_model']['fitted']
    assert len(d['games'])==59
    for game in d['games']:
        for side in ('home','away'):
            stats=game['raw_point_in_time_package'][f'{side}_stats']
            assert (stats['as_of_season'],stats['as_of_week'])<=(2026,6)
            total=sum(a*b for a,b in zip(fitted[f'{side}_coefficients'],game['totals']['features']))+fitted[f'{side}_intercept']
            assert total==pytest.approx(game['totals'][f'projected_{side}_points'])
        ats=game['ats']
        assert ats['intercept']+ats['coefficients'][0]*ats['epa_differential']==pytest.approx(ats['projected_home_margin'])
        assert research.instant(game['totals']['prediction_generated_at'])<research.instant(game['kickoff_utc'])


def test_original_verifier_defect_is_reproduced_without_editing_any_evidence(monkeypatch):
    """PR38 verifier ignores declared status and accepts empty checksum maps."""
    read=original.read_json
    def mutated(path):
        value=read(path)
        if path.name=='week7_postgame_manifest.json':
            value=copy.deepcopy(value)
            value.update(output_sha256={},audit_code_sha256={},formal_audit_status='COMPLETE',qualified_clv_rows=118)
        return value
    monkeypatch.setattr(original,'read_json',mutated)
    assert original.main(verify=True)['formal_audit_status']=='INCOMPLETE_CLV_CUSTODY'
    manifest=mutated(original.OUTPUT/'week7_postgame_manifest.json')
    with pytest.raises(ValueError,match='coverage'):research.validate_manifest(manifest,{'a'},{'b'})


def test_independent_manifest_gate_requires_exact_coverage_and_incomplete_clv():
    m=research.read(original.OUTPUT/'week7_postgame_manifest.json')
    outputs={p.relative_to(original.OUTPUT).as_posix() for p in original.OUTPUT.rglob('*') if p.is_file() and p.name!='week7_postgame_manifest.json'}
    code={'scripts/build_week7_postgame_audit.py','scripts/capture_week7_postgame_evidence.py','scripts/week5_postgame_core.py'}
    research.validate_manifest(m,outputs,code)
    assert len(outputs)==69
    bad=copy.deepcopy(m);bad['qualified_clv_rows']=1
    with pytest.raises(ValueError,match='status'):research.validate_manifest(bad,outputs,code)
    bad=copy.deepcopy(m);bad['output_sha256'].pop(next(iter(bad['output_sha256'])))
    with pytest.raises(ValueError,match='coverage'):research.validate_manifest(bad,outputs,code)


def test_week6_writer_rejects_overwrite_in_disposable_directory(tmp_path,monkeypatch):
    from scripts import build_week6_postgame_audit as week6
    monkeypatch.setattr(week6,'OUTPUT',tmp_path)
    (tmp_path/'existing.csv').write_text('sealed original\n')
    with pytest.raises(FileExistsError):
        week6.write_csv('existing.csv',[{'result':'replacement'}])
    assert (tmp_path/'existing.csv').read_text() == 'sealed original\n'


def test_archived_diagnostic_totals_and_no_clv_promotion():
    d=research.read(research.OUT/'diagnostics.json')
    assert d['status']=='RESEARCH_ONLY_NO_POLICY_CHANGE' and d['clv_status']=='INCOMPLETE'
    assert d['comparable_week5_7']['ATS']['n']==173
    assert d['comparable_week5_7']['ATS']['units_minus110']==-5
    assert d['comparable_week5_7']['TOTAL']['units_minus110']==pytest.approx(-34/11)
    assert [(r['week'],r['n']) for r in d['weekly'] if r['market']=='TOTAL']==[(2,49),(3,56),(5,56),(6,58),(7,59)]
