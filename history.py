"""Archive the original published 1X/X2 pick and settle it against a final score."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

LISBON = ZoneInfo('Europe/Lisbon')


def load_history(path):
    if not path.exists():
        return {'updated': None, 'picks': []}
    return json.loads(path.read_text())


def before_kickoff(match, publication):
    day = publication.astimezone(LISBON).date().isoformat()
    if match['day'] != day:
        return match['day'] > day
    kickoff = match.get('kickoff')
    if not kickoff:
        return False
    return publication < datetime.fromisoformat(
        f"{match['day']}T{kickoff}"
    ).replace(tzinfo=LISBON)


def update_history(history, snapshot, scores):
    picks = {pick['id']: dict(pick) for pick in history['picks']}
    publication = datetime.fromisoformat(snapshot['updated'])
    threshold = snapshot.get('pickMinimum', .75)
    leagues = {league['code']: league['name'] for league in snapshot['leagues']}

    for match in snapshot['matches']:
        probability = match.get('prob')
        if (match['id'] in picks or match.get('stale')
                or probability is None or probability <= threshold
                or match.get('market') not in ('1X', 'X2')
                or not before_kickoff(match, publication)):
            continue
        picks[match['id']] = {
            key: match[key] for key in ('id', 'day', 'home', 'away', 'league', 'market', 'prob')
        }
        picks[match['id']].update(
            leagueName=leagues.get(match['league'], match['league']),
            publishedAt=snapshot['updated'],
            status='pending',
            score=None,
        )

    for match_id, pick in picks.items():
        score = scores.get(match_id)
        if score is None:
            continue
        home, away = score
        correct = home >= away if pick['market'] == '1X' else away >= home
        pick.update(score=score, status='hit' if correct else 'miss')

    return {
        'updated': snapshot['updated'],
        'picks': sorted(picks.values(), key=lambda p: (p['day'], p['id']), reverse=True),
    }


def save_history(path, history):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(history, ensure_ascii=False, separators=(',', ':')) + '\n')
    temp.replace(path)
