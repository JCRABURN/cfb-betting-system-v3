"""Add actual seal custody to the unchanged original delivery without replacing it."""
import argparse
import csv
import io
import json
from scripts.prepare_week12_source import ROOT,digest,csv_bytes,serialized

OUT=ROOT/'outputs/2026-week12-delivery/v2'

def build():
    folder=OUT.parent
    seal_raw=(folder/'initial-seal.json').read_bytes();seal=json.loads(seal_raw)
    late=set(seal['late_custody_game_ids'])
    outputs={};inputs={'initial-seal.json':digest(seal_raw)}
    for name in ('full-card-66.csv','all-132-markets.csv'):
        raw=(folder/'v1'/name).read_bytes();inputs['v1/'+name]=digest(raw)
        rows=list(csv.DictReader(io.StringIO(raw.decode())))
        for row in rows:
            row['custody']='NO_ORIGINAL_FORECAST' if row['status']=='ELAPSED_NO_PROSPECTIVE_FORECAST' else (
                'LATE_CUSTODY_RECORDED_PREGAME_TIME_NOT_INDEPENDENTLY_VERIFIED' if int(row['game_id']) in late else 'FORWARD_SEALED')
            row['actual_sealed_at_utc']=seal['sealed_at_utc']
        outputs[name]=csv_bytes(rows)
    outputs['manifest.json']=serialized(dict(version='week12-custody-qualified-delivery-v2',inputs=inputs,
        forward_games=seal['forward_sealed_games'],late_games=len(late),no_forecast_games=3,
        original_forecasts_changed=False,files={name:digest(raw) for name,raw in outputs.items()}))
    return outputs

def main(verify=False):
    files=build()
    if verify:
        if {p.name for p in OUT.iterdir()}!=set(files):raise ValueError('qualified delivery coverage')
        for name,raw in files.items():
            if (OUT/name).read_bytes()!=raw:raise ValueError('qualified delivery mismatch')
    else:
        OUT.mkdir(exist_ok=False)
        for name,raw in files.items():(OUT/name).write_bytes(raw)
    return dict(files=len(files),forward_games=61,late_games=2,no_forecast_games=3)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--verify',action='store_true');print(json.dumps(main(p.parse_args().verify)))
