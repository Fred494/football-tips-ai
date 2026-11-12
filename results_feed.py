"""Fetch and normalize score-only results from Football-Data.co.uk."""
import csv
import io
import json
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

CODES = dict(zip('en.1 en.2 de.1 de.2 es.1 es.2 fr.1 fr.2 it.1 it.2 nl.1 pt.1 be.1 gr.1 tr.1'.split(),
                 'E0 E1 D1 D2 SP1 SP2 F1 F2 I1 I2 N1 P1 B1 G1 T1'.split()))
ROOT = Path(__file__).resolve().parent

def fetch(code, year):
    div = CODES[code]
    url = f'https://www.football-data.co.uk/mmz4281/{year%100:02d}{(year+1)%100:02d}/{div}.csv'
    path = ROOT/'data'/f'csv_{year}-{(year+1)%100:02d}_{code}.json'
    try:
        with urllib.request.urlopen(url, timeout=18) as response:
            reader = csv.DictReader(io.StringIO(response.read().decode('utf-8-sig', errors='replace')))
        results = []
        for r in reader:
            try:
                day = datetime.strptime(r['Date'],'%d/%m/%Y').date().isoformat()
                score = [int(r['FTHG']), int(r['FTAG'])]
                if r['HomeTeam'] and r['AwayTeam'] and min(score)>=0:
                    results.append(dict(day=day,home=r['HomeTeam'],away=r['AwayTeam'],score=score))
            except (KeyError, TypeError, ValueError):
                continue
        if results:
            path.write_text(json.dumps(results))
        return code, len(results)
    except (OSError, ValueError) as exc:
        return code, str(exc)

def refresh(year):
    with ThreadPoolExecutor(max_workers=15) as pool:
        print('Score feed:',list(pool.map(lambda code:fetch(code,year), CODES)))

def merge(rows, results, code, season):
    """Match provider aliases through unique shared date and score observations."""
    index = defaultdict(list)
    for m in rows:
        if m['score'] is not None:
            index[(m['day'], tuple(m['score']))].append(m)
    votes = defaultdict(lambda: defaultdict(int))
    for r in results:
        same = index[(r['day'],tuple(r['score']))]
        if len(same)==1:
            for side in ('home','away'):
                votes[r[side]][same[0][side]] += 1
    aliases = {}
    for team, choices in votes.items():
        ranked = sorted(choices.items(),key=lambda x:-x[1])
        if ranked[0][1]>=2 and (len(ranked)==1 or ranked[0][1]>ranked[1][1]*2):
            aliases[team]=ranked[0][0]
    names={r[side] for r in results for side in ('home','away')}
    # A one-to-one mapping is mandatory for a combined source.
    if rows and (not names.issubset(aliases) or len(set(aliases.values()))!=len(aliases)):
        return rows
    replaced=set()
    for r in results:
        h,a = (aliases.get(r[side],r[side]) for side in ('home','away'))
        replaced.add((h,a))
    combined=[r for r in rows if (r['home'],r['away']) not in replaced]
    for r in results:
        h,a=(aliases.get(r[side],r[side]) for side in ('home','away'))
        combined.append(dict(r,id='|'.join((code,season,r['day'],h,a)),home=h,away=a,
                             season=season,league=code,round=None))
    return sorted(combined,key=lambda r:r['day'])

if __name__=='__main__':
    today=date.today()
    refresh(today.year-(today.month<7))
