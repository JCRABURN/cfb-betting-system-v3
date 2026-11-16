"""Read-only replay of a separately timestamped Friday contextual review.

No model execution, new selection, confidence change, or historical rewrite.
The previous five remain byte-equivalent JSON objects; updates are separate.
"""
import argparse
import copy
import gzip
import json
from datetime import datetime, timezone

from scripts import capture_week11_availability as availability
from scripts import review_week11_context as prior
from scripts import week11_context as context
from scripts.seal_week11_board import ROOT, instant, read, sha

CONTEXT = ROOT / 'outputs/2026-week11-context/20261113T1305Z-refresh'
AVAILABILITY = ROOT / 'outputs/2026-week11-context/20261113-availability-v2'
OUT = ROOT / 'outputs/2026-week11-owner-review/20261113-v2'
PINS = {
    prior.OUT / 'review.json': '6ec1fda9dec2a0825d64c4a176f2ee849fcb227c2d9b1422207a8e2ac4da46bb',
    CONTEXT / 'manifest.json': 'f7b58161758c8687dcf8f07763ca632d238c534a2108188d56c187a369b3a110',
    AVAILABILITY / 'manifest.json': '3b8358117fa8311e74e27ac8dcf8e1c2b705f30b80787a9ab0747b8f2d972c98',
}
OBSERVATIONS = [
    {'source': 'article-colorado-3', 'assessment':
     'Colorado November12 preview confirms Friday 8:15pm Mountain kickoff. Its run defense has allowed3.53 yards/carry and five rushing TDs through nine games; Houston is2-2 away. This supports only the existing tentative cushion argument. Colorado scored10 last game; Houston offensive-line strength and Colorado personnel/kicking limitations remain risks. No numeric adjustment.'},
    {'source': 'article-duke-5', 'assessment':
     'Newly published Patke interview discusses an earlier4-0 team and pre-bye performance. Its publication date does not make that discussion a current injury report or current defensive efficiency sample. Do not treat it as new personnel clearance.'},
    {'source': 'article-duke-6', 'assessment':
     'Video landing page contains no substantive transcript. No new performance or medical claim inferred.'},
]


def reports(folder):
    result = {}
    for conference in availability.OFFICIAL:
        payload = json.loads(gzip.decompress((folder / (conference + '.json.gz')).read_bytes()))
        for report in payload.values():
            for team in report['games']:
                name = team['teamDisplayName']
                if name in result:
                    raise ValueError('ambiguous duplicate team report')
                result[name] = dict(conference=conference, date=report['publishDate'],
                                    time=report['postedTime'], timezone=report['conferenceTimeZone'],
                                    report_type=report['ReportType'],
                                    rows={r['name']: r['status'] for r in team['rows']})
    return result


