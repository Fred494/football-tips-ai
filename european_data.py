"""Refresh the three UEFA club league-phase schedules from official publications."""
import html
import json
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
SOURCES = {
    'uefa.cl': 'https://www.uefa.com/uefachampionsleague/news/02a8-2174c9e9019d-f909a77bd77a-1000--2026-27-champions-league-all-the-league-phase-fixtures-a/',
    'uefa.el': 'https://www.uefa.com/uefaeuropaleague/news/02a8-2174cafa5bb6-82bbc20c9b92-1000--2026-27-europa-league-all-the-league-phase-fixtures/',
    'uefa.ecl': 'https://www.uefa.com/uefaconferenceleague/news/02a8-2174cb200f25-b94693ddff4e-1000--2026-27-conference-league-league-phase-fixtures/',
}
# Explicit provider names for the same clubs. Other identities use exact normalized names.
ALIASES = {
    'Atlético de Madrid': 'Club Atlético de Madrid', 'Inter': 'FC Internazionale Milano',
    'Paris': 'Paris Saint-Germain FC', 'Paris Saint-Germain': 'Paris Saint-Germain FC',
    'Sporting CP': 'Sporting Clube de Portugal', 'Benfica': 'Sport Lisboa e Benfica',
    'Braga': 'Sporting Clube de Braga', 'Porto': 'FC Porto', 'Bayern München': 'FC Bayern München',
    'Leipzig': 'RB Leipzig', 'Leverkusen': 'Bayer 04 Leverkusen', 'Stuttgart': 'VfB Stuttgart',
    'Hoffenheim': 'TSG 1899 Hoffenheim', 'Como': 'Como 1907', 'Napoli': 'SSC Napoli',
    'Milan': 'AC Milan', 'Roma': 'AS Roma', 'Atalanta': 'Atalanta BC',
    'Feyenoord': 'Feyenoord Rotterdam', 'PSV Eindhoven': 'PSV', 'N.E.C. Nijmegen': 'NEC',
    'N.E.C.': 'NEC', 'AZ Alkmaar': 'AZ', 'Twente': "FC Twente '65",
    'Lens': 'Racing Club de Lens', 'Lyon': 'Olympique Lyonnais',
    'Marseille': 'Olympique de Marseille', 'Rennes': 'Stade Rennais FC 1901',
    'Celta': 'RC Celta de Vigo', 'Real Sociedad': 'Real Sociedad de Fútbol',
    'Real Betis': 'Real Betis Balompié', 'Sunderland': 'Sunderland AFC',
    'Club Brugge': 'Club Brugge KV', 'Union SG': 'Union St. Gilloise',
    'Galatasaray': 'Galatasaray SK', 'Fenerbahçe': 'Fenerbahçe SK',
    'Beşiktaş': 'Beşiktaş JK', 'AEK Athens': 'AEK Athens FC',
    'Olympiacos': 'Olympiacos FC', 'Panathinaikos': 'Panathinaikos FC',
}

ALIASES.update({
    'Atlético Madrid':'Club Atlético de Madrid', 'Internazionale':'FC Internazionale Milano',
    'Bayern Munich':'FC Bayern München', 'Slavia Prague':'Slavia Praha',
    'Celta Vigo':'RC Celta de Vigo', 'Dinamo Zagreb':'GNK Dinamo',
    'Bayer Leverkusen':'Bayer 04 Leverkusen', 'RB Salzburg':'Salzburg', 'LASK Linz':'LASK',
    "Hapoel Be'er":'Hapoel Beer-Sheva', 'Sparta Prague':'Sparta Praha',
    'NK Celje':'Celje', 'Sabah FK':'Sabah', 'Viking FK':'Viking',
    'CSU Craiova':'Universitatea Craiova', 'Iberia 1999':'Iberia Tbilisi',
    'AGF':'Aarhus', 'SK Brann':'Brann', "Inter D'Escaldes":'Inter Escaldes',
    'København':'Copenhagen', 'F.C. København':'Copenhagen', 'KAA Gent':'Gent',
    'Red Star Belgrade':'Crvena Zvezda', 'FC Twente':"FC Twente '65",
})
ESPN = {'uefa.cl':'uefa.champions','uefa.el':'uefa.europa','uefa.ecl':'uefa.europa.conf'}

def clean(value):
    return ' '.join(html.unescape(re.sub('<[^>]+>', ' ', value)).replace('\ufeff', '').split())

def club_key(team):
    team = ALIASES.get(clean(team), clean(team))
    team = team.replace('ø','o').replace('Ø','O').replace('ł','l').replace('Ł','L')
    team = unicodedata.normalize('NFKD', team).encode('ascii', 'ignore').decode().lower()
    team = re.sub(r'\b(fc|afc|cf|ac|sc|sk|jk|kv|bc|1907|1909|1913)\b', ' ', team)
    return re.sub(r'[^a-z0-9]', '', team)

