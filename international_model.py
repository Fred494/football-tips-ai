"""Train a separate 90-minute double-chance model for national teams."""
import json
from collections import defaultdict
from datetime import datetime, timedelta

import numpy as np
from scipy.optimize import minimize_scalar
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss

from international_data import CODES, ROOT

FEATURES=['National team Elo advantage','Recent points per game advantage',
          'Recent goal difference advantage','Home venue']

def load(file):
    path=ROOT/'data'/file
    return json.loads(path.read_text()) if path.exists() else {}

def predict_internationals(today, timezone, threshold, summary, predict, measure, standings):
    history=load('international-results.json')
    schedules={'int.unl':load('international-fixtures.json'),'int.afconq':load('afcon-fixtures.json')}
    now=today.isoformat()
    horizon=(today+timedelta(days=30)).isoformat()
    verified={(r['day'],r['home'],r['away']):r for schedule in schedules.values() for r in schedule.get('rows',[])}
    recent=defaultdict(list)
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
        for m in batch:
            h,a=m['home'],m['away']
            hr,ar=summary(recent[h][-5:],h),summary(recent[a][-5:],a)
            if min(hr['n'],ar['n'])<3:
                continue
            x=[elo[h]-elo[a],hr['ppg']-ar['ppg'],hr['gd']/hr['n']-ar['gd']/ar['n'],int(not m['neutral'])]
            if m['score'] is not None and day<now:
                s,t=m['score']
                train.append((day,x,0 if s>t else 1 if s==t else 2,m['league']))
            if m['score'] is None and day>=now:
                code=m['league']
                group=groups[(code,m['group'])]
                hs,as_=summary(group[h],h),summary(group[a],a)
                hv=summary([r for r in recent[h] if r['home']==h and not r['neutral']],h)
                av=summary([r for r in recent[a] if r['away']==a and not r['neutral']],a)
                if 'kickoffUTC' in m:
                    from datetime import timezone as utc_zone
                    kickoff=datetime.fromisoformat(day+'T'+m['kickoffUTC']).replace(tzinfo=utc_zone.utc).astimezone(timezone).strftime('%H:%M')
                else:
                    kickoff=(datetime.fromisoformat(day+'T'+m['kickoffCET'])-timedelta(hours=1)).strftime('%H:%M')
                if datetime.fromisoformat(day+'T'+kickoff).replace(tzinfo=timezone)<=datetime.now(timezone):
                    continue
                fixtures.append(dict(**m,id=f"{code}|2026-27|{day}|{h}|{a}",x=x,season='2026–27 · Group '+m['group'],
                                     kickoff=kickoff,stale=not fresh[code] or (code,h) in unresolved or (code,a) in unresolved,
                                     stats=[hs,as_,hv,av,hr,ar],table=standings(group),
                                     form=[recent[t][-5:][::-1] for t in (h,a)],
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
        model=LogisticRegression(max_iter=1000).fit(xt,yt)
        temp=minimize_scalar(lambda t:log_loss(yv,predict(model,xv,t),labels=[0,1,2]),
                             bounds=(.4,4),method='bounded').x
        p=predict(model,xe,temp)
        q=np.stack((1-p[:,2],1-p[:,0]),axis=1)
        best=q.argmax(axis=1)
        eligible=q.max(axis=1)>threshold
        hit=np.where(best==0,ye!=2,ye!=0)
        evaluation=dict(**measure(p,ye),train=len(yt),validation=len(yv),above=int(eligible.sum()),
                        hitAbove=float(hit[eligible].mean()) if eligible.any() else None,
                        start=split[2][0][0],end=split[2][-1][0])
        nations=np.array([r[3]=='int.unl' for r in split[2]])
        evaluation['nationsLeague']=measure(p[nations],ye[nations]) if nations.any() else None
        median=np.median(xt,axis=0)
        for m in fixtures:
            x=np.array(m['x'])
            probs=predict(model,x[None,:],temp)[0]
            excluded=2 if probs[2]<=probs[0] else 0
            x_alt=np.repeat(x[None,:],len(x),axis=0)
            np.fill_diagonal(x_alt,median)
            alt=predict(model,x_alt,temp)
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
    return leagues,fixtures,evaluation
