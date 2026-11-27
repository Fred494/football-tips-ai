"""Train a separate 90-minute double-chance model for national teams."""
import json
from collections import defaultdict
from datetime import datetime, timedelta

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from model_benchmarks import EloGoals, FORM_WINDOW, ModelBlend, recent_strength, select_forecast_model
from sklearn.linear_model import LogisticRegression

from international_data import CODES, ROOT
from window import history_start
from qualification import group_status

FEATURES=['National team Elo advantage','Recent points adjusted for opponent Elo',
          'Recent goal difference advantage','Home venue',
          'Home eliminated','Away eliminated','Home venue points per game',
          'Away venue points per game','Unbeaten rate advantage','Recent opponent strength',
          'Home and away rest difference']
QUALIFIED_WIN_PENALTY = .05

def adjust_qualification(probabilities, statuses, penalty=QUALIFIED_WIN_PENALTY):
    """Lower each qualified side's win probability and preserve total probability."""
    adjusted = probabilities.copy()
    winners = [column for column, status in zip((0, 2), statuses) if status == 'qualified']
    for winner in winners:
        removed = probabilities[..., winner] * penalty
        adjusted[..., winner] -= removed
        if len(winners) == 2:
            adjusted[..., 1] += removed
        else:
            adjusted[..., 1] += removed / 2
            adjusted[..., 2-winner] += removed / 2
    return adjusted


def load(file):
    path=ROOT/'data'/file
    return json.loads(path.read_text()) if path.exists() else {}

