"""Build a dated forecast snapshot from verified season feeds."""
import json
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import softmax
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from results_feed import merge
from history import load_history, save_history, update_history
from international_model import predict_internationals
from player_data import PLAYER_FEATURES, for_match, load_players

ROOT = Path(__file__).resolve().parent
TODAY = datetime.now(ZoneInfo('Europe/Lisbon')).date()
FEATURES = ['Elo difference', 'Recent points per game', 'Season points per game',
            'Home vs away points per game', 'Season goal difference per game', 'Recent goal difference per game',
            'League position advantage', 'Recent opponent strength', 'Home venue points per game']
PICK_MINIMUM = .75
PRIORITY = {'en.1','es.1','de.1','it.1','fr.1','pt.1','nl.1','uefa.cl','uefa.el','uefa.ecl'}
BASE = 'https://github.com/openfootball/football.json'
LISBON = ZoneInfo('Europe/Lisbon')
VENUES = {'en':'Europe/London','de':'Europe/Berlin','es':'Europe/Madrid',
          'fr':'Europe/Paris','it':'Europe/Rome','nl':'Europe/Amsterdam','pt':'Europe/Lisbon'}

def summary(games, team):
    won = drawn = lost = gf = ga = 0
    for match in games:
        a, b = match['score']
        if match['away'] == team:
            a, b = b, a
        won += a > b
        drawn += a == b
        lost += a < b
        gf += a
        ga += b
    n = len(games)
    return dict(n=n,w=won,d=drawn,l=lost,gf=gf,ga=ga,gd=gf-ga,pts=3*won+drawn,
                ppg=round((3*won+drawn)/n,2) if n else None,
                gpg=round(gf/n,2) if n else None, gapg=round(ga/n,2) if n else None)

def read_data():
    leagues = []
    european_year = TODAY.year - (TODAY.month < 7)
    path = ROOT/'data'/'fetch-status.json'
    refresh = json.loads(path.read_text()) if path.exists() else {}
    for code, country, name in json.loads((ROOT/'leagues.json').read_text()):
        seasons = {}
        year = TODAY.year if code in ('se.1','us.1') else european_year
        allowed = {str(y) if code in ('se.1','us.1') else f'{y}-{(y+1)%100:02d}' for y in range(year-2,year+1)}
        active = str(year) if code in ('se.1','us.1') else f'{year}-{(year+1)%100:02d}'
        for path in sorted((ROOT/'data').glob(f'[0-9]*_{code}.json')):
            season = path.name.split('_')[0]
            if season not in allowed:
                continue
            rows = {}
            for match in json.loads(path.read_text())['matches']:
                day, home, away = (match.get(k) for k in ('date','team1','team2'))
                try:
                    date.fromisoformat(day)
                except (TypeError,ValueError):
                    continue
                if not home or not away or home == away:
                    continue
                raw_score = match.get('score')
                score = raw_score.get('ft') if isinstance(raw_score, dict) else raw_score
                if not isinstance(score,list) or len(score)!=2 or not all(type(x) is int and x>=0 for x in score):
                    score = None
                kickoff = None
                venue = VENUES.get(code.split('.')[0])
                if venue and match.get('time'):
                    try:
                        local = datetime.fromisoformat(f"{day}T{match['time']}").replace(tzinfo=ZoneInfo(venue))
                        kickoff = local.astimezone(LISBON).strftime('%H:%M')
                        day = local.astimezone(LISBON).date().isoformat()
                    except ValueError:
                        pass
                key = (day,home,away)
                rows[key] = dict(id='|'.join((code,season,*key)), day=day, home=home, away=away,
                                 score=score, kickoff=kickoff, season=season, league=code, round=match.get('round'))
            seasons[season] = sorted(rows.values(),key=lambda x:x['day'])
        enriched=[]
        for path in (ROOT/'data').glob(f'csv_*_{code}.json'):
            season=path.name.split('_')[1]
            if season not in allowed:
                continue
            old=seasons.get(season,[])
            combined=merge(old,json.loads(path.read_text()),code,season)
            if combined is not old:
                seasons[season]=combined
                enriched.append(season)
        leagues.append(dict(code=code,country=country,name=name,seasons=dict(sorted(seasons.items())),
                            resultsFeed=enriched,priority=code in PRIORITY,
                            scoreSource='OpenFootball archive' if code in ('pt.2','hu.1','uefa.cl','uefa.el','uefa.ecl') else 'Football-Data.co.uk',
                            fixturesChecked=refresh.get('checkedAt') if refresh.get('files',{}).get(f'{active}/{code}.json')=='OK' else None))
    return leagues

