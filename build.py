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
from european_data import SOURCES as EUROPEAN_SOURCES, club_key
from history import load_history, load_published_history, merge_picks, save_history, update_history
from international_model import predict_internationals
from model_benchmarks import (EloGoals, FORM_WINDOW, ModelBlend, market_metrics, recent_strength,
                              select_forecast_model)
from picks import MINIMUM, EXCEPTION_MINIMUM, assign_picks, home_exception
from player_data import PLAYER_FEATURES, for_match, load_players

ROOT = Path(__file__).resolve().parent
TODAY = datetime.now(ZoneInfo('Europe/Lisbon')).date()
FEATURES = ['Elo difference', 'Recent points adjusted for opponent Elo', 'Season points per game',
            'Home vs away points per game', 'Season goal difference per game', 'Recent goal difference per game',
            'League position advantage', 'Recent opponent strength', 'Home venue points per game',
            'Away venue points per game', 'Unbeaten rate advantage', 'Home and away rest difference',
            'Home recent goals scored', 'Home recent goals conceded',
            'Away recent goals scored', 'Away recent goals conceded']
PICK_MINIMUM = MINIMUM
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
            payload=json.loads(path.read_text())
            if code in EUROPEAN_SOURCES and season == active and payload.get('checkedAt'):
                refresh.setdefault('files',{})[f'{active}/{code}.json']='OK'
            for match in payload['matches']:
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
                if match.get('kickoffCET'):
                    local=datetime.fromisoformat(f"{day}T{match['kickoffCET']}").replace(tzinfo=ZoneInfo('Europe/Berlin'))
                    kickoff=local.astimezone(LISBON).strftime('%H:%M')
                    day=local.astimezone(LISBON).date().isoformat()
                key = (day,home,away)
                rows[key] = dict(id='|'.join((code,season,*key)), day=day, home=home, away=away,
                                 score=score, kickoff=kickoff, season=season, league=code, round=match.get('round'), source=match.get('source'))
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
                            scoreSource='UEFA schedule / matched ESPN results' if code in EUROPEAN_SOURCES else 'OpenFootball archive' if code in ('pt.2','hu.1') else 'Football-Data.co.uk',
                            fixturesChecked=(json.loads((ROOT/'data'/f'{active}_{code}.json').read_text()).get('checkedAt')
                                             if code in EUROPEAN_SOURCES and (ROOT/'data'/f'{active}_{code}.json').exists()
                                             else refresh.get('checkedAt') if refresh.get('files',{}).get(f'{active}/{code}.json')=='OK' else None)))
    scoreboard_path=ROOT/'data'/'scoreboard.json'
    if scoreboard_path.exists():
        scoreboard=json.loads(scoreboard_path.read_text())
        for league in leagues:
            entry=scoreboard.get('leagues',{}).get(league['code'])
            if not entry:
                continue
            for season in {m['season'] for m in entry['matches']}:
                existing={m['id']:m for m in league['seasons'].get(season,[])}
                for m in entry['matches']:
                    if m['season']==season:
                        existing={identity:old for identity,old in existing.items()
                                  if identity==m['id']
                                  or old['home']!=m['home'] or old['away']!=m['away']
                                  or abs((date.fromisoformat(old['day'])-date.fromisoformat(m['day'])).days)>7}
                        original=existing.get(m['id'],{})
                        existing[m['id']]=dict(original,**m)
                        if original.get('score') is not None and m['score'] is None:
                            existing[m['id']]['score']=original['score']
                league['seasons'][season]=sorted(existing.values(),key=lambda m:(m['day'],m['id']))
            league['seasons']=dict(sorted(league['seasons'].items()))
            recent_checks=[stamp for day,stamp in entry.get('checkedDays',{}).items()
                           if TODAY.isoformat()<=day<=(TODAY+timedelta(days=3)).isoformat()]
            if len(recent_checks)==4:
                league['fixturesChecked']=min(recent_checks)
            league['scoreSource']+=' / ESPN scoreboard'
    return leagues

def standings(current):
    table=[dict(team=t,**summary(g,t),form=['W' if m['score'][m['away']==t]>m['score'][m['home']==t] else 'L' if m['score'][m['away']==t]<m['score'][m['home']==t] else 'D' for m in g[-5:]]) for t,g in current.items() if g]
    return sorted(table,key=lambda r:(-r['pts'],-r['gd'],-r['gf'],r['team']))

