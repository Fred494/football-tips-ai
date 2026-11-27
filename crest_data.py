"""Refresh club badges from ESPN team lists and match existing provider aliases."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen
from club_tables import CODES
from european_data import club_key

ROOT=Path(__file__).resolve().parent

def refresh():
    path=ROOT/'data'/'team-crests.json'
    previous=json.loads(path.read_text()) if path.exists() else {'teams':{}}
    def fetch(provider):
        try:
            with urlopen(f'https://site.api.espn.com/apis/site/v2/sports/soccer/{provider}/teams?limit=1000',timeout=12) as response:
                payload=json.load(response)
            rows=payload.get('sports',[{}])[0].get('leagues',[{}])[0].get('teams',[])
            teams=[]
            for row in rows:
                team=row['team']
                logo=next((r['href'] for r in team.get('logos',[]) if r.get('href','').startswith('https://a.espncdn.com/')),None)
                if logo:
                    teams.append(dict(names=[team[k] for k in ('displayName','shortDisplayName','name') if team.get(k)],logo=logo))
            return teams
        except (OSError,ValueError,KeyError,IndexError):
            return []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for teams in pool.map(fetch,sorted(set(CODES.values()))):
            for team in teams:
                for name in team['names']:
                    previous['teams'][club_key(name)]=team['logo']
    previous['updated']=datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(previous,ensure_ascii=False,separators=(',',':'))+'\n')
    print('Club badge identities',len(previous['teams']))

def apply_crests(snapshot):
    path=ROOT/'data'/'team-crests.json'
    known=json.loads(path.read_text()).get('teams',{}) if path.exists() else {}
    coefficient_file=ROOT/'data'/'uefa-coefficients.json'
    if coefficient_file.exists():
        for season in json.loads(coefficient_file.read_text()).get('seasons',{}).values():
            for name,team in season['clubs'].items():
                if team.get('logo'):
                    known.setdefault(name,team['logo'])
    for name,logo in snapshot.get('crests',{}).items():
        known.setdefault(club_key(name),logo)
    names=set()
    for league in snapshot['leagues']:
        if league.get('international'):
            continue
        for row in league.get('table',[]):
            names.add(row['team'])
        for group in league.get('displayTable',{}).get('groups',[]):
            for row in group['rows']:
                if row.get('logo'):
                    for name in [row['team'],*row.get('aliases',[])]:
                        if name:
                            known[club_key(name)]=row['logo']
                names.add(row['team'])
    for match in snapshot['matches']:
        if match.get('international'):
            continue
        names.update((match['home'],match['away']))
        for side in match.get('form',[]):
            for game in side:
                names.update((game['home'],game['away']))
    aliases={
        '1. FC Kaiserslautern':'Kaiserslautern','AE Kifisias':'Kifisia','AEK':'AEK Athens',
        'AEK Athen':'AEK Athens','Amedspor':'Ameds FK','Aris Saloniki':'Aris Thessaloniki',
        'Atlanta Utd':'Atlanta United','Braunschweig':'TSV Eintracht Braunschweig',
        'Eintracht Braunschweig':'TSV Eintracht Braunschweig','Brommapojkarna':'IF Brommapojkarna',
        'Buyuksehyr':'Istanbul Basaksehir','CD Castellón':'Castellon','CD Tenerife':'Tenerife',
        'Celta B':'Celta Fortuna','Clermont':'Clermont Foot','Corum':'Corum FK',
        'Deportivo La Coruña':'Deportivo','Dijon':'Dijon FCO','Dinamo Kiev':'Dynamo Kyiv',
        'Dresden':'Dynamo Dresden','Erzurumspor':'Erzurum BB','FC Porto B':'FC Porto',
        'Fortuna Düsseldorf':'Fortuna Dusseldorf','Goztep':'Goztepe','Halmstad':'Halmstads BK',
        'Hertha BSC':'Hertha Berlin','Karlsruhe':'Karlsruher','Kasımpaşa SK':'Kasimpasa',
        'Lausanne':'Lausanne Sports','Laval':'Stade Laval','Legia':'Legia Warsaw',
        'Levadeiakos':'Levadiakos','Los Angeles FC':'LAFC','Los Angeles Galaxy':'LA Galaxy',
        'New York Red Bulls':'Red Bull NY','Nurnberg':'1. FC Nurnberg','OFI Heraklion':'OFI Crete',
        'Olympiakos':'Olympiacos','Olympiakos Piraeus':'Olympiacos','Oviedo':'Real Oviedo',
        'Paphos FC':'Pafos','Rizespor':'Caykur Rizespor','Rodez':'Rodez Aveyron',
        'SD Eibar':'Eibar','SL Benfica B':'Benfica','Sabadell':'CD Sabadell',
        'Sociedad B':'Real Sociedad II','Sp Gijon':'Gijon','St Truiden':'Sint-Truidense',
        'St. Gilloise':'Union SG','Standard':'Standard Liege','UD Almería':'Almeria',
        'UD Las Palmas':'Las Palmas','União Torreense':'Torreense','Waregem':'Zulte Waregem',
        'Paksi SE':'Paks','Puskás FC':'Puskas Akademia','Wisla':'Wisla Krakow',
        'Zaglebie':'Zaglebie Lubin','Preußen Münster':'Preussen Munster',
    }
    for original,target in aliases.items():
        if club_key(target) in known:
            known[club_key(original)]=known[club_key(target)]
    for name in names:
        if club_key(name) in known:
            snapshot['crests'][name]=known[club_key(name)]
    snapshot['crestCoverage']=dict(teams=len(names),withLogo=sum(name in snapshot['crests'] for name in names),
                                  missing=sorted(name for name in names if name not in snapshot['crests']))

if __name__=='__main__':
    refresh()