def standings(current):
    table=[dict(team=t,**summary(g,t),form=['W' if m['score'][m['away']==t]>m['score'][m['home']==t] else 'L' if m['score'][m['away']==t]<m['score'][m['home']==t] else 'D' for m in g[-5:]]) for t,g in current.items() if g]
    return sorted(table,key=lambda r:(-r['pts'],-r['gd'],-r['gf'],r['team']))

def features(match, recent, current, elo, table, opponent_history):
    h,a=match['home'],match['away']
    hs,as_=summary(current[h],h),summary(current[a],a)
    hr,ar=summary(recent[h][-5:],h),summary(recent[a][-5:],a)
    hv=summary([m for m in current[h] if m['home']==h],h)
    av=summary([m for m in current[a] if m['away']==a],a)
    diff=lambda x,y,k:(x[k] if x[k] is not None else 1.35)-(y[k] if y[k] is not None else 1.35)
    gd=lambda x:x['gd']/max(1,x['n'])
    position={r['team']:i+1 for i,r in enumerate(table)}
    rank_gap=(position.get(a,len(table)+1)-position.get(h,len(table)+1))/max(1,len(table))
    opponent=lambda t:sum(opponent_history[t][-5:])/max(1,len(opponent_history[t][-5:]))
    opponent_gap=opponent(h)-opponent(a)
    return [elo[h]-elo[a],diff(hr,ar,'ppg'),diff(hs,as_,'ppg'),diff(hv,av,'ppg'),
            gd(hs)-gd(as_),gd(hr)-gd(ar),rank_gap,opponent_gap,
            hv['ppg'] if hv['ppg'] is not None else 1.35], [hs,as_,hv,av,hr,ar]

