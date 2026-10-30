"""One-time, owner-authorized CI activation receipt generator; not a workflow."""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
import requests

OUT = Path(__file__).resolve().parent
BASE = 'https://api.github.com/repos/JCRABURN/cfb-betting-system-v3/'
CI = 328094886
OPS = (327189312, 327189314, 339530568, 337926765, 341565576, 327189316)
HEADS = {44: '922f1f8f8c66ef14674eb9aa20db144a45dada68',
         45: '6e1948dd9b675a3f1226350ce5b40a6556e09f7a'}
def now(): return datetime.now(timezone.utc).isoformat()

def main(phase):
    cred = subprocess.run(['git', 'credential', 'fill'],
        input='protocol=https\nhost=github.com\n\n', capture_output=True, text=True,
        check=True, env=dict(os.environ, GCM_INTERACTIVE='Never', GIT_TERMINAL_PROMPT='0'))
    fields = dict(line.split('=', 1) for line in cred.stdout.splitlines() if '=' in line)
    session = requests.Session()
    session.headers.update(Authorization='Bearer ' + fields['password'],
        Accept='application/vnd.github+json', **{'X-GitHub-Api-Version': '2022-11-28'})
    del cred, fields
    receipts = []
    target = OUT / (phase + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    def api(method, path, body=None, allowed=(200, 204)):
        row = dict(method=method, endpoint=path, requested_at_utc=now(), request_body=body)
        response = session.request(method, BASE + path, json=body, timeout=45)
        row.update(received_at_utc=now(), http_status=response.status_code,
            body=response.json() if response.content else None,
            github_request_id=response.headers.get('X-GitHub-Request-Id'))
        receipts.append(row)
        target.write_text(json.dumps(receipts, indent=2) + '\n', encoding='utf-8', newline='\n')
        if response.status_code not in allowed:
            raise RuntimeError(f'{method} {path}: unexpected HTTP {response.status_code}; STOP')
        return row['body']
    def states(disabled=False):
        w = api('GET', 'actions/workflows?per_page=100')
        assert w['total_count'] == 7, 'Unexpected workflow inventory; STOP'
        actual = {x['id']: x for x in w['workflows']}
        assert set(actual) == set(OPS) | {CI}, 'Unexpected workflow IDs; STOP'
        assert actual[CI]['state'] == 'active' and actual[CI]['path'] == '.github/workflows/ci.yml'
        if disabled:
            assert all(actual[x]['state'] == 'disabled_manually' for x in OPS), 'Operational workflow active; STOP'
        return actual
    def permissions(enabled):
        p = api('GET', 'actions/permissions')
        assert p['enabled'] is enabled, 'Unexpected repository activation state; STOP'
        assert p.get('sha_pinning_required') is False, 'Unexpected SHA pinning setting; STOP'
        t = api('GET', 'actions/permissions/workflow')
        assert t == {'default_workflow_permissions': 'read', 'can_approve_pull_request_reviews': False}, 'Token defaults changed; STOP'
    def pulls():
        for number, sha in HEADS.items():
            p = api('GET', f'pulls/{number}')
            assert p['state'] == 'open' and not p['merged'] and p['draft'] is True
            assert p['head']['sha'] == sha and p['base']['ref'] == 'main', 'PR identity changed; STOP'
    if phase == 'preflight':
        permissions(False); states(); pulls()
        api('GET', 'branches/main/protection', allowed=(404,))
        assert api('GET', 'rulesets') == []
        api('GET', 'actions/runs?per_page=100')
    elif phase == 'disable':
        permissions(False); states(); pulls()
        for wid in OPS:
            api('PUT', f'actions/workflows/{wid}/disable')
        states(True); permissions(False)
    elif phase == 'enable':
        permissions(False); states(True); pulls()
        api('PUT', 'actions/permissions', {'enabled': True})
        try:
            permissions(True); states(True)
        except Exception:
            api('PUT', 'actions/permissions', {'enabled': False})
            raise
    elif phase == 'trigger':
        permissions(True); states(True); pulls()
        for number, sha in HEADS.items():
            closed = api('PATCH', f'pulls/{number}', {'state': 'closed'})
            assert closed['state'] == 'closed' and closed['draft'] and closed['head']['sha'] == sha
            opened = api('PATCH', f'pulls/{number}', {'state': 'open'})
            assert opened['state'] == 'open' and opened['draft'] and opened['head']['sha'] == sha
        permissions(True); states(True)
    elif phase == 'status':
        permissions(True); states(True)
        runs = api('GET', 'actions/runs?per_page=100')
        assert all(r['workflow_id'] == CI for r in runs['workflow_runs']), 'Unexpected operational run; STOP'
        for run in runs['workflow_runs']:
            api('GET', f"actions/runs/{run['id']}/jobs?per_page=100")
        for n in (44,45,46):
            p = api('GET', f'pulls/{n}')
            api('GET', f'pulls/{n}/reviews')
            api('GET', f"commits/{p['head']['sha']}/check-runs")
        print(json.dumps([{'id':r['id'],'url':r['html_url'],'head_sha':r['head_sha'],
            'status':r['status'],'conclusion':r['conclusion']} for r in runs['workflow_runs']]))
    else:
        raise ValueError('Unknown phase')
    print(json.dumps({'phase':phase,'result':'PASS','receipt':str(target)}))

if __name__ == '__main__':
    main(sys.argv[1])