def parse_schedule(page, code):
    rows = {}
    day = None
    round_number = None
    for block in re.findall(r'<(?:p|h[23])\b[^>]*>.*?</(?:p|h[23])>', page, re.S):
        text = clean(block)
        round_match = re.fullmatch(r'Matchday (\d+)', text)
        if round_match:
            round_number = int(round_match[1])
        for line in re.split(r'<br\s*/?>', block):
            text = clean(line)
            date_match = re.search(r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday) (\d{1,2} [A-Za-z]+ 20\d{2})', text)
            if date_match:
                day = datetime.strptime(date_match[2], '%d %B %Y').date().isoformat()
                continue
            if not day or not round_number:
                continue
            link = re.search(r'<a\b[^>]*href="([^"]+/match/\d+[^"]*)"[^>]*>(.*?)</a>', line, re.S)
            if not link:
                continue
            label = clean(link[2])
            score = re.fullmatch(r'(.+?) (\d+)\s*[-–]\s*(\d+) (.+)', label)
            fixture = re.fullmatch(r'(.+?) vs (.+)', label)
            if not score and not fixture:
                continue
            home, away = (score[1], score[4]) if score else (fixture[1], fixture[2])
            time_match = re.search(r'\((\d\d:\d\d)\)', text)
            record = dict(date=day, team1=home, team2=away,
                          score={'ft':[int(score[2]),int(score[3])]} if score else None,
                          kickoffCET=time_match[1] if time_match else '21:00',
                          round=round_number, source=link[1])
            rows[(day,club_key(home),club_key(away))] = record
    if len(rows) < 100:
        raise ValueError(f'{code}: incomplete official schedule ({len(rows)})')
    return sorted(rows.values(),key=lambda r:(r['date'],r['team1']))

def refresh_espn(code, previous):
    """Match ESPN events to the verified schedule before replacing any scores."""
    rows=[dict(row) for row in previous['matches']]
    today=datetime.now(timezone.utc).date()
    end=(today+timedelta(days=7)).isoformat()
    days=sorted({row['date'] for row in rows if row['date']<=end})
    if not days:
        raise ValueError('No scheduled dates to verify')

    def fetch_day(day):
        url=f"https://site.api.espn.com/apis/site/v2/sports/soccer/{ESPN[code]}/scoreboard?dates={day.replace('-','')}"
        with urlopen(url,timeout=15) as response:
            payload=json.load(response)
        expected=[row for row in rows if row['date']==day]
        matched=[]
        for event in payload.get('events',[]):
            competition=event.get('competitions',[{}])[0]
            teams={team['homeAway']:team for team in competition.get('competitors',[])}
            if not all(side in teams for side in ('home','away')):
                continue
            def keys(side):
                team=teams[side]['team']
                return {club_key(team[field]) for field in ('displayName','shortDisplayName','name') if team.get(field)}
            candidates=[row for row in expected if club_key(row['team1']) in keys('home')
                        and club_key(row['team2']) in keys('away')]
            if len(candidates)!=1:
                continue
            row=candidates[0]
            stamp=datetime.fromisoformat(event['date'].replace('Z','+00:00')).astimezone(ZoneInfo('Europe/Berlin'))
            row['date']=stamp.date().isoformat()
            row['kickoffCET']=stamp.strftime('%H:%M')
            status=competition.get('status',event.get('status',{})).get('type',{})
            if status.get('completed') and status.get('state')=='post':
                score=[int(teams[side]['score']) for side in ('home','away')]
                if min(score)<0:
                    raise ValueError('Invalid final score')
                row['score']={'ft':score}
            row['resultSource']=url
            matched.append(id(row))
        if len(set(matched))!=len(expected):
            missing=[row['team1']+' – '+row['team2'] for row in expected if id(row) not in matched]
            raise ValueError(f"{code} {day}: unmatched schedule entries {missing}")
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(fetch_day,days))
    return dict(previous,matches=rows,checkedAt=datetime.now(timezone.utc).isoformat(),
                verificationSource='ESPN scoreboard matched to the official UEFA schedule')


def refresh():
    def fetch(item):
        code, source = item
        path=ROOT/'data'/f'2026-27_{code}.json'
        try:
            with urlopen(source,timeout=20) as response:
                rows=parse_schedule(response.read().decode('utf-8'),code)
            payload=dict(matches=rows,checkedAt=datetime.now(timezone.utc).isoformat(),source=source)
        except (OSError,ValueError) as error:
            if not path.exists():
                return code,str(error)
            try:
                payload=refresh_espn(code,json.loads(path.read_text()))
            except (OSError,ValueError,KeyError,TypeError) as fallback_error:
                return code,f'UEFA: {error}; ESPN: {fallback_error}'
        temp=path.with_suffix('.tmp')
        temp.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':'))+'\n')
        temp.replace(path)
        return code,len(payload['matches'])
    with ThreadPoolExecutor(max_workers=3) as pool:
        print('UEFA club schedules:',list(pool.map(fetch,SOURCES.items())))

if __name__=='__main__':
    refresh()
