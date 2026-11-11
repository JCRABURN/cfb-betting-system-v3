import json
import shutil
from datetime import datetime, timezone

import pytest

from scripts import prepare_week11_source as source
from scripts import run_week11_execution as execution
from scripts import finalize_week11_card as finalizer


def test_recovered_image_custody_and_all_67_independent_rows():
    assert source.readiness.digest((source.EVIDENCE / 'screenshot-custody.json').read_bytes()) == '353b8b74ba54b8956a02ff5f9b27d0245f77c1584e15d5c216b36a25e6d0aa76'
    verified = source.verify_images()
    assert verified['images'] == 8
    assert verified['independently_verified_line_pairs'] == 67
    assert verified['discrepancy_count'] == 0
    assert verified['custody']['chat_received_at_utc'] == '2026-11-10T22:25:54.183000+00:00'


@pytest.mark.parametrize('mutation', ['image', 'missing', 'extra', 'duplicate_number', 'line',
                                   'rehash_bad_line', 'orientation', 'clock', 'receipt', 'approval'])
def test_image_and_visual_custody_rejects_adversarial_mutations(tmp_path, mutation):
    folder = tmp_path / 'evidence'
    shutil.copytree(source.EVIDENCE, folder)
    path = folder / 'screenshot-custody.json'
    custody = json.loads(path.read_bytes())
    if mutation == 'image':
        (folder / 'splashsports-01.png').write_bytes(b'not the original')
    elif mutation == 'missing':
        custody['images'].pop()
    elif mutation == 'extra':
        (folder / 'unknown.txt').write_text('extra')
    elif mutation == 'duplicate_number':
        custody['images'][1]['screenshot_number'] = 1
    elif mutation in ('line', 'rehash_bad_line', 'orientation', 'clock'):
        review = folder / 'independent-visual-transcription.csv'
        raw = review.read_bytes()
        if mutation in ('line', 'rehash_bad_line'):
            raw = raw.replace(b'+5.5,44.5', b'+5.5,99.5', 1)
        elif mutation == 'orientation':
            raw = raw.replace(b'Kent State,Bowling Green', b'Bowling Green,Kent State', 1)
        else:
            raw = raw.replace(b'Tue,6:00pm', b'Tue,7:00pm', 1)
        review.write_bytes(raw)
        if mutation != 'line':
            custody['independent_review_sha256'] = source.readiness.digest(raw)
    elif mutation == 'receipt':
        custody['chat_received_at_utc'] = '2026-11-09T00:00:00Z'
    elif mutation == 'approval':
        custody['owner_selection_approval'] = 'APPROVED'
    path.write_bytes(source.readiness.serialized(custody))
    with pytest.raises(ValueError):
        source.verify_images(folder)


def test_source_subset_never_overwrites_existing_evidence(tmp_path, monkeypatch):
    p = tmp_path / 'existing.csv'; p.write_bytes(b'keep me')
    monkeypatch.setattr(source, 'SOURCE', p)
    with pytest.raises(FileExistsError):
        source.prepare(tmp_path)
    assert p.read_bytes() == b'keep me'


def test_source_database_cannot_be_execution_target():
    with pytest.raises(ValueError, match='disposable'):
        execution.run(execution.SOURCE_DB)


def test_missing_totals_or_ats_cannot_be_silently_skipped():
    with pytest.raises(ValueError):
        finalizer.require_complete_market_coverage(64, 64, 63, 64, [])
    with pytest.raises(ValueError):
        finalizer.require_complete_market_coverage(64, 64, 64, 63, [(1, 'missing_feature')])


def test_partial_finalization_outputs_are_never_overwritten(tmp_path):
    p = tmp_path / 'week11_ats_full_card.csv'; p.write_bytes(b'original')
    with pytest.raises(FileExistsError):
        finalizer.require_new_card_outputs(tmp_path)
    assert p.read_bytes() == b'original'


def test_historical_cumulative_inputs_are_bounded_and_replayed():
    for week in range(4, 10):
        rows, record = execution.prior_stats(week)
        assert len(rows) == 138
        assert record['parameters']['endWeek'] == week
        assert all(r['season'] == 2026 for r in rows)


def test_source_preparation_cannot_precede_image_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(source, 'SOURCE', tmp_path / 'new.csv')
    monkeypatch.setattr(source, 'METADATA', tmp_path / 'new.json')
    monkeypatch.setattr(source, 'OUT', tmp_path)
    with pytest.raises(ValueError, match='image recovery'):
        source.prepare(tmp_path, now=datetime(2026, 11, 11, 14, tzinfo=timezone.utc))
