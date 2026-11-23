"""Archive the original published 1X/X2 pick and settle it against a final score."""

import json
import os
from urllib.request import urlopen
from datetime import date, datetime
from zoneinfo import ZoneInfo

LISBON = ZoneInfo('Europe/Lisbon')


def load_history(path):
    if not path.exists():
        return {'updated': None, 'picks': []}
    return json.loads(path.read_text())


def load_published_history():
    """Recover the public archive even when the Actions cache is unavailable."""
    url = os.environ.get('PUBLISHED_HISTORY_URL')
    if not url and os.environ.get('GITHUB_REPOSITORY') == 'Fred494/football-tips-ai':
        url = 'https://fred494.github.io/football-tips-ai/history.json'
    if not url:
        return None
    try:
        with urlopen(url, timeout=12) as response:
            history = json.load(response)
        if not isinstance(history.get('picks'), list):
            raise ValueError('Missing published picks')
        return history
    except (OSError, ValueError) as error:
        print(f'Published history unavailable: {error}')
        return None


def merge_picks(*archives):
    picks = {}
    for archive in archives:
        for pick in archive:
            previous = picks.get(pick['id'])
            key = (pick['publishedAt'], pick['status'] == 'pending')
            if previous is None or key < (previous['publishedAt'], previous['status'] == 'pending'):
                picks[pick['id']] = pick
    return list(picks.values())


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
    # Correct provisional fixture dates using an unambiguous same-season match.
    candidates=set(scores)|{m['id'] for m in snapshot['matches']}
    fixture_details={m['id']:m for m in snapshot['matches']}
    for pick in picks.values():
        original=pick.get('fixtureId',pick['id'])
        if original in candidates:
            continue
        parts=original.split('|')
        if len(parts)!=5:
            continue
        code,season,day,home,away=parts
        matching=[]
        for candidate in candidates:
            fields=candidate.split('|')
            if len(fields)!=5:
                continue
            if (fields[:2]==[code,season] and fields[3:]==[home,away]
                    and abs((date.fromisoformat(day)-date.fromisoformat(fields[2])).days)<=7):
                matching.append(candidate)
        if len(matching)==1:
            replacement=matching[0]
            pick.setdefault('originalDay',pick['day'])
            pick['fixtureId']=replacement
            pick['day']=replacement.split('|')[2]
            if replacement in fixture_details:
                pick['kickoff']=fixture_details[replacement].get('kickoff')
    archived = {(pick.get('fixtureId', pick['id']), pick['market']) for pick in picks.values()}
    leagues = {league['code']: league['name'] for league in snapshot['leagues']}

    for match in snapshot['matches']:
        if not match.get('pick') or (match['id'], match['market']) in archived:
            continue
        pick_id = match['id'] if match['id'] not in picks else f"{match['id']}|{match['market']}"
        picks[pick_id] = {
            key: match[key] for key in ('day', 'home', 'away', 'league', 'market', 'prob')
        }
        picks[pick_id].update(
            id=pick_id,
            fixtureId=match['id'],
            kickoff=match.get('kickoff'),
            leagueName=leagues.get(match['league'], match['league']),
            publishedAt=snapshot['updated'],
            status='pending',
            exception=match['pick'] == 'exception',
            score=None,
        )

    for match_id, pick in picks.items():
        score = scores.get(pick.get('fixtureId', match_id))
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
