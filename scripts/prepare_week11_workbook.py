"""Lossless CSV/JSON interchange for the bundled Artifact Tool workbook builder."""
import argparse
import csv
import json
from pathlib import Path


def prepare(folder: Path, target: Path):
    csv.field_size_limit(10_000_000)
    payload={'findings':json.loads((folder/'audit_findings.json').read_bytes()),'tables':{}}
    for p in sorted(folder.glob('*.csv')):
        with p.open(encoding='utf-8-sig',newline='') as stream:
            payload['tables'][p.name]=list(csv.DictReader(stream))
    context=folder.parent/'context-v2/pregame_context_comparison.csv'
    with context.open(encoding='utf-8-sig',newline='') as stream:
        payload['tables'][context.name]=list(csv.DictReader(stream))
    source=Path(__file__).resolve().parents[1]/'data/ingest/2026-season-splashsports-recovery/2026-splashsports-all-contest-lines.csv'
    with source.open(encoding='utf-8-sig',newline='') as stream:
        payload['tables']['source_exports.csv']=list(csv.DictReader(stream))
    target.write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False),encoding='utf8')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--folder',type=Path,required=True);p.add_argument('--target',type=Path,required=True)
    args=p.parse_args();prepare(args.folder,args.target)
