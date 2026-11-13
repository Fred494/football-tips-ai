"""UEFA's public editorial schedule and open international scores."""
import csv
import html
import io
import json
import re
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from afcon import SOURCE as CAF_SOURCE, parse_afcon

ROOT = Path(__file__).resolve().parent
SCHEDULE = 'https://www.uefa.com/uefanationsleague/news/02a2-1fea18abbcbc-456e846509e7-1000--2026-27-uefa-nations-league-all-the-league-phase-fixtures-a/'
RESULTS = 'https://raw.githubusercontent.com/martj42/international_results/master/results.csv'
CODES = {
    'UEFA Nations League': 'int.unl', 'UEFA Euro': 'int.euro',
    'UEFA Euro qualification': 'int.euroq', 'FIFA World Cup': 'int.wc',
    'FIFA World Cup qualification': 'int.wcq', 'Copa América': 'int.copa',
    'African Cup of Nations': 'int.afcon', 'African Cup of Nations qualification': 'int.afconq', 'AFC Asian Cup': 'int.asian',
    'Gold Cup': 'int.gold', 'CONCACAF Nations League': 'int.cnl',
}
ALIASES = {'Türkiye':'Turkey','Czechia':'Czech Republic','Republic of Ireland':'Republic of Ireland',
           'Faroe Islands':'Faroe Islands','Bosnia and Herzegovina':'Bosnia and Herzegovina'}

def name(value):
    value=' '.join(value.split())
    return ALIASES.get(value,value)

def get(url):
    with urllib.request.urlopen(url,timeout=30) as response:
        return response.read().decode('utf-8')

def parse_schedule(page):
    parsed=[]
    day=None
    for block in re.findall(r'<p(?:\s[^>]*)?>(.*?)</p>',page,re.S|re.I):
        plain=html.unescape(re.sub(r'<[^>]+>','',block)).strip()
        m=re.fullmatch(r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday) (\d+) (September|October|November)',plain)
        if m:
            day=date(2026,{'September':9,'October':10,'November':11}[m[2]],int(m[1])).isoformat()
            continue
        if not day:
            continue
        for line in re.split(r'<br\s*/?>',block,flags=re.I):
            m=re.search(r'\b([A-D]\d)\s+<a\b[^>]*href="([^"]+/match/\d+[^"]*)"[^>]*>(.*?)</a>(.*)',line,re.S)
            if not m:
                continue
            label=' '.join(html.unescape(re.sub(r'<[^>]+>','',m[3])).split())
            score=re.fullmatch(r'(.+?) (\d+)\s*[-–]\s*(\d+) (.+)',label)
            fixture=re.fullmatch(r'(.+?) vs (.+)',label)
            if not score and not fixture:
                continue
            home,away=(score[1],score[4]) if score else (fixture[1],fixture[2])
            time=re.search(r'\((\d\d:\d\d)\)',m[4])
            parsed.append(dict(day=day,home=name(home),away=name(away),league='int.unl',group=m[1],
                               score=[int(score[2]),int(score[3])] if score else None,
                               kickoffCET=time[1] if time else '20:45',source=m[2],neutral=False))
    if len(parsed)<100:
        raise ValueError(f'Unexpected UEFA schedule size: {len(parsed)}')
    return parsed

def parse_results(payload,today):
    start=today.replace(year=today.year-3,day=min(today.day,28)).isoformat()
    end=today.isoformat()
    rows=[]
    for r in csv.DictReader(io.StringIO(payload)):
        if not start<=r['date']<end:
            continue
        tournament=r['tournament']
        if tournament not in CODES and tournament!='Friendly':
            continue
        try:
            score=[int(r['home_score']),int(r['away_score'])]
        except ValueError:
            continue
        # Qualification playoffs and tournament knockout scores can include extra time.
        # Train on friendlies and Nations League group-stage windows only.
        eligible=tournament=='Friendly' or (
            tournament=='UEFA Nations League' and int(r['date'][:4])%2==0 and 9<=int(r['date'][5:7])<=11)
        rows.append(dict(day=r['date'],home=name(r['home_team']),away=name(r['away_team']),
                         league=CODES.get(tournament,'int.friendly'),neutral=r['neutral']=='TRUE',
                         score=score,eligible=eligible))
    if len(rows)<500:
        raise ValueError('Incomplete international results feed')
    return rows

def refresh(today):
    for file, url, parser in [('international-fixtures.json',SCHEDULE,parse_schedule),
                              ('afcon-fixtures.json',CAF_SOURCE,parse_afcon),
                              ('international-results.json',RESULTS,lambda payload:parse_results(payload,today))]:
        try:
            rows=parser(get(url))
        except (OSError,ValueError) as exc:
            print(file,exc)
            continue
        path=ROOT/'data'/file
        if file=='afcon-fixtures.json' and path.exists():
            previous={(m['day'],m['home'],m['away']):m['score'] for m in json.loads(path.read_text())['rows']}
            for m in rows:
                m['score']=previous.get((m['day'],m['home'],m['away']))
        payload=dict(checkedAt=datetime.now(timezone.utc).isoformat(),rows=rows,source=url)
        path.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':'))+'\n')
        print(file,len(rows))

if __name__=='__main__':
    refresh(date.today())
