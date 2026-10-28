"""Append-only context capture; never writes to the sealed card or database."""
from __future__ import annotations
import argparse
import csv
import gzip
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
from scripts.capture_week6_core import _key

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "outputs/2026-week9-prospective"
SITES = {"Navy":"navysports.com", "Notre Dame":"fightingirish.com", "Mississippi State":"hailstate.com",
 "Texas":"texaslonghorns.com", "Troy":"troytrojans.com", "James Madison":"jmusports.com",
 "Northwestern":"nusports.com", "Oregon":"goducks.com", "San Jose State":"sjsuspartans.com",
 "New Mexico":"golobos.com", "Florida Atlantic":"fausports.com", "North Texas":"meangreensports.com",
 "Colorado State":"csurams.com", "Utah State":"utahstateaggies.com", "Wisconsin":"uwbadgers.com",
 "Iowa":"hawkeyesports.com", "Southern Miss":"southernmiss.com", "UL Monroe":"ulmwarhawks.com",
 "SMU":"smumustangs.com", "Syracuse":"cuse.com", "Texas State":"txst.com", "Boise State":"broncosports.com"}

def now(): return datetime.now(timezone.utc).isoformat()
def instant(s): return datetime.fromisoformat(s.replace("Z", "+00:00"))

def official_article_links(base, links, as_of):
    """Only direct news pages on the same official host, dated by capture day."""
    result=set()
    for link in links:
        url=urljoin(base,link); parsed=urlparse(url)
        if parsed.scheme!='https' or parsed.netloc!=urlparse(base).netloc or parsed.query:
            continue
        match=re.search(r'^/news/(\d{4})/(\d{1,2})/(\d{1,2})/',parsed.path)
        if not match:continue
        published=datetime(*map(int,match.groups()),tzinfo=timezone.utc).date()
        if as_of.date()-timedelta(days=7)<=published<=as_of.date():result.add(url)
    return sorted(result)

class Page(HTMLParser):
    def __init__(self): super().__init__(); self.links=[]; self.words=[]; self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ("script","style"): self.hidden+=1
        if tag=="a" and dict(attrs).get("href"): self.links.append(dict(attrs)["href"])
    def handle_endtag(self,tag):
        if tag in ("script","style"): self.hidden=max(0,self.hidden-1)
    def handle_data(self,data):
        if not self.hidden and data.strip(): self.words.append(data.strip())

def capture(output: Path):
    output=output.resolve()
    if not output.is_relative_to(ROOT/"outputs/2026-week9-context") or output.exists():
        raise ValueError("context needs a new version under outputs/2026-week9-context")
    output.mkdir(parents=True)
    def get(name,url,headers=None):
        item={"name":name,"url":url,"requested_at_utc":now(),"status":"UNAVAILABLE"}
        try:
            response=requests.get(url,headers=headers or {"User-Agent":"CFB-Audit/1.0"},timeout=30)
            item.update(http_status=response.status_code,received_at_utc=now(),resolved_url=response.url)
            response.raise_for_status(); raw=response.content
            path=name+".gz"; (output/path).write_bytes(gzip.compress(raw,mtime=0))
            item.update(path=path,sha256=hashlib.sha256(raw).hexdigest(),status="CAPTURED")
            return item,raw
        except requests.RequestException as exc:
            item.update(error_type=type(exc).__name__,received_at_utc=now()); return item,None
    records=[]
    games=json.loads((BOARD/"core-initial/cfbd-2026-games.json").read_text(encoding="utf-8"))
    ids={x["game_id"] for x in json.loads((BOARD/"week9_locked_line_snapshot.json").read_text())["lines"]}
    kickoffs={g['id']:instant(g['startDate']) for g in games if g['id'] in ids}
    def espn(gid):
        if datetime.now(timezone.utc)>=kickoffs[gid]:
            return {'name':f'espn-{gid}','status':'SKIPPED_KICKOFF_PASSED','game_id':gid}
        return get(f"espn-{gid}",f"https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary?event={gid}")[0]
    with ThreadPoolExecutor(max_workers=6) as pool:records+=list(pool.map(espn,sorted(ids)))
    for name,url in [("cfbd-venues","https://api.collegefootballdata.com/venues"),
                     ("cfbd-current-week9-lines","https://api.collegefootballdata.com/lines?year=2026&week=9&seasonType=regular")]:
        item,raw=get(name,url,{"Authorization":"Bearer "+_key()}); records.append(item)
        if name=="cfbd-venues":venues={x["id"]:x for x in json.loads(raw)} if raw else {}
    def site(pair):
        team,host=pair; name=re.sub(r"[^a-z0-9]+","-",team.lower()); url=f"https://{host}/sports/football"
        item,raw=get("official-"+name,url); result=[item]
        if raw:
            page=Page();page.feed(raw.decode("utf-8",errors="replace"))
            links=official_article_links(url,page.links,datetime.now(timezone.utc))
            # News links discovered on official football landing pages; content reviewed separately.
            for i,link in enumerate(links):
                entry,data=get(f"article-{name}-{i}",link);result.append(entry)
                if data:
                    p=Page();p.feed(data.decode("utf-8",errors="replace"))
                    (output/f"article-{name}-{i}.txt").write_text("\n".join(p.words),encoding="utf-8",newline="\n")
        return result
    with ThreadPoolExecutor(max_workers=6) as pool:
        for result in pool.map(site,SITES.items()):records+=result
    # Forecast all 54 venues, not observations or model inputs.
    def weather(game):
        gid=game["id"]; v=venues.get(game["venueId"]); row={"game_id":gid,"status":"UNAVAILABLE","requests":[]}
        if datetime.now(timezone.utc)>=instant(game['startDate']):
            return dict(row,status='SKIPPED_KICKOFF_PASSED')
        if not v:return row
        row["venue"]=v; row["kickoff_utc"]=game["startDate"]
        entry,raw=get(f"weather-point-{gid}",f"https://api.weather.gov/points/{v['latitude']:.4f},{v['longitude']:.4f}")
        row["requests"].append(entry)
        if raw:
            url=json.loads(raw).get("properties",{}).get("forecastHourly")
            if url:
                entry,raw=get(f"weather-hourly-{gid}",url);row["requests"].append(entry)
                if raw:
                    props=json.loads(raw)["properties"]; kickoff=instant(game["startDate"])
                    row["game_hours"]=[h for h in props["periods"] if instant(h["startTime"])<kickoff+timedelta(hours=3) and instant(h["endTime"])>kickoff]
                    row.update(status="CAPTURED" if row["game_hours"] else "NO_KICKOFF_COVERAGE",forecast_generated_at=props.get("generatedAt"),gust_status="UNAVAILABLE_IN_HOURLY_PRODUCT",field_condition="UNCONFIRMED")
        return row
    with ThreadPoolExecutor(max_workers=6) as pool:weather_rows=list(pool.map(weather,[g for g in games if g["id"] in ids]))
    manifest={"captured_at_utc":now(),"records":records,"weather":weather_rows,"model_adjustments":[],
              "market_usage":"CURRENT_CONTEXT_ONLY;NOT_HISTORICAL_CLOSE;NEVER_REPLACES_CONTEST_LINE"}
    (output/"capture-manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps({"records":len(records),"unavailable":sum(x["status"]!="CAPTURED" for x in records),"weather_games":len(weather_rows),"weather_captured":sum(x["status"]=="CAPTURED" for x in weather_rows)}))

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,required=True);capture(p.parse_args().output)
