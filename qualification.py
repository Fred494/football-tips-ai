"""Conservative qualification bounds using scores available before matchday."""
HOSTS = {'Kenya', 'Uganda', 'Tanzania'}
RULES = {'int.afconq': (4, 6, 2), 'int.unl': (4, 6, 2)}

def group_status(code, teams, games, team):
    if code == 'int.afconq' and team in HOSTS:
        return 'qualified'
    if code not in RULES or (code == 'int.unl' and games[0]['group'][0] != 'A'):
        return 'unknown'
    size, total, places = RULES[code]
    if len(teams) != size or team not in teams:
        return 'unknown'
    excluded = teams & HOSTS if code == 'int.afconq' else set()
    places -= len(excluded)
    points = dict.fromkeys(teams, 0)
    played = dict.fromkeys(teams, 0)
    for m in games:
        h,a = m['home'],m['away']
        s,t = m['score']
        played[h] += 1
        played[a] += 1
        points[h] += 3 if s>t else int(s==t)
        points[a] += 3 if t>s else int(s==t)
    if max(played.values())>total:
        return 'unknown'
    maximum = {t:p+3*(total-played[t]) for t,p in points.items()}
    rivals = teams - excluded - {team}
    # Equality is unresolved: leave official tie-breaks to the competition.
    if sum(maximum[r]>=points[team] for r in rivals)<places:
        return 'qualified'
    if sum(points[r]>maximum[team] for r in rivals)>=places:
        return 'eliminated'
    return 'open'
