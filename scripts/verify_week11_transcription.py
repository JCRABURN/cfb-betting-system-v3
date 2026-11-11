"""Read-only review of concurrent owner transcription; never certifies missing images."""
import csv
import io
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from ingestion import CanonicalTeamResolver
from scripts import prepare_week11_readiness as readiness

ROOT=readiness.ROOT
SOURCE_COMMIT='8cccef1c5f14b4230091fb443af92f8a5665c358'
HASHES={
    'production-weeks/2026-week11-splashsports.csv':'a27f367a38918e188cc2e8aa417b9a1970049ca02d0501789d00ccfdb0b12c22',
    'production-weeks/2026-week11-splashsports-lock-metadata.json':'3b12cd8a0fb339ee30690b910bcefe1abeaeb879f0a5b4d45f895cf21a492b0a',
    'data/ingest/2026-week11-splashsports-transcription.csv':'ee7ab2b94b7ce42d57deefac6aa478a8da09c011086f921cd2cf061147058faa',
    'data/ingest/2026-week11-splashsports-schedule-reconciliation.csv':'16881fd0f9aa868a9f6953e5d210e1202bd53be600843bb3b6a348d5312d5437',
}
AS_OF='2026-11-11T01:40:28.406171+00:00'


def load(root=ROOT):
    blobs={path:(root/path).read_bytes() for path in HASHES}
    if any(readiness.digest(raw)!=HASHES[path] for path,raw in blobs.items()):
        raise ValueError('owner transcription byte custody mismatch')
    parsed={path:(json.loads(raw) if path.endswith('.json') else list(csv.DictReader(io.StringIO(raw.decode()))))
            for path,raw in blobs.items()}
    return tuple(parsed.values())


def reconcile(source,metadata,transcription,reconciliation,schedule,as_of=AS_OF):
    if not(len(source)==len(transcription)==len(reconciliation)==len(schedule)==67):raise ValueError('exact 67-game coverage required')
    expected=readiness.unique(schedule,'game_id');seen=set();counts={};elapsed=[]
    aliases=json.loads((readiness.OUT/'resolver-aliases.json').read_bytes())
    aliases['SplashSports'].update(metadata['normalized_aliases'])
    resolver=CanonicalTeamResolver(sorted({r[s] for r in schedule for s in ('home','away')}),aliases)
    for order,(s,t,r) in enumerate(zip(source,transcription,reconciliation),1):
        if int(t['source_order'])!=order or int(r['source_order'])!=order:raise ValueError('source order mismatch')
        gid=r['game_id']
        if gid in seen or gid not in expected:raise ValueError('duplicate or unsupported game')
        seen.add(gid);game=expected[gid]
        for side,column in [('away','Away Team'),('home','Home Team')]:
            if s[column]!=t[side+'_team'] or s[column]!=r['source_'+side]:raise ValueError('source team conflict')
            normalized=resolver.resolve('SplashSports',s[column])
            if normalized.status!='resolved' or normalized.canonical_name!=game[side] or r['canonical_'+side]!=game[side]:
                raise ValueError('canonical team orientation conflict')
        numbers=[Decimal(s['Spread']),Decimal(t['home_spread']),Decimal(r['home_spread'])]
        totals=[Decimal(s['Total']),Decimal(t['total']),Decimal(r['locked_total'])]
        if any(not v.is_finite() for v in numbers+totals) or len(set(numbers))!=1 or len(set(totals))!=1 or totals[0]<=0:
            raise ValueError('contest line discrepancy')
        if Decimal(t['away_spread'])!=-numbers[0]:raise ValueError('away spread sign conflict')
        if s['Game Date']!=t['date_displayed'] or s['Game Time']!=t['time_displayed']:raise ValueError('source clock conflict')
        if not '2026-11-10'<=s['Game Date']<='2026-11-14':raise ValueError('outside fixed Week11 clock reconciliation window')
        # Verify the observed UTC-06 offset against both providers for this dated card.
        # This is not a general timezone implementation or an unlabeled-source assertion.
        local=datetime.strptime(s['Game Date']+' '+s['Game Time'],'%Y-%m-%d %I:%M %p').replace(tzinfo=timezone(timedelta(hours=-6)))
        kickoff=local.astimezone(timezone.utc)
        if kickoff!=readiness.timestamp(game['kickoff_utc']) or kickoff!=readiness.timestamp(r['provider_utc_kickoff']):raise ValueError('provider kickoff conflict')
        screenshot=t['screenshot_number'];counts[screenshot]=counts.get(screenshot,0)+1
        if int(t['row_in_screenshot'])!=counts[screenshot]:raise ValueError('screenshot row identity')
        if kickoff<=readiness.timestamp(as_of):elapsed.append(gid)
    if seen!=set(expected) or counts!=metadata['screenshot_row_counts']:raise ValueError('source coverage mismatch')
    if metadata['game_count']!=67 or metadata['screenshot_count']!=8 or metadata['model_predictions_generated'] is not False:
        raise ValueError('source status contradiction')
    return dict(status='TRANSCRIPTION_BYTES_AND_67_MATCHUPS_VERIFIED_ORIGINAL_IMAGE_CUSTODY_INCOMPLETE',
                source_commit=SOURCE_COMMIT,source_sha256=HASHES,source_rows=67,spread_rows=67,total_rows=67,
                screenshot_references=8,screenshot_images_independently_verified_here=0,
                original_image_custody='INCOMPLETE: remote metadata reports original image bytes unavailable; last-asset hash alone is not independent verification',
                source_observed_no_later_than=metadata['source_observed_no_later_than'],owner_quote_timestamp=metadata['owner_screenshot_quote_timestamp'],
                kickoff_zone_basis='For November10-14 only, UTC-06:00 matches all67 provider kickoffs, consistent with America/Chicago; screenshots do not label timezone',
                eligibility_as_of_utc=as_of,elapsed_by_archived_schedule=elapsed,remaining_by_archived_schedule=67-len(elapsed),
                model_lock_or_seal_created=False,ats_picks=0,totals_picks=0,owner_selection_approval='PENDING',
                supersession='The concurrent source delivery supersedes earlier local no-screenshot-receipt statements. Earlier captures/gates remain intact.',
                blockers=['Recover and independently inspect all eight original images with actual receipt and byte hashes',
                          'Refresh live schedule and status before prospective execution; never backfill elapsed games',
                          'Formal disposable-database ingestion, model lock/seal, full cards and candidate context review remain pending'])


def verify():
    return reconcile(*load(),json.loads((readiness.OUT/'schedule.json').read_bytes()))


if __name__=='__main__':print(json.dumps(verify(),indent=2,sort_keys=True))
