"""Additional read-only validation; never rewrites the pre-kickoff v1 snapshot."""
import hashlib
import json
from .data import HERE, load, instant
from .engine import Fit
from .run import canonical

HOLDOUT_SHA = '592b564798c434846ce169728aa3d0a4fd1b112d5397e587d40703ce2e58c23c'


def verify_holdout(directory=None):
    directory = directory or HERE/'holdout/20261106-v1'
    raw = (directory/'prospective.json').read_bytes()
    seal = json.loads((directory/'seal.json').read_bytes())
    if hashlib.sha256(raw).hexdigest() != HOLDOUT_SHA or seal['sha256'] != HOLDOUT_SHA:
        raise ValueError('prospective byte seal changed')
    held = json.loads(raw)
    if held['generated_at_utc'] != seal['generated_at_utc']:
        raise ValueError('prospective custody contradiction')
    if held['status'] != 'PROSPECTIVE_RESEARCH_ONLY_NOT_CONTEST_REVISION' or held['owner_approval'] != 'PENDING' or held['policy_changed']:
        raise ValueError('unauthorized status')
    rows, protocol = load()
    if held['protocol_sha256'] != hashlib.sha256((HERE/'protocol.json').read_bytes()).hexdigest():
        raise ValueError('prospective protocol identity')
    # Only the original declared source files are checked; later additive
    # verification/report modules are not misrepresented as the holdout source.
    for name, digest in held['source_code_sha256_lf'].items():
        if hashlib.sha256((HERE/name).read_bytes().replace(b'\r\n', b'\n')).hexdigest() != digest:
            raise ValueError('holdout generating code changed: '+name)
    expected = {(r['game_id'], r['market'], c) for r in rows if r['week'] == 10 for c in protocol['candidates']}
    actual = [(r['game_id'], r['market'], r['candidate']) for r in held['selections']]
    if len(actual) != len(set(actual)) or set(actual) != expected or held['eligible_shadow_games'] != 57:
        raise ValueError('prospective exact coverage')
    fits = {m: Fit([r for r in rows if r['week'] < 10 and r['market'] == m], 10, protocol) for m in protocol['markets']}
    originals = {(r['game_id'], r['market']): r for r in rows if r['week'] == 10}
    for archived in held['selections']:
        if instant(archived['kickoff']) <= instant(held['generated_at_utc']):
            raise ValueError('holdout is not prospective')
        row = originals[archived['game_id'], archived['market']]
        computed = fits[row['market']].predict(row, archived['candidate'])
        # Canonical precision applies only to derived research computations.
        # Original card/source/holdout bytes remain protected by exact SHA256.
        if canonical(computed) != canonical(archived):
            raise ValueError('prospective research computation mismatch')
    return {'status': 'VERIFIED', 'games': 57, 'candidate_rows': len(actual), 'sha256': HOLDOUT_SHA,
            'generated_at_utc': held['generated_at_utc'], 'source_commit': held['source_commit']}


if __name__ == '__main__':
    print(json.dumps(verify_holdout(), sort_keys=True))
