"""Read regulation-time league-phase scores from OpenFootball text archives."""
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

ROOT=Path(__file__).resolve().parent
SOURCES={
    'pt.2':('europe','portugal/{season}_pt2.txt'),
    'hu.1':('europe','hungary/{season}_hu1.txt'),
    'uefa.cl':('champions-league','{season}/cl.txt'),
    'uefa.el':('champions-league','{season}/el.txt'),
    'uefa.ecl':('champions-league','{season}/conf.txt'),
}
MONTHS={m:i+1 for i,m in enumerate('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split())}

def parse_matches(payload,season,league_phase_only=False):
    year=int(season[:4])
    day=None
    phase=not league_phase_only
    rows=[]
    for raw in payload.splitlines():
        line=raw.strip()
        if line.startswith('▪') and league_phase_only:
            label=line[1:].strip().lower()
            phase=label.startswith(('league phase','league,','matchday','group stage','group '))
        stamp=re.fullmatch(r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) (\w{3})\s+(\d{1,2})(?: (\d{4}))?',line)
        if stamp and stamp[1] in MONTHS:
            month=MONTHS[stamp[1]]
            day=date(int(stamp[3]) if stamp[3] else year+(month<7),month,int(stamp[2])).isoformat()
            continue
        m=re.match(r'^(?:\d{1,2}:\d{2}\s+)?(.+?)\s+v\s+(.+?)\s+(\d+)\s*[-–]\s*(\d+)(?:\s|$)',line)
        if day and phase and m:
            names=[re.sub(r'\s+\([A-Z]{3}\)$','',m[i]).strip() for i in (1,2)]
            rows.append(dict(day=day,home=names[0],away=names[1],score=[int(m[3]),int(m[4])]))
    return rows

def fetch(job):
    code,season=job
    repo,path=SOURCES[code]
    url=f'https://raw.githubusercontent.com/openfootball/{repo}/HEAD/{path.format(season=season)}'
    try:
        with urllib.request.urlopen(url,timeout=12) as r:
            rows=parse_matches(r.read().decode('utf-8-sig'),season,code.startswith('uefa.'))
        if rows:
            target=ROOT/'data'/f'csv_{season}_{code}.json'
            target.write_text(json.dumps(rows,ensure_ascii=False)+'\n')
        return code,season,len(rows)
    except (OSError,ValueError) as exc:
        return code,season,str(exc)

def refresh_text(year):
    jobs=[(code,f'{y}-{(y+1)%100:02d}') for code in SOURCES for y in range(year-2,year+1)]
    with ThreadPoolExecutor(max_workers=12) as pool:
        print('OpenFootball text scores:',list(pool.map(fetch,jobs)))
