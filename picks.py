"""Shared publication policy for Top Picks and the settlement archive."""
from datetime import datetime, timedelta

from history import before_kickoff
from scoreboard_data import key as club_key

MINIMUM = .875


def home_exception(stats, table, home, away):
    """Flag every top-five host facing a bottom-five visitor."""
    ranks = {club_key(row['team']): index for index, row in enumerate(table)}
    home,away=club_key(home),club_key(away)
    return (len(table)>=10 and home in ranks and away in ranks
            and ranks[home]<5 and ranks[away]>=len(table)-5)


def assign_picks(snapshot):
    publication = datetime.fromisoformat(snapshot['updated'])
    leagues={league['code']:league for league in snapshot['leagues']}
    last_day = (publication.date() + timedelta(days=3)).isoformat()
    for match in sorted(snapshot['matches'], key=lambda m: (-m.get('prob', 0), m['id'])):
        probability = match.get('prob')
        if (match.get('stale') or probability is None or match['day'] > last_day
                or not before_kickoff(match, publication)):
            continue
        league=leagues.get(match['league'],{})
        published=league.get('displayTable',{})
        groups=published.get('groups',[])
        table=groups[0]['rows'] if published.get('season')==match.get('season') and len(groups)==1 else match.get('table',[])
        risk=home_exception(None,table,match['home'],match['away'])
        if risk and not match.get('international'):
            match['pick'] = 'exception'
            if match.get('market')!='1X':
                match['why']=[]
            match['market'] = '1X'
            match['prob'] = float(1-match['breakdown'][2])
        elif probability >= MINIMUM:
            match['pick'] = 'standard'
