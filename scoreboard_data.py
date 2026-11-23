"""Refresh near-term domestic fixtures and final scores from ESPN scoreboards."""
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from club_tables import CODES
from european_data import club_key

ROOT=Path(__file__).resolve().parent
LISBON=ZoneInfo('Europe/Lisbon')
COMPETITIONS={code:provider for code,provider in CODES.items() if not code.startswith('uefa.')}
COMPETITIONS.update({'pt.2':'por.2','hu.1':'hun.1','pl.1':'pol.1'})
ALIASES={
    'Alavés':'Deportivo Alavés', 'Deportivo':'RC Deportivo La Coruña', 'Levante':'Levante UD',
    'Espanyol':'RCD Espanyol de Barcelona', 'Celta Vigo':'RC Celta de Vigo',
    'Real Sociedad':'Real Sociedad de Fútbol', 'Rayo Vallecano':'Rayo Vallecano de Madrid',
    'Sporting CP':'Sporting Clube de Portugal', 'Benfica':'Sport Lisboa e Benfica',
    'Braga':'Sporting Clube de Braga', 'Estoril':'GD Estoril Praia', 'Santa Clara':'CD Santa Clara',
    'Nacional':'CD Nacional', 'Maritimo':'CS Marítimo',
    'Mainz':'1. FSV Mainz 05', 'Cologne':'1. FC Köln', 'FC Cologne':'1. FC Köln',
    'Werder Bremen':'SV Werder Bremen', 'Schalke 04':'FC Schalke 04',
    'PSV Eindhoven':'PSV', 'Telstar':'Telstar 1963', 'Excelsior':'SBV Excelsior',
    'Willem II':'Willem II Tilburg', 'Feyenoord':'Feyenoord Rotterdam',
    'Heerenveen':'SC Heerenveen','NEC Nijmegen':'NEC',
    'Stade Rennais':'Stade Rennais FC 1901','Strasbourg':'RC Strasbourg Alsace',
    'Lens':'Racing Club de Lens', 'Brest':'Stade Brestois 29',
    'Angers':'Angers SCO', 'Troyes':'ES Troyes AC', 'Monaco':'AS Monaco FC',
    'Fiorentina':'ACF Fiorentina', 'Bologna':'Bologna FC 1909', 'Napoli':'SSC Napoli',
    'Lazio':'SS Lazio', 'Genoa':'Genoa CFC', 'Parma':'Parma Calcio 1913',
    'Frosinone':'Frosinone Calcio','Sassuolo':'US Sassuolo Calcio',
    'Venezia':'Venezia FC','Lecce':'US Lecce','Udinese':'Udinese Calcio',
    'Hamburg SV':'Hamburger SV','Hannover 96':'Hannover 96',
}

def key(name):
    return club_key(ALIASES.get(name,name))

def normalize_events(payload, code, season, known):
    names=defaultdict(set)
    for match in known:
        for field in ('home','away'):
            names[key(match[field])].add(match[field])
    canonical_names={team for choices in names.values() for team in choices}
    output=[]
    for event in payload.get('events',[]):
        competitions=event.get('competitions',[])
        if len(competitions)!=1:
            continue
        competition=competitions[0]
        competitors={r.get('homeAway'):r for r in competition.get('competitors',[])}
        if not all(side in competitors for side in ('home','away')):
            continue
        stamp=datetime.fromisoformat(event['date'].replace('Z','+00:00')).astimezone(LISBON)
        day=stamp.date().isoformat()
        resolved={}
        for side in ('home','away'):
            team=competitors[side]['team']
            choices=set()
            for field in ('displayName','shortDisplayName','name'):
                if team.get(field):
                    choices.update(names.get(key(team[field]),set()))
            preferred=ALIASES.get(team.get('displayName'))
            if preferred in choices:
                resolved[side]=preferred
            elif len(choices)==1:
                resolved[side]=next(iter(choices))
            elif not choices:
                resolved[side]=team['displayName']
        if len(resolved)!=2 or resolved['home']==resolved['away']:
            continue
        # A single known side and date can disambiguate a provider abbreviation.
        same_day=[m for m in known if m['day']==day]
        candidates=[m for m in same_day if
                    m['home']==resolved['home'] or m['away']==resolved['away']]
        if len(candidates)==1:
            candidate=candidates[0]
            if any(resolved[side]!=candidate[side] and resolved[side] in canonical_names
                   for side in ('home','away')):
                continue
            resolved={side:candidate[side] for side in ('home','away')}
        elif candidates and not any(all(m[side]==resolved[side] for side in ('home','away')) for m in candidates):
            continue
        match_status=competition.get('status',event.get('status',{}))
        status=match_status.get('type',{})
        if status.get('state') not in ('pre','in','post'):
            continue
        score=None
        extra_time=(int(match_status.get('period',2))>2 or
                    status.get('shortDetail') in ('AET','ET','PEN') or
                    'PEN' in status.get('name','') or 'EXTRA' in status.get('name',''))
        if status.get('state')=='post' and status.get('completed') and not extra_time:
            score=[int(competitors[side]['score']) for side in ('home','away')]
            if min(score)<0:
                continue
        home,away=resolved['home'],resolved['away']
        output.append(dict(id='|'.join((code,season,day,home,away)),day=day,home=home,away=away,
                           season=season,league=code,score=score,kickoff=stamp.strftime('%H:%M'),
                           providerId=event['id'],source='https://www.espn.com/soccer/match/_/gameId/'+event['id'],
                           round=None))
    return output