def process(leagues, players):
    training, upcoming = [], []
    now = TODAY.isoformat()
    horizon = (TODAY+timedelta(days=30)).isoformat()
    for league in leagues:
        recent=defaultdict(list)
        elo=defaultdict(lambda:1500.)
        opponent_history=defaultdict(list)
        all_rows=[]
        last_table=[]
        for season, rows in league['seasons'].items():
            all_rows.extend(rows)
            current=defaultdict(list)
            for day in sorted({m['day'] for m in rows if m['day'] <= horizon}):
                batch=[m for m in rows if m['day']==day]
                table=standings(current)
                prior_elo={t:elo[t] for m in batch for t in (m['home'],m['away'])}
                for m in batch:
                    h,a=m['home'],m['away']
                    x, stats=features(m,recent,current,elo,table,opponent_history)
                    ready=min(len(recent[h]),len(recent[a]))>=5 and min(len(current[h]),len(current[a]))>=3
                    if day < now and m['score'] is not None and ready:
                        left,right=m['score']
                        player_x,_=for_match(players,m,date.fromisoformat(day),LISBON)
                        training.append((day,league['code'],x,0 if left>right else 1 if left==right else 2,player_x,m['id']))
                    if now <= day <= horizon and m['score'] is None:
                        player_x,player_details=for_match(players,m,TODAY,LISBON)
                        upcoming.append(dict(**m, x=x, ready=ready, stats=stats,table=table,
                                             playerX=player_x,players=player_details,playersUsed=False,
                                             form=[recent[t][-5:][::-1] for t in (h,a)],
                                             long=[summary(recent[t][-10:],t) for t in (h,a)],
                                             h2h=[r for r in recent[h] if a in (r['home'],r['away'])][-5:][::-1]))
                for m in batch:
                    if day>=now or m['score'] is None:
                        continue
                    h,a=m['home'],m['away']
                    left,right=m['score']
                    actual=1 if left>right else .5 if left==right else 0
                    expected=1/(1+10**((elo[a]-elo[h]-65)/400))
                    delta=24*(actual-expected)
                    elo[h]+=delta
                    elo[a]-=delta
                    opponent_history[h].append(prior_elo[a]-1500)
                    opponent_history[a].append(prior_elo[h]-1500)
                    for t in (h,a):
                        current[t].append(m)
                        recent[t].append(m)
            last_table=standings(current)
        league['table']=last_table
        league['tableSeason']=next(reversed(league['seasons']),None)
        league['completed']=sum(m['score'] is not None and m['day']<now for m in all_rows)
        league['upcoming']=sum(m['league']==league['code'] for m in upcoming)
        league['latest']=max((m['day'] for m in all_rows if m['score'] is not None and m['day']<now),default=None)
        league['seasons']=list(league['seasons'])
        age=(TODAY-date.fromisoformat(league['latest'])).days if league['latest'] else None
        league['resultsAge']=age
        league['stale']=age is None or age>21
        unresolved=[m for m in all_rows if m['score'] is None and
                    (TODAY-timedelta(days=14)).isoformat()<=m['day']<now]
        league['unresolved']=len(unresolved)
        unresolved_teams={m[side] for m in unresolved for side in ('home','away')}
        checked=league['fixturesChecked']
        fixtures_stale=not checked or (datetime.now(LISBON)-datetime.fromisoformat(checked))>timedelta(hours=48)
        league['fixtureStatus']='Current feed checked' if not fixtures_stale else 'Current fixture feed unverified'
        for match in upcoming:
            if match['league']==league['code']:
                match['stale']=league['stale'] or fixtures_stale or bool({match['home'],match['away']} & unresolved_teams)
    return sorted(training),upcoming

def predict(model, x, temperature):
    return softmax(np.log(np.clip(model.predict_proba(x),1e-9,1))/temperature,axis=1)

def measure(p,y):
    q=np.stack((1-p[:,2],1-p[:,0]),axis=1)
    hits=np.stack((y!=2,y!=0),axis=1)
    best=q.argmax(axis=1)
    i=np.arange(len(y))
    return dict(n=len(y),logLoss=round(log_loss(y,p,labels=[0,1,2]),4),
                brier=round(float(np.mean((p-np.eye(3)[y])**2)*3),4),
                doubleBrier=np.round(((q-hits)**2).mean(axis=0),4).tolist(),
                hit=np.round(hits.mean(axis=0),4).tolist(),selected=round(float(hits[i,best].mean()),4))

def competition_backtest(records):
    """Pool pre-month training games, then score each league's held-out matches."""
    months=defaultdict(list)
    for record in records:
        months[record[0][:7]].append(record)
    past=[]
    predictions=defaultdict(list)
    for games in months.values():
        if len(past)>=500:
            calibration_start=(date.fromisoformat(games[0][0])-timedelta(days=60)).isoformat()
            training=[r for r in past if r[0]<calibration_start]
            calibration=[r for r in past if r[0]>=calibration_start]
            if len(training)>=300 and len(calibration)>=100:
                x,y=zip(*[(r[2],r[3]) for r in training])
                xc,yc=zip(*[(r[2],r[3]) for r in calibration])
                model=LogisticRegression(max_iter=1200).fit(x,y)
                temperature=minimize_scalar(lambda t:log_loss(yc,predict(model,xc,t),labels=[0,1,2]),
                                            bounds=(.4,4),method='bounded').x
                for record,prob in zip(games,predict(model,[r[2] for r in games],temperature)):
                    predictions[record[1]].append((prob,record[3]))
        past.extend(games)
    return {code:measure(np.array([p for p,y in rows]),np.array([y for p,y in rows]))
            for code,rows in predictions.items()}

