"""Import published club standings and their team crests for display."""
import json
from datetime import date
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / 'data' / 'club-tables.json'
CODES = dict(zip(
    'pt.1 es.1 es.2 en.1 en.2 fr.1 fr.2 nl.1 it.1 it.2 se.1 ch.1 us.1 dk.1 be.1 de.1 de.2 gr.1 tr.1 uefa.cl uefa.el uefa.ecl'.split(),
    'por.1 esp.1 esp.2 eng.1 eng.2 fra.1 fra.2 ned.1 ita.1 ita.2 swe.1 sui.1 usa.1 den.1 bel.1 ger.1 ger.2 gre.1 tur.1 uefa.champions uefa.europa uefa.europa.conf'.split()
))
FIELDS = dict(n='gamesPlayed', w='wins', d='ties', l='losses', gf='pointsFor',
              ga='pointsAgainst', gd='pointDifferential', pts='points')

def normalize(payload, year, season):
    if payload.get('season', {}).get('year') != year:
        return []
    groups = []
    for child in payload.get('children', []):
        rows = []
        for entry in child.get('standings', {}).get('entries', []):
            team = entry.get('team', {})
            stats = {s['name']: s.get('value') for s in entry.get('stats', [])}
            if not team.get('displayName') or any(stats.get(key) is None for key in FIELDS.values()):
                continue
            logo = next((x['href'] for x in team.get('logos', [])
                         if x.get('href', '').startswith('https://a.espncdn.com/')), None)
            rows.append(dict(team=team['displayName'], logo=logo, aliases=[team.get('shortDisplayName'),team.get('name')],
                             rank=stats.get('rank'), **{k:int(stats[v]) for k,v in FIELDS.items()}))
        if rows and any(r['n'] for r in rows):
            groups.append(dict(label=child.get('name','').strip(), rows=rows))
    return groups

def refresh():
    today = date.today()
    def fetch(item):
        code, espn = item
        annual = code in ('se.1','us.1')
        year = today.year if annual else today.year-(today.month<7)
        season = str(year) if annual else f'{year}-{(year+1)%100:02d}'
        url = f'https://site.api.espn.com/apis/v2/sports/soccer/{espn}/standings?season={year}'
        try:
            with urlopen(url, timeout=12) as response:
                groups=normalize(json.load(response),year,season)
            if groups:
                return code,dict(season=season,groups=groups,source=f'https://www.espn.com/soccer/standings/_/league/{espn}',checkedOn=today.isoformat())
        except (OSError, ValueError) as error:
            print(f'{code}: {error}')
        return code,None
    previous=json.loads(CACHE.read_text()) if CACHE.exists() else {}
    with ThreadPoolExecutor(max_workers=12) as pool:
        previous.update((code,table) for code,table in pool.map(fetch,CODES.items()) if table)
    CACHE.write_text(json.dumps(previous,ensure_ascii=False,separators=(',',':'))+'\n')
    print(f'Club tables available: {len(previous)}')

if __name__=='__main__':
    refresh()
