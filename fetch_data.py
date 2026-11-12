"""Fetch openfootball public-domain season files, retaining successful local copies."""
import concurrent.futures
import json
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

BASE = 'https://raw.githubusercontent.com/openfootball/football.json/master'
ROOT = Path(__file__).resolve().parent

def download(job):
    league, season = job
    name = f'{season}/{league}.json'
    path = ROOT / 'data' / f'{season}_{league}.json'
    try:
        with urllib.request.urlopen(f'{BASE}/{name}', timeout=15) as response:
            content = response.read()
        if not isinstance(json.loads(content).get('matches'), list):
            raise ValueError('Missing matches')
        path.write_bytes(content)
        return name, 'OK'
    except Exception as exc:
        return name, str(exc)

if __name__ == '__main__':
    today = date.today()
    year = today.year - (today.month < 7)
    leagues = json.loads((ROOT / 'leagues.json').read_text())
    jobs = [(code, str(y) if code in ('se.1', 'us.1') else f'{y}-{(y+1)%100:02d}')
            for code, _, _ in leagues for y in range(year-2, year+1)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        results = dict(pool.map(download, jobs))
    print(sum(status == 'OK' for status in results.values()), 'season files refreshed')
    (ROOT / 'data' / 'fetch-status.json').write_text(json.dumps({'checkedAt':datetime.now(timezone.utc).isoformat(), 'files':results}, indent=2))
