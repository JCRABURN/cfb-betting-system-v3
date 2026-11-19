"""Fail-closed source, draft market coverage and initial receipt verification."""
from __future__ import annotations
import argparse
import json
from datetime import datetime,timezone
from scripts.prepare_week12_source import ROOT,digest,serialized,timestamp
from scripts import build_week12_delivery as delivery, review_week12_context as context
from scripts.capture_week12_availability import verify as verify_reports

SEAL=ROOT/'outputs/2026-week12-delivery/initial-seal.json'
FOLDERS=('data/ingest/2026-week12-splashsports','outputs/2026-week12-prospective',
         'outputs/2026-week12-delivery/v1','outputs/2026-week12-readiness/execution-gate-20261118',
         'outputs/2026-week12-context/20261118-initial','outputs/2026-week12-context/20261118-conference',
         'outputs/2026-week12-context/20261118-supplement','outputs/2026-week12-context/review-v1',
         'outputs/2026-week12-context/review-v2')

def files():
    return {p.relative_to(ROOT).as_posix():digest(p.read_bytes()) for folder in FOLDERS
            for p in sorted((ROOT/folder).rglob('*')) if p.is_file()}

def validate_receipt(receipt):
    if receipt['files_sha256']!=files():raise ValueError('initial evidence bytes or coverage changed')
    for name,sha in receipt['model_policy_code_sha256_lf'].items():
        if digest((ROOT/name).read_bytes().replace(b'\r\n',b'\n'))!=sha:raise ValueError('approved model or policy changed')
    model=json.loads((delivery.BOARD/'week12_model_manifest.json').read_bytes())
    if digest((ROOT/'data/cfb.db').read_bytes())!=model['source_database_sha256']:raise ValueError('protected DB changed')
    lock=json.loads((delivery.BOARD/'week12_locked_line_snapshot.json').read_bytes())
    late=sorted(r['game_id'] for r in lock['lines'] if timestamp(receipt['sealed_at_utc'])>=timestamp(r['source_kickoff_utc']))
    if receipt['late_custody_game_ids']!=late or receipt['forward_sealed_games']!=63-len(late):
        raise ValueError('late custody classification contradicts actual seal time')
    status='LATE_CUSTODY_CAPTURE_NOT_FULL_PREGAME_SEAL' if late else 'PREGAME_DRAFT_SEAL_NOT_CALIBRATED_CARD_APPROVAL'
    if receipt['status']!=status:raise ValueError('late custody status omitted')
    if model['code_commit_sha']!='69d14465fdaf437f8bdec85e155d97c818c020b4':raise ValueError('original execution identity changed')

def main(seal=False):
    delivery.main(True);context.main(True);verify_reports(context.CONF)
    if seal:
        sources=[p for folder in ('business_entities','models','config') for p in (ROOT/folder).rglob('*')
                 if p.is_file() and p.suffix in ('.py','.json')]
        sealed_at=datetime.now(timezone.utc)
        lock=json.loads((delivery.BOARD/'week12_locked_line_snapshot.json').read_bytes())
        late=sorted(r['game_id'] for r in lock['lines'] if sealed_at>=timestamp(r['source_kickoff_utc']))
        receipt=dict(sealed_at_utc=sealed_at.isoformat(),files_sha256=files(),late_custody_game_ids=late,forward_sealed_games=63-len(late),
                     model_policy_code_sha256_lf={p.relative_to(ROOT).as_posix():digest(p.read_bytes().replace(b'\r\n',b'\n')) for p in sorted(sources)},
                     status='LATE_CUSTODY_CAPTURE_NOT_FULL_PREGAME_SEAL' if late else 'PREGAME_DRAFT_SEAL_NOT_CALIBRATED_CARD_APPROVAL',external_week11_submissions_used=False)
        validate_receipt(receipt)
        with SEAL.open('xb') as f:f.write(serialized(receipt))
    receipt=json.loads(SEAL.read_bytes());validate_receipt(receipt)
    return dict(status='VERIFIED_READ_ONLY_DRAFT_WITH_DECLARED_GAPS',files=len(receipt['files_sha256']),
                games=66,markets=132,eligible_predictions=126,elapsed_markets=6,official_combined_top5=False,
                forward_sealed_games=receipt['forward_sealed_games'],late_custody_games=len(receipt['late_custody_game_ids']))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--seal',action='store_true');print(json.dumps(main(p.parse_args().seal)))
