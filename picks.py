"""Shared publication policy for Top Picks and the settlement archive."""
from datetime import datetime, timedelta

from history import before_kickoff

MINIMUM = .85
EXCEPTION_MINIMUM = .80


def home_exception(stats, table, home, away):
    """Require a top-quarter host, bottom-quarter visitor and strong venue gap."""
    ranks = {row['team']: index for index, row in enumerate(table)}
    if len(table) < 8 or home not in ranks or away not in ranks:
        return False
    home_venue, away_venue = stats[2:4]
    quarter = len(table) // 4
    return (ranks[home] < quarter and ranks[away] >= len(table) - quarter
            and min(home_venue['n'], away_venue['n']) >= 5
            and home_venue['ppg'] >= 2.25 and away_venue['ppg'] <= 1.0)


def assign_picks(snapshot):
    publication = datetime.fromisoformat(snapshot['updated'])
    last_day = (publication.date() + timedelta(days=3)).isoformat()
    exceptions = set()
    for match in sorted(snapshot['matches'], key=lambda m: (-m.get('prob', 0), m['id'])):
        probability = match.get('prob')
        if (match.get('stale') or probability is None or match['day'] > last_day
                or not before_kickoff(match, publication)):
            continue
        if probability >= MINIMUM:
            match['pick'] = 'standard'
        elif (probability >= EXCEPTION_MINIMUM and match['market'] == '1X'
              and match['day'] not in exceptions and match.get('homeException')):
            match['pick'] = 'exception'
            exceptions.add(match['day'])