def features(match, recent, current, elo, table, opponent_history, window=FORM_WINDOW, all_venues=False):
    h,a=match['home'],match['away']
    hs,as_=summary(current[h],h),summary(current[a],a)
    hr,ar=[summary(recent[t][-window:],t) for t in (h,a)]
    home_venue=recent[h][-FORM_WINDOW:] if all_venues else current[h]
    away_venue=recent[a][-FORM_WINDOW:] if all_venues else current[a]
    hv=summary([m for m in home_venue if m['home']==h],h)
    av=summary([m for m in away_venue if m['away']==a],a)
    diff=lambda x,y,k:(x[k] if x[k] is not None else 1.35)-(y[k] if y[k] is not None else 1.35)
    gd=lambda x:x['gd']/max(1,x['n'])
    position={r['team']:i+1 for i,r in enumerate(table)}
    rank_gap=(position.get(a,len(table)+1)-position.get(h,len(table)+1))/max(1,len(table))
    home_form, home_opponents = recent_strength(h, recent[h], opponent_history[h], window)
    away_form, away_opponents = recent_strength(a, recent[a], opponent_history[a], window)
    def rest(team):
        return min(21, (date.fromisoformat(match['day']) - date.fromisoformat(recent[team][-1]['day'])).days) if recent[team] else 7
    return [elo[h]-elo[a],home_form-away_form,diff(hs,as_,'ppg'),diff(hv,av,'ppg'),
            gd(hs)-gd(as_),gd(hr)-gd(ar),rank_gap,home_opponents-away_opponents,
            hv['ppg'] if hv['ppg'] is not None else 1.35,
            av['ppg'] if av['ppg'] is not None else 1.35,
            (hr['w']+hr['d'])/max(1,hr['n'])-(ar['w']+ar['d'])/max(1,ar['n']),
            rest(h)-rest(a), hr['gpg'] or 0, hr['gapg'] or 0, ar['gpg'] or 0, ar['gapg'] or 0], [hs,as_,hv,av,hr,ar]

def european_context(leagues):
    names={}
    for league in leagues:
        if league['code'] not in EUROPEAN_SOURCES:
            for rows in league['seasons'].values():
                for match in rows:
                    for side in ('home','away'):
                        names.setdefault(club_key(match[side]),match[side])
    for league in leagues:
        if league['code'] in EUROPEAN_SOURCES:
            for rows in league['seasons'].values():
                for match in rows:
                    for side in ('home','away'):
                        names.setdefault(club_key(match[side]),match[side])
                        match[side]=names[club_key(match[side])]
                    match['id']='|'.join((match['league'],match['season'],match['day'],match['home'],match['away']))
    context=defaultdict(dict)
    for league in leagues:
        for season,rows in league['seasons'].items():
            for match in rows:
                if match['score'] is None:
                    continue
                normalized=dict(match,home=names.get(club_key(match['home']),match['home']),
                                away=names.get(club_key(match['away']),match['away']))
                key=(normalized['day'],normalized['home'],normalized['away'])
                context[season][key]=normalized
    return context


