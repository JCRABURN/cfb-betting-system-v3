"""Adversarial checks of the separate, non-authorized human review artifact."""
import copy
import gzip
import hashlib
import json
import pytest
from scripts import verify_week10_owner_review as review
from scripts.build_week10_owner_review import write_new, build


PATH = review.REVIEWS/'20261105-afternoon-decision/owner-review.json'


@pytest.fixture
def document():
    return json.loads(PATH.read_text(encoding='utf-8'))


def test_archived_review_read_only(document):
    before = review.sha(PATH)
    result = review.validate(document, check_board=False)
    assert result['verified_candidates'] == 10
    assert result['recommended_five'] == 5
    assert review.sha(PATH) == before


@pytest.mark.parametrize('field,value', [
    ('locked_line',3.5), ('frozen_projection_home_margin_or_total',999),
    ('frozen_confidence',5), ('original_market_research_rank',99),
    ('research_score_not_calibrated',.99), ('frozen_uncertainty_points',1),
    ('selected_forecast_edge',99), ('selection','Texas'), ('home','Texas'),
    ('numeric_projection_adjustment',1), ('owner_approval','APPROVED'),
    ('human_review_confidence_1_to_5',True), ('human_review_confidence_1_to_5',6),
    ('human_review_confidence_1_to_5',0), ('owner_review_rank',2),
    ('recommended_five',False), ('locked_line',float('nan')),
    ('sources',[]), ('rationale',''),
])
def test_reject_altered_frozen_or_governance_fields(document, field, value):
    document['selections'][0][field] = value
    with pytest.raises(ValueError):
        review.validate(document, check_board=False)


@pytest.mark.parametrize('field,value', [
    ('owner_approval','APPROVED'), ('model_policy_changed',True),
    ('sealed_board_sha256','0'*64), ('evidence_inventory_sha256','0'*64),
    ('human_brief_sha256','0'*64),
])
def test_reject_top_level_contradictions(document, field, value):
    document[field] = value
    with pytest.raises(ValueError):
        review.validate(document, check_board=False)


def test_reject_missing_candidate(document):
    document['selections'].pop()
    with pytest.raises(ValueError,match='coverage'):
        review.validate(document, check_board=False)


def test_reject_duplicate_candidate(document):
    document['selections'][-1]=copy.deepcopy(document['selections'][0])
    with pytest.raises(ValueError,match='coverage'):
        review.validate(document, check_board=False)


def test_reject_future_source_publication(document):
    document['selections'][0]['sources'][0]['published_at_utc']='2027-01-01T00:00:00Z'
    with pytest.raises(ValueError,match='publication'):
        review.validate(document, check_board=False)


def test_reject_later_evidence_for_earlier_decision(document):
    document['selections'][0]['created_at_utc']='2026-11-05T01:00:00Z'
    with pytest.raises(ValueError,match='source after'):
        review.validate(document, check_board=False)


def test_reject_retrospective_initial_review(document):
    document['created_at_utc']='2026-11-06T02:00:00Z'
    with pytest.raises(ValueError,match='started row'):
        review.validate(document, check_board=False)


def test_started_rows_can_only_be_carried_forward_exactly(document):
    document['created_at_utc']='2026-11-06T02:00:00Z'
    document['previous_review_path']=PATH.relative_to(review.ROOT).as_posix()
    document['previous_review_sha256']=review.sha(PATH)
    assert review.validate(document,check_board=False)['recommended_five']==5
    document['selections'][3]['human_review_confidence_1_to_5']=1
    with pytest.raises(ValueError,match='started row'):
        review.validate(document,check_board=False)


def test_started_rank_and_membership_cannot_change(document):
    document['created_at_utc']='2026-11-06T02:00:00Z'
    document['previous_review_path']=PATH.relative_to(review.ROOT).as_posix()
    document['previous_review_sha256']=review.sha(PATH)
    rows=document['selections'];rows[3],rows[8]=rows[8],rows[3]
    for rank,row in enumerate(rows,1):
        row['owner_review_rank']=rank;row['recommended_five']=rank<=5
    with pytest.raises(ValueError,match='started row'):
        review.validate(document,check_board=False)


def test_no_timezone_is_rejected():
    with pytest.raises(ValueError,match='timezone'):
        review.instant('2026-11-05T01:00:00')


def test_writer_will_not_replace_existing_bytes(tmp_path):
    path=tmp_path/'review.json';path.write_bytes(b'original')
    with pytest.raises(FileExistsError):
        write_new(path,{'replace':True})
    assert path.read_bytes()==b'original'


def test_builder_will_not_replace_existing_version():
    with pytest.raises(ValueError,match='new owner review'):
        build(review.ROOT/'docs/week10-human-context-20261105.json',PATH.parent)


def test_missing_checksum_entry_rejected(document, tmp_path, monkeypatch):
    inventory_path=review.ROOT/document['evidence_inventory_path']
    inventory=json.loads(inventory_path.read_text())
    inventory['sha256'].pop(next(iter(inventory['sha256'])))
    replacement=tmp_path/'inventory.json';write_new(replacement,inventory)
    document['evidence_inventory_sha256']=review.sha(replacement)
    original_confined=review.confined
    monkeypatch.setattr(review,'confined',lambda name,parent: replacement if name==document['evidence_inventory_path'] else original_confined(name,parent))
    with pytest.raises(ValueError,match='checksum coverage'):
        review.validate(document,check_board=False)


def test_altered_evidence_bytes_rejected(document, monkeypatch):
    original_sha=review.sha
    monkeypatch.setattr(review,'sha',lambda path: '0'*64 if path.name=='derived-team-metrics.json' else original_sha(path))
    with pytest.raises(ValueError,match='evidence bytes'):
        review.validate(document,check_board=False)


def test_metrics_replay_rejects_changed_numerical_output(tmp_path):
    source=next(review.CONTEXT.glob('*/derived-team-metrics.json'))
    data=json.loads(source.read_text());data['rows'][0]['off_ppa']+=.01
    path=tmp_path/'changed.json';write_new(path,data)
    with pytest.raises(ValueError,match='metric replay'):
        review.verify_team_metrics(path)


def test_reading_copy_normalization_preserves_original_bytes():
    record=json.loads((PATH.parent/'reading-copy-normalization.json').read_text())
    assert record['changes']
    for item in record['changes']:
        original=gzip.decompress((review.ROOT/item['original_bytes_archive']).read_bytes())
        assert hashlib.sha256(original).hexdigest()==item['original_sha256']
        normalized=('\n'.join(line.expandtabs(4).rstrip() for line in original.decode('utf-8').splitlines()).rstrip()+'\n').encode('utf-8')
        assert (review.ROOT/item['path']).read_bytes()==normalized
        assert hashlib.sha256(normalized).hexdigest()==item['normalized_sha256']
    previous=json.loads(gzip.decompress((PATH.parent/'owner-review.json.before-reading-copy-normalization.gz').read_bytes()))
    current=json.loads(PATH.read_text())
    assert previous['selections']==current['selections']
    assert previous['created_at_utc']==current['created_at_utc']
