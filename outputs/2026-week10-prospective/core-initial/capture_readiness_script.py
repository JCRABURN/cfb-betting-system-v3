import csv,hashlib,json,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone
import requests
sys.path.insert(0,str(Path.cwd()))
from scripts.capture_week6_core import _key,BASE
from ingestion import CanonicalTeamResolver
root=Path.cwd();out=root/'outputs/2026-week10-readiness'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');out.mkdir(parents=True,exist_ok=False)
items=[]
specs=[('games','/games',{'year':2026,'classification':'fbs'}),('teams','/teams/fbs',{'year':2026}),('week9-advanced','/stats/season/advanced',{'year':2026,'endWeek':9,'excludeGarbageTime':'true'})]
data={};key=_key()
for name,endpoint,params in specs:
 requested=datetime.now(timezone.utc).isoformat();r=requests.get(BASE+endpoint,params=params,headers={'Authorization':'Bearer '+key},timeout=60);received=datetime.now(timezone.utc).isoformat();raw=r.content;(out/(name+'.raw.json')).write_bytes(raw)
 item={'name':name,'endpoint':BASE+endpoint,'parameters':params,'requested_at_utc':requested,'received_at_utc':received,'status_code':r.status_code,'raw_sha256':hashlib.sha256(raw).hexdigest(),'path':name+'.raw.json'};items.append(item)
 (out/'capture-manifest.json').write_text(json.dumps({'status':'INCOMPLETE','requests':items},indent=2)+'\n',encoding='utf-8',newline='\n');r.raise_for_status();data[name]=r.json();assert isinstance(data[name],list);item['records']=len(data[name]);print(name,len(data[name]),flush=True)
del key
source=root/'data/ingest/2026-week10-splashsports-screen-capture.csv';meta=root/'data/ingest/2026-week10-splashsports-source-manifest.json';rows=list(csv.DictReader(source.open(encoding='utf-8-sig',newline='')));manifest=json.loads(meta.read_bytes());resolver=CanonicalTeamResolver([t['school'] for t in data['teams']]);now=datetime.now(timezone.utc)
def canon(name,provider):
 r=resolver.resolve(provider,name)
 if r.status!='resolved':raise ValueError('Unresolved identity '+name)
 return r.canonical_name
schedule={}
for g in data['games']:
 if g.get('week')==10 and g.get('homeClassification')==g.get('awayClassification')=='fbs':schedule[(canon(g['awayTeam'],'collegefootballdata'),canon(g['homeTeam'],'collegefootballdata'))]=g
results=[];seen=set()
for row in rows:
 try:pair=(canon(row['away_team'],'SplashSports'),canon(row['home_team'],'SplashSports'))
 except ValueError as exc:results.append({'source':row,'status':'UNRESOLVED','error':str(exc)});continue
 seen.add(pair);g=schedule.get(pair)
 if not g:results.append({'source':row,'status':'NO_FBS_SCHEDULE_MATCH'});continue
 kickoff=datetime.fromisoformat(g['startDate'].replace('Z','+00:00'))
 state='EXCLUDED_ELAPSED' if kickoff<=now or g.get('completed') else 'UPCOMING'
 results.append({'source':row,'game_id':g['id'],'kickoff_utc':g['startDate'],'status':state,'target_score_present':g.get('homePoints') is not None or g.get('awayPoints') is not None,'source_spreads_opposite':float(row['away_spread'])==-float(row['home_spread'])})
result={'checked_at_utc':now.isoformat(),'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'source_csv_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'source_manifest_sha256':hashlib.sha256(meta.read_bytes()).hexdigest(),'source_rows':len(rows),'fbs_schedule_games':len(schedule),'upcoming':sum(r['status']=='UPCOMING' for r in results),'excluded':sum(r['status']=='EXCLUDED_ELAPSED' for r in results),'source_image_bytes_available':False,'official_card_status':'BLOCKED_SCREENSHOT_RECONCILIATION_AND_REVIEW_INTEGRATION_PENDING','missing_source_matchups':[list(k) for k in schedule if k not in seen],'rows':results,'statistics_cutoff_week':9,'model_run':False,'database_mutated':False}
(out/'readiness.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n');(out/'capture-manifest.json').write_text(json.dumps({'status':'COMPLETE','requests':items},indent=2)+'\n',encoding='utf-8',newline='\n');print(json.dumps({k:v for k,v in result.items() if k!='rows'}),flush=True);print('EVIDENCE_DIR='+str(out),flush=True)