def process(leagues, players):
    training, upcoming = [], []
    context=european_context(leagues)
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
            if league['code'] in EUROPEAN_SOURCES:
                others=[m for m in context.get(season,{}).values() if m['league']!=league['code']]
                rows=rows+others
            current=defaultdict(list)
            for day in sorted({m['day'] for m in rows if m['day'] <= horizon}):
                batch=[m for m in rows if m['day']==day]
                table=standings(current)
                prior_elo={t:elo[t] for m in batch for t in (m['home'],m['away'])}
                for m in batch:
                    if m['league']!=league['code']:
                        continue
                    h,a=m['home'],m['away']
                    x, stats=features(m,recent,current,elo,table,opponent_history,all_venues=league["code"] in EUROPEAN_SOURCES)
                    ready=min(len(recent[h]),len(recent[a]))>=FORM_WINDOW and min(len(current[h]),len(current[a]))>=3
                    if day < now and m['score'] is not None and ready:
                        left,right=m['score']
                        player_x,_=for_match(players,m,date.fromisoformat(day),LISBON)
                        training.append((day,league['code'],x,0 if left>right else 1 if left==right else 2,player_x,m['id'],m['score'],home_exception(stats,table,h,a),
                                         stats[4]['ppg']-stats[5]['ppg'],
                                         features(m,recent,current,elo,table,opponent_history,5,all_venues=league["code"] in EUROPEAN_SOURCES)[0]))
                    if now <= day <= horizon and m['score'] is None:
                        player_x,player_details=for_match(players,m,TODAY,LISBON)
                        upcoming.append(dict(**m, formScope='Domestic and European matches' if league['code'] in EUROPEAN_SOURCES else 'League matches', x=x, ready=ready, stats=stats,table=table,
                                             playerX=player_x,players=player_details,playersUsed=False,
                                             form=[recent[t][-FORM_WINDOW:][::-1] for t in (h,a)],
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
                    opponent_history[h].append(prior_elo[a])
                    opponent_history[a].append(prior_elo[h])
                    for t in (h,a):
                        if m['league']==league['code']:
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
                markets=market_metrics(p,y),hit=np.round(hits.mean(axis=0),4).tolist(),selected=round(float(hits[i,best].mean()),4))

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
    european_context(leagues)
    final_scores={m['id']:m['score'] for l in leagues for season in l['seasons'].values()
                  for m in season if m['score'] is not None and m['day']<=TODAY.isoformat()}
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
                ('Gradient boosted trees · three seasons',HistGradientBoostingClassifier(max_iter=85,random_state=42),train),
                ('Elo + Poisson',EloGoals(),train),
                ('Elo + Dixon–Coles',EloGoals(correction=True),train)]:
            if len(window)<100:
                continue
            x_fit,y_fit=unpack(window)
            if len(set(y_fit))!=3:
                continue
            model.fit(x_fit,[r[6] for r in window] if isinstance(model,EloGoals) else y_fit)
            candidates.append((name,model))
        fitted=dict(candidates)
        candidates.append(('Logistic + Elo Poisson blend',ModelBlend(
            fitted['Logistic regression · three seasons'],fitted['Elo + Poisson'])))
        validation_codes=np.array([r[1] for r in val])
        league_ids=np.array([r[1] for r in test])
        name,model,calibration,incumbent,baselines=select_forecast_model(
            candidates,xv,yv,validation_codes,np.array([r[0] for r in val]))
        chosen_train=train
        incumbent_name,incumbent_model,incumbent_calibration=incumbent
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
            if log_loss(ypv,predict(pm,xpv,pt),labels=[0,1,2]) < log_loss(ypv,calibration.predict(model.predict_proba(xpv[:,:len(FEATURES)]),np.array([r[1] for r in player_val])),labels=[0,1,2]):
                player_fit=(pm,pt,np.median(xp,axis=0))
                player_evaluation=dict(augmented=measure(predict(pm,xpe,pt),ype),
                                       teamOnly=measure(calibration.predict(model.predict_proba(xpe[:,:len(FEATURES)]),np.array([r[1] for r in player_test])),ype))
        # Controlled feature comparisons on the same dates using logistic regression.
        ablations=[]
        for label, transform in [
                ('10 matches · opponent-adjusted',lambda x,row:x),
                ('5 matches · opponent-adjusted',lambda x,row:row[9]),
                ('10 matches · raw points',lambda x,row:[*x[:1],row[8],*x[2:7],0.,*x[8:]]),
                ('Opponent-adjusted · without venue form',lambda x,row:[*x[:3],0.,*x[4:8],1.35,1.35,*x[10:]])]:
            arrays=[np.array([transform(r[2],r) for r in part]) for part in partitions]
            baseline=LogisticRegression(max_iter=1500).fit(arrays[0],[r[3] for r in train])
            t=minimize_scalar(lambda t:log_loss(yv,predict(baseline,arrays[1],t),labels=[0,1,2]),
                              bounds=(.4,4),method='bounded').x
            ablations.append(dict(name=label, **measure(predict(baseline,arrays[2],t),ye)))
        p=calibration.predict(model.predict_proba(xe),league_ids)
        q=np.stack((1-p[:,2],1-p[:,0]),axis=1)
        best=q.argmax(axis=1)
        scores=q.max(axis=1)
        hit=np.where(best==0,ye!=2,ye!=0)
        bands=[]
        for lo,hi in zip([.85,.9,.95],[.9,.95,1.01]):
            mask=(scores>=lo)&(scores<hi)
            if mask.any():
                bands.append(dict(lo=lo,hi=min(hi,1),n=int(mask.sum()),expected=float(scores[mask].mean()),observed=float(hit[mask].mean())))
        qualifying=scores>=PICK_MINIMUM
        exceptions=np.zeros(len(test),dtype=bool)
        exception_days=set()
        for index in np.argsort(-scores,kind='stable'):
            day=test[index][0]
            if (best[index]==0 and EXCEPTION_MINIMUM<=scores[index]<PICK_MINIMUM
                    and test[index][7] and day not in exception_days):
                exceptions[index]=True
                exception_days.add(day)
        match_days={r[0] for r in test}
        shown_days={r[0] for r,shown in zip(test,qualifying) if shown}
        displayed=dict(n=int(qualifying.sum()),hit=float(hit[qualifying].mean()) if qualifying.any() else None,
                       days=len(shown_days),matchDays=len(match_days),
                       exceptions=int(exceptions.sum()),
                       exceptionHit=float(hit[exceptions].mean()) if exceptions.any() else None)
        holdout_leagues={code:measure(p[league_ids==code],ye[league_ids==code])
                         for code in sorted(set(league_ids))}
        by_league=competition_backtest(records)
        evaluation=dict(name=name,train=len(chosen_train),trainingStart=chosen_train[0][0],historyStart=records[0][0],historyMatches=len(records),validation=len(val),start=test[0][0],end=test[-1][0],
                        **measure(p,ye),bands=bands,displayed=displayed,playerModel=player_evaluation,leagues=by_league,holdoutLeagues=holdout_leagues,ablations=ablations,
                        calibration=calibration.method,calibratedLeagues=sorted(calibration.offsets),
                        incumbent=dict(name=incumbent_name,**measure(incumbent_calibration.predict(
                            incumbent_model.predict_proba(xe),league_ids),ye)),
                        models=[dict(name=n,train=len(train),trainStart=train[0][0],
                                     **measure(c.predict(m.predict_proba(xe),league_ids),ye))
                                for n,(_,m,c) in baselines.items()])
        median=np.median(unpack(chosen_train)[0],axis=0)
        eligible=[m for m in matches if m['ready']]
        if eligible:
            probabilities=calibration.predict(model.predict_proba([m['x'] for m in eligible]),
                                                np.array([m['league'] for m in eligible]))
            for m,probs in zip(eligible,probabilities):
                active_median=median
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
                alt=(predict(active_model,x_alt,active_temp) if m['playersUsed'] else
                     calibration.predict(model.predict_proba(x_alt),np.repeat(m['league'],len(x))))
                excluded=2 if probs[2]<=probs[0] else 0
                m['market']='1X' if excluded==2 else 'X2'
                m['prob']=(1-probs[excluded]).item()
                m['homeException']=home_exception(m['stats'],m['table'],m['home'],m['away'])
                m['breakdown']=probs.tolist()
                m['why']=sorted([dict(name=k,value=float(x[i]),delta=float(alt[i,excluded]-probs[excluded]))
                                  for i,k in enumerate(feature_names)],key=lambda e:abs(e['delta']),reverse=True)[:3]
    timestamp=datetime.now(ZoneInfo('Europe/Lisbon')).isoformat(timespec='seconds')
    for m in matches:
        m.pop('x')
        m.pop('playerX')
    national_leagues,national_matches,national_evaluation,national_scores=predict_internationals(
        TODAY,LISBON,PICK_MINIMUM,summary,measure,standings)
    leagues.extend(national_leagues)
    matches.extend(national_matches)
    snapshot=dict(internationalEvaluation=national_evaluation,updated=timestamp,day=TODAY.isoformat(),source=BASE,pickMinimum=PICK_MINIMUM,leagues=leagues,matches=matches,evaluation=evaluation)
    club_tables=ROOT/'data'/'club-tables.json'
    if club_tables.exists():
        display_tables=json.loads(club_tables.read_text())
        for league in leagues:
            table=display_tables.get(league['code'])
            if table and table['season'] >= (league.get('tableSeason') or ''):
                league['displayTable']=table
    crest_file=ROOT/'crests.json'
    snapshot['crests']=json.loads(crest_file.read_text()) if crest_file.exists() else {}
    extra_crests=ROOT/'standings_crests.json'
    if extra_crests.exists():
        snapshot['crests'].update(json.loads(extra_crests.read_text()))
    final_scores.update(national_scores)

    assign_picks(snapshot)
    history_path = ROOT/'dist'/'history.json'
    with sqlite3.connect(ROOT/'data'/'forecasts.sqlite') as db:
        db.execute('CREATE TABLE IF NOT EXISTS published_history (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
        cached = db.execute('SELECT payload FROM published_history WHERE id = 1').fetchone()
        history = load_history(history_path)
        published = load_published_history()
        if cached or published:
            history['picks'] = merge_picks(history['picks'],
                                           json.loads(cached[0])['picks'] if cached else [],
                                           published['picks'] if published else [])
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