def predict_internationals(today, timezone, threshold, summary, measure, standings):
    history=load('international-results.json')
    schedules={'int.unl':load('international-fixtures.json'),'int.afconq':load('afcon-fixtures.json')}
    now=today.isoformat()
    horizon=(today+timedelta(days=30)).isoformat()
    verified={(r['day'],r['home'],r['away']):r for schedule in schedules.values() for r in schedule.get('rows',[])}
    group_teams=defaultdict(set)
    group_scores=defaultdict(list)
    for m in verified.values():
        group_teams[(m['league'],m['group'])].update((m['home'],m['away']))
    recent=defaultdict(list)
    opponent_history=defaultdict(list)
    elo=defaultdict(lambda:1500.)
    groups=defaultdict(lambda:defaultdict(list))
    rows={}
    for r in history.get('rows',[]):
        if r['eligible']:
            rows[(r['day'],r['home'],r['away'])]=r
    for r in history.get('rows',[]):
        key=(r['day'],r['home'],r['away'])
        if key in verified and verified[key]['league']==r['league'] and verified[key]['score'] is None:
            verified[key]['score']=r['score']
    rows.update(verified)
    rows={key:row for key,row in rows.items() if row['day']>=history_start(today).isoformat()}
    batches=defaultdict(list)
    for r in rows.values():
        if r['day']<=horizon:
            batches[r['day']].append(r)
    train=[]
    fixtures=[]
    checked={code:schedule.get('checkedAt') for code,schedule in schedules.items()}
    fresh={code:bool(stamp and datetime.now(timezone)-datetime.fromisoformat(stamp)<=timedelta(hours=48))
           for code,stamp in checked.items()}
    unresolved={(r['league'],t) for r in verified.values() if r['score'] is None and r['day']<now for t in (r['home'],r['away'])}
    for day, batch in sorted(batches.items()):
        prior_elo={t:elo[t] for m in batch for t in (m['home'],m['away'])}
        for m in batch:
            h,a=m['home'],m['away']
            hr,ar=[summary(recent[t][-FORM_WINDOW:],t) for t in (h,a)]
            if min(hr['n'],ar['n'])<5:
                continue
            home_form, home_opponents = recent_strength(h, recent[h], opponent_history[h])
            away_form, away_opponents = recent_strength(a, recent[a], opponent_history[a])
            hv=summary([r for r in recent[h] if r['home']==h and not r['neutral']][-FORM_WINDOW:],h)
            av=summary([r for r in recent[a] if r['away']==a and not r['neutral']][-FORM_WINDOW:],a)
            x=[elo[h]-elo[a],home_form-away_form,hr['gd']/hr['n']-ar['gd']/ar['n'],int(not m['neutral'])]
            key=(m['league'],m.get('group'))
            group_games=group_scores[key]
            statuses=[group_status(m['league'],group_teams[key],group_games,t)
                      if m.get('group') and group_games else 'unknown' for t in (h,a)]
            x.extend(int(status=='eliminated') for status in statuses)
            def rest(team):
                return min(60, (datetime.fromisoformat(day) - datetime.fromisoformat(recent[team][-1]['day'])).days)
            x.extend([hv['ppg'] if hv['n'] and not m['neutral'] else 1.35,
                      av['ppg'] if av['n'] and not m['neutral'] else 1.35,
                      (hr['w']+hr['d'])/hr['n']-(ar['w']+ar['d'])/ar['n'],
                      home_opponents-away_opponents,rest(h)-rest(a)])
            if m['score'] is not None and day<now:
                s,t=m['score']
                train.append((day,x,0 if s>t else 1 if s==t else 2,m['league'],statuses,m['score']))
            if m['score'] is None and day>=now:
                code=m['league']
                group=groups[(code,m['group'])]
                hs,as_=summary(group[h],h),summary(group[a],a)
                if 'kickoffUTC' in m:
                    from datetime import timezone as utc_zone
                    kickoff=datetime.fromisoformat(day+'T'+m['kickoffUTC']).replace(tzinfo=utc_zone.utc).astimezone(timezone).strftime('%H:%M')
                else:
                    kickoff=(datetime.fromisoformat(day+'T'+m['kickoffCET'])-timedelta(hours=1)).strftime('%H:%M')
                if datetime.fromisoformat(day+'T'+kickoff).replace(tzinfo=timezone)<=datetime.now(timezone):
                    continue
                fixtures.append(dict(**m,id=f"{code}|2026-27|{day}|{h}|{a}",x=x,season='2026–27 · Group '+m['group'],
                                     qualification=dict(zip(('home','away'),statuses)),kickoff=kickoff,stale=not fresh[code] or (code,h) in unresolved or (code,a) in unresolved,
                                     stats=[hs,as_,hv,av,hr,ar],table=standings(group),
                                     form=[recent[t][-FORM_WINDOW:][::-1] for t in (h,a)],
                                     long=[summary(recent[t][-10:],t) for t in (h,a)],
                                     h2h=[r for r in recent[h] if a in (r['home'],r['away'])][-5:][::-1],
                                     players=[None,None],playersUsed=False,international=True))
        for m in batch:
            if m['score'] is None or day>=now:
                continue
            h,a=m['home'],m['away']
            s,t=m['score']
            expected=1/(1+10**((elo[a]-elo[h]-(0 if m['neutral'] else 65))/400))
            delta=24*((1 if s>t else .5 if s==t else 0)-expected)
            elo[h]+=delta
            elo[a]-=delta
            opponent_history[h].append(prior_elo[a])
            opponent_history[a].append(prior_elo[h])
            if 'group' in m:
                group_scores[(m['league'],m['group'])].append(m)
            for team in (h,a):
                recent[team].append(m)
                if 'group' in m:
                    groups[(m['league'],m['group'])][team].append(m)
    evaluation=None
    if len(train)>=300:
        days=sorted({r[0] for r in train})
        first,last=days[int(.65*len(days))],days[int(.8*len(days))]
        split=[[r for r in train if pred(r[0])] for pred in
               (lambda d:d<first,lambda d:first<=d<last,lambda d:d>=last)]
        def xy(rows):
            return np.array([r[1] for r in rows]),np.array([r[2] for r in rows])
        xt,yt=xy(split[0]); xv,yv=xy(split[1]); xe,ye=xy(split[2])
        def apply_penalty(probs, records, penalty=QUALIFIED_WIN_PENALTY):
            return np.array([adjust_qualification(prob, record[4], penalty)
                             for prob, record in zip(probs, records)])

        candidates=[]
        for name, model in [
                ('Logistic regression',LogisticRegression(max_iter=1500)),
                ('Gradient boosted trees',HistGradientBoostingClassifier(max_iter=85,random_state=42)),
                ('Elo + Poisson',EloGoals(neutral_index=3)),
                ('Elo + Dixon–Coles',EloGoals(correction=True,neutral_index=3))]:
            model.fit(xt,[r[5] for r in split[0]] if isinstance(model,EloGoals) else yt)
            candidates.append((name,model))
        fitted=dict(candidates)
        candidates.append(('Logistic + Elo Poisson blend',ModelBlend(
            fitted['Logistic regression'],fitted['Elo + Poisson'])))
        validation_codes=np.array([r[3] for r in split[1]])
        test_codes=np.array([r[3] for r in split[2]])

        def adjust_validation(probabilities, mask):
            return apply_penalty(probabilities,[r for r,included in zip(split[1],mask) if included])

        name,model,calibration,incumbent,baselines=select_forecast_model(
            candidates,xv,yv,validation_codes,np.array([r[0] for r in split[1]]),adjust_validation)
        incumbent_name,incumbent_model,incumbent_calibration=incumbent
        raw=calibration.predict(model.predict_proba(xe),test_codes)
        p=apply_penalty(raw,split[2])
        q=np.stack((1-p[:,2],1-p[:,0]),axis=1)
        best=q.argmax(axis=1)
        eligible=q.max(axis=1)>=threshold
        hit=np.where(best==0,ye!=2,ye!=0)
        evaluation=dict(**measure(p,ye),name=name,
                        calibration=calibration.method,calibratedLeagues=sorted(calibration.offsets),
                        incumbent=dict(name=incumbent_name,**measure(apply_penalty(
                            incumbent_calibration.predict(incumbent_model.predict_proba(xe),test_codes),split[2]),ye)),
                        models=[dict(name=label,**measure(apply_penalty(
                            calibrator.predict(candidate.predict_proba(xe),test_codes),split[2]),ye))
                                for label,(_,candidate,calibrator) in baselines.items()],
                        train=len(yt),validation=len(yv),above=int(eligible.sum()),
                        hitAbove=float(hit[eligible].mean()) if eligible.any() else None,
                        start=split[2][0][0],end=split[2][-1][0])
        evaluation['leagues']={}
        for code in CODES.values():
            mask=np.array([r[3]==code for r in split[2]])
            if mask.any():
                evaluation['leagues'][code]=measure(p[mask],ye[mask])
        evaluation['holdoutLeagues']=evaluation['leagues']
        mask=np.array([tuple(r[4]) in (('qualified','open'),('open','qualified')) for r in split[2]])
        evaluation['qualification']=[]
        if mask.any():
            qualified_win=np.array([r[4][0]=='qualified' and r[2]==0 or r[4][1]=='qualified' and r[2]==2
                                    for r, included in zip(split[2],mask) if included])
            columns=np.array([0 if r[4][0]=='qualified' else 2 for r, included in zip(split[2],mask) if included])
            for penalty in (0., .05, .10):
                adjusted=apply_penalty(raw,split[2],penalty)[mask]
                win=adjusted[np.arange(len(columns)),columns]
                evaluation['qualification'].append(dict(
                    penalty=penalty, winExpected=float(win.mean()), winObserved=float(qualified_win.mean()),
                    winBrier=float(((win-qualified_win)**2).mean()), **measure(adjusted,ye[mask])))
        median=np.median(xt,axis=0)
        for m in fixtures:
            x=np.array(m['x'])
            statuses=[m['qualification'][side] for side in ('home','away')]
            base_probs=calibration.predict(model.predict_proba(x[None,:]),np.array([m['league']]))[0]
            probs=adjust_qualification(base_probs,statuses)
            m['qualificationWinChange']=dict(home=float(probs[0]-base_probs[0]),
                                             away=float(probs[2]-base_probs[2]))

            excluded=2 if probs[2]<=probs[0] else 0
            x_alt=np.repeat(x[None,:],len(x),axis=0)
            np.fill_diagonal(x_alt,median)
            alt=adjust_qualification(
                calibration.predict(model.predict_proba(x_alt),np.repeat(m['league'],len(x))),statuses)
            m.update(prob=float(1-probs[excluded]),market='1X' if excluded==2 else 'X2',
                     breakdown=probs.tolist(),why=sorted([
                         dict(name=k,value=float(x[i]),delta=float(alt[i,excluded]-probs[excluded]))
                         for i,k in enumerate(FEATURES)],key=lambda e:abs(e['delta']),reverse=True)[:3])
    for m in fixtures:
        m.pop('x')
    leagues=[]
    for label,code in CODES.items():
        completed={ (r['day'],r['home'],r['away']) for r in history.get('rows',[])
                   if r['league']==code and r['day']<now}
        completed.update(k for k,r in verified.items() if r['league']==code and r['score'] is not None and r['day']<now)
        upcoming=sum(m['league']==code for m in fixtures)
        leagues.append(dict(code=code,country='International',name=label,priority=code in {'int.unl','int.euro','int.wc'},
                            completed=len(completed),upcoming=upcoming,table=[],seasons=[],resultsFeed=[],
                            latest=max((r[0] for r in completed),default=None),unresolved=0,
                            fixturesChecked=checked.get(code),
                            fixtureStatus=('Schedule checked' if fresh[code] else 'Schedule check overdue')
                            if code in schedules else 'Historical results only · No active fixture feed',
                            international=True,tables=[dict(label='Group '+label,rows=standings(group)) for (comp,label),group in sorted(groups.items()) if comp==code],
                            recentResults=sorted([r for r in verified.values() if r['league']==code and r['score'] is not None and r['day']<=now],key=lambda r:r['day'],reverse=True)[:24]))
    scores={f"{r['league']}|2026-27|{r['day']}|{r['home']}|{r['away']}":r['score']
            for r in verified.values() if r['score'] is not None and r['day']<=now}
    return leagues,fixtures,evaluation,scores
