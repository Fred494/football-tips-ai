"""Load verified pre-match player snapshots, keyed by fixture ID and team."""
import json
from datetime import datetime, time, timedelta
from pathlib import Path

PLAYER_FEATURES = ('Available player form difference', 'Injury impact difference',
                   'Suspension impact difference')
STATUS = {'available', 'injured', 'suspended', 'doubtful', 'unknown'}

def load_players(root):
    path = Path(root) / 'data' / 'player_snapshots.json'
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError('Expected player snapshots keyed by fixture ID')
    return data

def for_match(snapshots, match, cutoff_day, timezone):
    cutoff = datetime.combine(cutoff_day, time.min, timezone)
    teams = snapshots.get(match['id'], {})
    verified = []
    for team in (match['home'], match['away']):
        entry = teams.get(team, {})
        try:
            observed = datetime.fromisoformat(entry['observedAt'])
            if observed.tzinfo is None or not cutoff-timedelta(hours=48) <= observed < cutoff:
                raise ValueError
            if not entry['source'] or not isinstance(entry['players'], list):
                raise ValueError
            players = {}
            for p in entry['players']:
                if not isinstance(p['name'],str) or not p['name'].strip() or p['status'] not in STATUS:
                    raise ValueError
                if not 0 <= p['minutesShare'] <= 1 or not 0 <= p['rating'] <= 10:
                    raise ValueError
                players[p['name']] = {k:p[k] for k in ('name','status','minutesShare','rating')}
            if len(players)<11:
                raise ValueError
        except (ValueError, KeyError, TypeError):
            verified.append(None)
            continue
        verified.append(dict(team=team,source=entry['source'],observedAt=entry['observedAt'],
                             players=list(players.values())))
    if any(entry is None for entry in verified):
        return None, verified
    if any(any(p['status'] in ('unknown','doubtful') for p in entry['players']) for entry in verified):
        return None, verified
    def impacts(entry):
        weighted = lambda status:sum(p['minutesShare']*p['rating'] for p in entry['players']
                                      if p['status']==status)
        return tuple(weighted(s) for s in ('available','injured','suspended'))
    a,b=map(impacts,verified)
    return [left-right for left,right in zip(a,b)],verified
