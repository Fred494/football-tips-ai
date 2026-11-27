"""Archive the official, season-end UEFA club coefficients with their availability dates."""
import json
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen
from european_data import club_key

ROOT=Path(__file__).resolve().parent

def refresh():
    path=ROOT/'data'/'uefa-coefficients.json'
    archive=json.loads(path.read_text()) if path.exists() else {'seasons':{}}
    now=datetime.now(timezone.utc)
    year=now.year-(now.month<7)
    for season in range(year-2,year+1):
        if str(season) in archive['seasons']:
            continue
        base=f'https://comp.uefa.com/v2/coefficients?coefficientRange=OVERALL&coefficientType=MEN_CLUB&language=EN&seasonYear={season}'
        def get(page):
            with urlopen(base+f'&page={page}',timeout=15) as response:
                return json.load(response)
        try:
            first=get(1)
            total=int(first['meta']['collection']['totalElements'])
            with ThreadPoolExecutor(max_workers=8) as pool:
                pages=[first,*pool.map(get,range(2,math.ceil(total/20)+1))]
            members=[m for page in pages for m in page['data']['members']]
            if len({m['member']['id'] for m in members})!=total:
                raise ValueError('Incomplete ranking archive')
            available=max(page['data']['lastUpdateDate'][:10] for page in pages)
            # A season-end ranking can only be used after it was finalized.
            available=max(available,f'{season}-07-01')
            clubs={}
            for entry in members:
                member=entry['member'];ranking=entry['overallRanking']
                row=dict(name=member['displayName'],points=ranking['totalValue'],
                         rank=ranking['position'],logo=member.get('bigLogoUrl') or member.get('logoUrl'))
                for field in ('displayName','displayNameShort','displayOfficialName','internationalName'):
                    if member.get(field):
                        clubs[club_key(member[field])]=row
            archive['seasons'][str(season)]=dict(available=available,source=base,clubs=clubs)
            print('UEFA coefficient archive',season,total,available,flush=True)
        except (OSError,ValueError,KeyError) as error:
            print('UEFA coefficient archive',season,str(error),flush=True)
    path.write_text(json.dumps(archive,ensure_ascii=False,separators=(',',':'))+'\n')

def load():
    path=ROOT/'data'/'uefa-coefficients.json'
    return json.loads(path.read_text()).get('seasons',{}) if path.exists() else {}

def coefficient_features(home,away,day,archive):
    import numpy as np
    eligible=[(season,data) for season,data in archive.items() if data['available']<day]
    if not eligible:
        return None
    season,data=max(eligible)
    h=data['clubs'].get(club_key(home));a=data['clubs'].get(club_key(away))
    if not h or not a:
        return None
    return [float(np.log1p(h['points'])-np.log1p(a['points'])),
            (a['rank']-h['rank'])/100.],dict(season=season,available=data['available'],source=data['source'],
                                           home=h,away=a)

if __name__=='__main__':
    refresh()