def build(as_of):
    for path, digest in PINS.items():
        if sha(path) != digest:
            raise ValueError('pinned source identity changed')
    context.verify(CONTEXT)
    availability.verify(AVAILABILITY)
    previous = read(prior.OUT / 'review.json')
    captured = read(CONTEXT / 'manifest.json')
    report_manifest = read(AVAILABILITY / 'manifest.json')
    if instant(as_of) < max(instant(captured['completed_at_utc']), instant(report_manifest['created_at_utc'])):
        raise ValueError('review cannot precede evidence capture')
    old, new = reports(prior.AVAILABILITY), reports(AVAILABILITY)
    weather = {r['game_id']: r for r in captured['weather']}
    schedule = {r['game_id']: r for r in captured['candidates']}
    market = {str(r['id']): r for r in json.loads(gzip.decompress((CONTEXT / 'separate-current-market.gz').read_bytes()))}
    updates = []
    for row in previous['candidates']:
        gid = row['game_id']
        if instant(row['kickoff_utc']) <= instant(as_of):
            updates.append(dict(game_id=gid, status='FROZEN_STARTED_NO_NEW_CONTEXT', previous_row=copy.deepcopy(row)))
            continue
        team_updates = []
        for side in ('away', 'home'):
            team = schedule[gid][side]
            before, after = old.get(team), new.get(team)
            changes = []
            if before and after:
                for name in sorted(set(before['rows']) | set(after['rows'])):
                    a, b = before['rows'].get(name), after['rows'].get(name)
                    if a != b:
                        changes.append(dict(player=name, previous=a, current=b))
            team_updates.append(dict(team=team, official_report=after, changes=changes,
                                     clearance='INCOMPLETE_NOT_STARTER_CONFIRMATION'))
        updates.append(dict(game_id=gid, status='PREGAME_CONTEXT_REFRESH_ONLY', teams=team_updates,
                            weather=weather.get(gid), separate_market_observation=market.get(gid),
                            market_status='RETRIEVAL_TIME_ONLY_NOT_QUALIFIED_CLV', numeric_adjustments=[]))
    entries = {r['name']: r for r in captured['records']}
    observations = [dict(note, source_url=entries[note['source']]['url'],
                         raw_sha256=entries[note['source']]['raw_sha256']) for note in OBSERVATIONS]
    return dict(created_at_utc=as_of, status='PROVISIONAL_CONTEXT_REFRESH_NO_SELECTION_CHANGE',
                owner_approval='PENDING', choices=copy.deepcopy(previous['choices']),
                selection_changes=[], confidence_changes=[], numeric_adjustments=[],
                original_combined_research_top5=previous['original_combined_research_top5'],
                input_sha256={p.relative_to(ROOT).as_posix(): d for p, d in PINS.items()},
                candidate_updates=updates, reviewed_observations=observations,
                decision='Retain the same five and ordinal confidence2/2/1/1/1. New availability adds risks but does not establish a quantified forecast change or a better validated alternative. Earlier reasons are retained as historical text; the current status deltas explicitly supersede older personnel designations.',
                limitations=['Not final game-day clearance; Available does not designate a starter.',
                             'Boston College/Notre Dame and CSU/WSU final full personnel reports remain missing.',
                             'No new coaching change verified; a dated interview is not a current availability report.',
                             'Hourly weather has no gust observations; retrieval-time markets are not closing prices.',
                             'No model recalculation, confidence calibration, owner approval or policy promotion.'])


def markdown(value):
    lines = ['# Week 11 Friday owner review', '', value['created_at_utc'], '',
             value['decision'], '', 'Owner approval PENDING. Human confidence is ordinal, not a probability.', '',
             '| Rank | Pick / locked line | Frozen projection | Human confidence |',
             '|---:|---|---:|---:|']
    for r in value['choices']:
        lines.append(f"| {r['rank']} | {r['game']}: {r['pick']} {r['contest_line']:+g} | {r['frozen_projection']:.2f} ({r['projection_orientation']}) | {r['human_confidence']}/5 |")
    lines += ['', '## Official report changes', '']
    for game in value['candidate_updates']:
        for team in game.get('teams', []):
            for change in team['changes']:
                lines.append(f"- {team['team']}: {change['player']}: {change['previous']} -> {change['current']}.")
    lines += ['', '## Reviewed source qualifications', '']
    for note in value['reviewed_observations']:
        lines.append(f"- {note['assessment']} [Official source]({note['source_url']})")
    lines += ['', 'All weather windows, report rows, exact hashes and separate market observations are in the JSON companion. Original ranks, forecasts, contest lines and all previous reviews are preserved.', '', *['- '+s for s in value['limitations']], '']
    return '\n'.join(lines)


def main(verify=False):
    if verify:
        saved = read(OUT / 'review.json')
        value = build(saved['created_at_utc'])
        if value != saved or (OUT / 'REVIEW.md').read_text(encoding='utf-8') != markdown(value):
            raise ValueError('Friday review exact replay mismatch')
    else:
        if OUT.exists():
            raise FileExistsError('never overwrite owner review')
        value = build(datetime.now(timezone.utc).isoformat())
        OUT.mkdir(parents=True)
        for name, content in [('review.json', json.dumps(value, indent=2, sort_keys=True)+'\n'), ('REVIEW.md', markdown(value))]:
            with (OUT / name).open('x', encoding='utf-8', newline='\n') as stream:
                stream.write(content)
    return dict(status=value['status'], recommendations=len(value['choices']), owner_approval='PENDING')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify', action='store_true')
    print(json.dumps(main(parser.parse_args().verify)))
