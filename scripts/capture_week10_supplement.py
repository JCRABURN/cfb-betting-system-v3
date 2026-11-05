"""Append-only public source retrieval for a manually reviewed pregame supplement."""
import argparse
import gzip
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests
from scripts.capture_week10_context import Page, ROOT, instant


def capture(output, urls, cutoff):
    output = Path(output).resolve()
    if not output.is_relative_to(ROOT / 'outputs/2026-week10-context') or output.exists():
        raise ValueError('new Week10 context directory required')
    if datetime.now(timezone.utc) >= instant(cutoff):
        raise ValueError('supplement cutoff passed')
    output.mkdir(parents=True)

    def get(pair):
        name, url = pair
        if not name.replace('-', '').isalnum() or not url.startswith('https://'):
            raise ValueError('invalid source identity')
        item = dict(name=name, url=url, requested_at_utc=datetime.now(timezone.utc).isoformat())
        try:
            response = requests.get(url, timeout=35, headers={'User-Agent': 'CFB-Pregame-Context/1.0'})
            raw = response.content
            path = name + '.gz'
            (output / path).write_bytes(gzip.compress(raw, mtime=0))
            item.update(path=path, sha256=hashlib.sha256(raw).hexdigest(), http_status=response.status_code,
                        resolved_url=response.url, received_at_utc=datetime.now(timezone.utc).isoformat(),
                        status='CAPTURED' if response.ok else 'HTTP_ERROR', content_type=response.headers.get('content-type'))
            if raw.startswith(b'%PDF'):
                (output / (name + '.pdf')).write_bytes(raw)
            elif response.ok:
                page = Page(); page.feed(raw.decode('utf-8', errors='replace'))
                (output / (name + '.txt')).write_text('\n'.join(page.words), encoding='utf-8', newline='\n')
        except requests.RequestException as exc:
            item.update(status='UNAVAILABLE', error_type=type(exc).__name__, received_at_utc=datetime.now(timezone.utc).isoformat())
        return item

    with ThreadPoolExecutor(max_workers=6) as pool:
        records = list(pool.map(get, urls.items()))
    manifest = dict(captured_at_utc=datetime.now(timezone.utc).isoformat(), cutoff_utc=cutoff, records=records,
                    capture_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    model_adjustments=[], note='HTTP success is not evidence of usable article content or medical clearance.')
    (output / 'capture-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps([{'name':r['name'], 'status':r['status']} for r in records]))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--urls',type=Path,required=True);parser.add_argument('--cutoff',required=True)
    args=parser.parse_args();capture(args.output,json.loads(args.urls.read_text(encoding='utf-8')),args.cutoff)