def refresh_nationals(today):
    from international_data import name
    sources=[('international-fixtures.json','uefa.nations'),('afcon-fixtures.json','caf.nations_qual')]
    for filename,provider in sources:
        path=ROOT/'data'/filename
        if not path.exists():
            continue
        payload=json.loads(path.read_text())
        days=sorted({r['day'] for r in payload['rows']
                     if (today-timedelta(days=14)).isoformat()<=r['day']<=(today+timedelta(days=3)).isoformat()})
        verified=True
        for day in days:
            url=f"https://site.api.espn.com/apis/site/v2/sports/soccer/{provider}/scoreboard?dates={day.replace('-','')}"
            try:
                with urlopen(url,timeout=12) as response:
                    feed=json.load(response)
                expected=[r for r in payload['rows'] if r['day']==day]
                known=[dict(r,day=r['day'],home=name(r['home']),away=name(r['away'])) for r in expected]
                events=normalize_events(feed,expected[0]['league'],'2026-27',known)
                mapped={(row['home'],row['away']):row for row in events}
                for row in expected:
                    update=mapped.get((name(row['home']),name(row['away'])))
                    if not update:
                        verified=False
                        continue
                    if update['score'] is not None:
                        row['score']=update['score']
                        row['resultSource']=url
                if len(mapped)<len(expected):
                    verified=False
            except (OSError,ValueError,KeyError,TypeError) as error:
                verified=False
                print(filename,day,str(error))
        if days and verified:
            payload['checkedAt']=datetime.now(timezone.utc).isoformat()
        temp=path.with_suffix('.tmp')
        temp.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':'))+'\n')
        temp.replace(path)
        print(filename,'scoreboard reconciliation complete')


def refresh():
    from build import read_data
    leagues={league['code']:league for league in read_data()}
    today=datetime.now(LISBON).date()
    days=[(today+timedelta(days=i)).isoformat() for i in range(-7,4)]
    checked=datetime.now(timezone.utc).isoformat()
    known={code:[m for rows in league['seasons'].values() for m in rows]
           for code,league in leagues.items()}
    season_year=today.year-(today.month<7)

    def fetch(job):
        code,day=job
        season=str(today.year) if code in ('se.1','us.1') else f'{season_year}-{(season_year+1)%100:02d}'
        url=f"https://site.api.espn.com/apis/site/v2/sports/soccer/{COMPETITIONS[code]}/scoreboard?dates={day.replace('-','')}"
        try:
            with urlopen(url,timeout=12) as response:
                payload=json.load(response)
            if not isinstance(payload.get('events'),list):
                raise ValueError('Missing events')
            rows=normalize_events(payload,code,season,known.get(code,[]))
            expected=[m for m in known.get(code,[]) if m['day']==day and m['score'] is None]
            covered={(m['home'],m['away']) for m in rows}
            missing=[m for m in expected if (m['home'],m['away']) not in covered]
            if missing:
                return code,day,rows,f'{len(missing)} known fixtures missing from scoreboard'
            return code,day,rows,None
        except (OSError,ValueError,KeyError,TypeError) as error:
            return code,day,[],str(error)

    path=ROOT/'data'/'scoreboard.json'
    previous=json.loads(path.read_text()) if path.exists() else {'leagues':{}}
    by_code=defaultdict(list)
    with ThreadPoolExecutor(max_workers=12) as pool:
        for code,day,rows,error in pool.map(fetch,[(c,d) for c in COMPETITIONS for d in days]):
            by_code[code].append((day,rows,error))
    for code,results in by_code.items():
        entry=previous['leagues'].get(code,{'matches':[],'checkedDays':{}})
        records={m['id']:m for m in entry['matches']}
        for day,rows,error in results:
            if not error:
                entry['checkedDays'][day]=checked
            for row in rows:
                records={identity:record for identity,record in records.items()
                         if record.get('providerId')!=row['providerId'] or identity==row['id']}
                prior=records.get(row['id'])
                if prior and prior['score'] is not None and row['score'] is None:
                    row['score']=prior['score']
                records[row['id']]=row
        entry['matches']=list(records.values())
        previous['leagues'][code]=entry
        print(code,len(records),'scoreboard matches;',sum(error is not None for _,_,error in results),'failed dates')
    refresh_nationals(today)
    previous['updated']=checked
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(previous,ensure_ascii=False,separators=(',',':'))+'\n')
    temp.replace(path)

if __name__=='__main__':
    refresh()
