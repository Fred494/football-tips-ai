"""Refresh the three UEFA club league-phase schedules from official publications."""
import html
import json
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
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

def clean(value):
    return ' '.join(html.unescape(re.sub('<[^>]+>', ' ', value)).replace('\ufeff', '').split())

def club_key(team):
    team = ALIASES.get(clean(team), clean(team))
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

def refresh():
    def fetch(item):
        code, source = item
        try:
            with urlopen(source,timeout=20) as response:
                rows=parse_schedule(response.read().decode('utf-8'),code)
            payload=dict(matches=rows,checkedAt=datetime.now(timezone.utc).isoformat(),source=source)
            path=ROOT/'data'/f'2026-27_{code}.json'
            temp=path.with_suffix('.tmp')
            temp.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':'))+'\n')
            temp.replace(path)
            return code,len(rows)
        except (OSError,ValueError) as error:
            return code,str(error)
    with ThreadPoolExecutor(max_workers=3) as pool:
        print('UEFA club schedules:',list(pool.map(fetch,SOURCES.items())))

if __name__=='__main__':
    refresh()
