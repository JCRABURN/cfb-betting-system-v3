"""Pinned read-only acceptance of Week 11 source, board, context and forward shadow."""
import json
from scripts.seal_week11_board import ROOT, sha, main as verify_board
from scripts import review_week11_context as review
from research.week11_validation import forward_shadow

PINS={
 'outputs/2026-week11-prospective/week11_initial_seal_manifest.json':'d6d163f2500fa638ad73da8b4b0da244e9cad4fe456e42d80ea65e36e073868c',
 'outputs/2026-week11-context/20261112T1220Z-initial/manifest.json':'003bad5fb391b15119e585cff3107add7ff5d414c8581acd8920294e57e8f40f',
 'outputs/2026-week11-context/20261112-availability-v1/manifest.json':'491f1126eee9bbc202860e1234e9560ac88d8f4a6df07aa0e0cdf217273e641d',
 'research/week11_validation/forward-v1.json':'3c530ecd8ec696ea0e945d992a5d4d098dc675dcad6de9e24a1a730d572b8e3c',
 'outputs/2026-week11-owner-review/20261112-v1/review.json':'6ec1fda9dec2a0825d64c4a176f2ee849fcb227c2d9b1422207a8e2ac4da46bb',
}

def verify():
    for name,digest in PINS.items():
        if sha(ROOT/name)!=digest:raise ValueError('frozen evidence identity changed: '+name)
    board=verify_board(True);shadow=forward_shadow.main(True);owner=review.main(True)
    if board['capture_before_recorded_kickoff_count']!=61 or board['status']!='LATE_CUSTODY_CAPTURE_NOT_FULL_PREGAME_SEAL':raise ValueError('late custody limitation removed')
    return dict(status='READ_ONLY_BYTES_AND_REPLAY_VERIFIED_NOT_APPROVAL',board=board,shadow=shadow,owner_review=owner)

if __name__=='__main__':print(json.dumps(verify(),indent=2))