def build():
    leagues=read_data()
    final_scores={m['id']:m['score'] for l in leagues for season in l['seasons'].values()
                  for m in season if m['score'] is not None and m['day']<TODAY.isoformat()}
    records,matches=process(leagues,load_players(ROOT))
    evaluation=None
    if len(records)>=300:
        days=sorted({r[0] for r in records})
        cut1,cut2=days[int(len(days)*.65)],days[int(len(days)*.8)]
        partitions=[[r for r in records if ok(r[0])] for ok in
                    (lambda d:d<cut1,lambda d:cut1<=d<cut2,lambda d:d>=cut2)]
        train,val,test=partitions
        unpack=lambda rows:(np.array([r[2] for r in rows]),np.array([r[3] for r in rows]))
        xv,yv=unpack(val)
        xe,ye=unpack(test)
        candidates=[]
        for name,model,window in [
                ('Logistic regression · three seasons',LogisticRegression(max_iter=1200),train),
                ('Gradient boosted trees · three seasons',HistGradientBoostingClassifier(max_iter=85,random_state=42),train)]:
            if len(window)<100:
                continue
            x_fit,y_fit=unpack(window)
            if len(set(y_fit))!=3:
                continue
            model.fit(x_fit,y_fit)
            temp=minimize_scalar(lambda t:log_loss(yv,predict(model,xv,t),labels=[0,1,2]),
                                 bounds=(.4,4),method='bounded').x
            candidates.append((log_loss(yv,predict(model,xv,temp),labels=[0,1,2]),name,model,temp,window))
        _,name,model,temp,chosen_train=min(candidates,key=lambda c:c[0])
        player_fit=None
        player_evaluation=None
        with_players=[[r for r in part if r[4] is not None] for part in partitions]
        if all(len(part)>=limit and len({r[3] for r in part})==3
               for part,limit in zip(with_players,(500,150,150))):
            player_train,player_val,player_test=with_players
            player_unpack=lambda rows:(np.array([r[2]+r[4] for r in rows]),np.array([r[3] for r in rows]))
            xp,yp=player_unpack(player_train)
            xpv,ypv=player_unpack(player_val)
            xpe,ype=player_unpack(player_test)
            pm=LogisticRegression(max_iter=1200).fit(xp,yp)
            pt=minimize_scalar(lambda t:log_loss(ypv,predict(pm,xpv,t),labels=[0,1,2]),
                               bounds=(.4,4),method='bounded').x
            if log_loss(ypv,predict(pm,xpv,pt),labels=[0,1,2]) < log_loss(ypv,predict(model,xpv[:,:len(FEATURES)],temp),labels=[0,1,2]):
                player_fit=(pm,pt,np.median(xp,axis=0))
                player_evaluation=dict(augmented=measure(predict(pm,xpe,pt),ype),
                                       teamOnly=measure(predict(model,xpe[:,:len(FEATURES)],temp),ype))
        p=predict(model,xe,temp)
        q=np.stack((1-p[:,2],1-p[:,0]),axis=1)
        best=q.argmax(axis=1)
        scores=q.max(axis=1)
        hit=np.where(best==0,ye!=2,ye!=0)
        bands=[]
        for lo,hi in zip([.75,.8,.85,.9,.95],[.8,.85,.9,.95,1.01]):
            mask=(scores>.75)&(scores>=lo)&(scores<hi)
            if mask.any():
                bands.append(dict(lo=lo,hi=min(hi,1),n=int(mask.sum()),expected=float(scores[mask].mean()),observed=float(hit[mask].mean())))
        qualifying=scores>PICK_MINIMUM
        match_days={r[0] for r in test}
        shown_days={r[0] for r,shown in zip(test,qualifying) if shown}
        displayed=dict(n=int(qualifying.sum()),hit=float(hit[qualifying].mean()) if qualifying.any() else None,
                       days=len(shown_days),matchDays=len(match_days))
        by_league=competition_backtest(records)
        evaluation=dict(name=name,train=len(chosen_train),trainingStart=chosen_train[0][0],historyStart=records[0][0],historyMatches=len(records),validation=len(val),start=test[0][0],end=test[-1][0],
                        **measure(p,ye),bands=bands,displayed=displayed,playerModel=player_evaluation,leagues=by_league,
                        models=[dict(name=n,train=len(w),trainStart=w[0][0],**measure(predict(m,xe,t),ye)) for _,n,m,t,w in candidates])
        median=np.median(unpack(chosen_train)[0],axis=0)
        eligible=[m for m in matches if m['ready']]
        if eligible:
            probabilities=predict(model,np.array([m['x'] for m in eligible]),temp)
            for m,probs in zip(eligible,probabilities):
                active_model,active_temp,active_median=model,temp,median
                feature_names=FEATURES
                x=np.array(m['x'])
                if player_fit and m['playerX'] is not None:
                    active_model,active_temp,active_median=player_fit
                    feature_names=FEATURES+list(PLAYER_FEATURES)
                    x=np.array(m['x']+m['playerX'])
                    probs=predict(active_model,x[None,:],active_temp)[0]
                    m['playersUsed']=True
                x_alt=np.repeat(x[None,:],len(x),axis=0)
                np.fill_diagonal(x_alt,active_median)
                alt=predict(active_model,x_alt,active_temp)
                excluded=2 if probs[2]<=probs[0] else 0
                m['market']='1X' if excluded==2 else 'X2'
                m['prob']=(1-probs[excluded]).item()
                m['breakdown']=probs.tolist()
                m['why']=sorted([dict(name=k,value=float(x[i]),delta=float(alt[i,excluded]-probs[excluded]))
                                  for i,k in enumerate(feature_names)],key=lambda e:abs(e['delta']),reverse=True)[:3]
    timestamp=datetime.now(ZoneInfo('Europe/Lisbon')).isoformat(timespec='seconds')
    for m in matches:
        m.pop('x')
        m.pop('playerX')
    national_leagues,national_matches,national_evaluation=predict_internationals(
        TODAY,LISBON,PICK_MINIMUM,summary,predict,measure,standings)
    leagues.extend(national_leagues)
    matches.extend(national_matches)
    snapshot=dict(internationalEvaluation=national_evaluation,updated=timestamp,day=TODAY.isoformat(),source=BASE,pickMinimum=PICK_MINIMUM,leagues=leagues,matches=matches,evaluation=evaluation)
    crest_file=ROOT/'crests.json'
    snapshot['crests']=json.loads(crest_file.read_text()) if crest_file.exists() else {}
    extra_crests=ROOT/'standings_crests.json'
    if extra_crests.exists():
        snapshot['crests'].update(json.loads(extra_crests.read_text()))
    international_file = ROOT/'data'/'international-fixtures.json'
    if international_file.exists():
        for match in json.loads(international_file.read_text())['rows']:
            if match['score'] is not None and match['day'] <= TODAY.isoformat():
                match_id = f"int.unl|2026-27|{match['day']}|{match['home']}|{match['away']}"
                final_scores[match_id] = match['score']

    history_path = ROOT/'dist'/'history.json'
    with sqlite3.connect(ROOT/'data'/'forecasts.sqlite') as db:
        db.execute('CREATE TABLE IF NOT EXISTS published_history (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
        cached = db.execute('SELECT payload FROM published_history WHERE id = 1').fetchone()
        history = json.loads(cached[0]) if cached else load_history(history_path)
        history = update_history(history, snapshot, final_scores)
        db.execute('INSERT OR REPLACE INTO published_history VALUES (1, ?)', (json.dumps(history),))
    save_history(history_path, history)
    target=ROOT/'dist'/'snapshot.json'
    temp_path=target.with_suffix('.tmp')
    temp_path.write_text(json.dumps(snapshot,ensure_ascii=False,allow_nan=False))
    temp_path.replace(target)
    print(f'{len(records)} training-eligible results, {len(matches)} upcoming fixtures, {sum("prob" in m for m in matches)} forecasts')

if __name__=='__main__':
    build()
