"""Temporally evaluate a UEFA coefficient model for clubs lacking full match features."""
from collections import defaultdict
import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import softmax
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from ranking_data import load,coefficient_features
from picks import MINIMUM,home_exception


def run(games,matches,today,measure,standings):
    archive=load()
    records=[]
    current=defaultdict(lambda:defaultdict(list))
    for day in sorted({game['day'] for game in games}):
        batch=[game for game in games if game['day']==day]
        for game in batch:
            key=(game['league'],game['season'])
            value=coefficient_features(game['home'],game['away'],day,archive)
            if value:
                score=game['score']
                target=0 if score[0]>score[1] else 1 if score[0]==score[1] else 2
                risk=home_exception(None,standings(current[key]),game['home'],game['away'])
                records.append((day,value[0],target,game['league'],risk))
        for game in batch:
            for team in (game['home'],game['away']):
                current[(game['league'],game['season'])][team].append(game)
    if len(records)<150:
        return dict(available=False,reason='Insufficient pre-match coefficient observations',n=len(records))
    days=sorted({r[0] for r in records})
    if len(days)<8:
        return dict(available=False,reason='Insufficient distinct calibration dates',n=len(records))
    first,last=days[int(.60*len(days))],days[int(.80*len(days))]
    partitions=[[r for r in records if pred(r[0])] for pred in
                (lambda day:day<first,lambda day:first<=day<last,lambda day:day>=last)]
    if min(map(len,partitions))<20 or len({r[2] for r in partitions[0]})<3:
        return dict(available=False,reason='Insufficient chronological partitions',n=len(records))
    def xy(rows):
        return np.array([r[1] for r in rows]),np.array([r[2] for r in rows])
    xt,yt=xy(partitions[0]);xv,yv=xy(partitions[1]);xe,ye=xy(partitions[2])
    model=LogisticRegression(max_iter=1200,C=1.).fit(xt,yt)
    def forecast(x,temp):
        return softmax(np.log(np.clip(model.predict_proba(x),1e-9,1))/temp,axis=1)
    temp=minimize_scalar(lambda t:log_loss(yv,forecast(xv,t),labels=[0,1,2]),
                         bounds=(.5,4.),method='bounded').x
    prior=np.bincount(yt,minlength=3)/len(yt)
    validation_loss=log_loss(yv,forecast(xv,temp),labels=[0,1,2])
    prior_loss=log_loss(yv,np.tile(prior,(len(yv),1)),labels=[0,1,2])
    enabled=validation_loss<prior_loss and len(ye)>=40
    p=forecast(xe,temp)
    risk=np.array([r[4] for r in partitions[2]])
    result=dict(available=True,enabled=enabled,name='Official UEFA coefficient · calibrated logistic regression',
                train=len(yt),validation=len(yv),start=partitions[2][0][0],end=partitions[2][-1][0],
                validationLogLoss=float(validation_loss),baselineValidationLogLoss=float(prior_loss),
                baseline=measure(np.tile(prior,(len(ye),1)),ye),**measure(p,ye,risk),
                risky=dict(n=int(risk.sum()),hit=float((ye[risk]!=2).mean()) if risk.any() else None))
    applied=0
    if enabled:
        median=np.median(xt,axis=0)
        for match in matches:
            if 'prob' in match or not match['league'].startswith('uefa.') or match.get('stale'):
                continue
            value=coefficient_features(match['home'],match['away'],today.isoformat(),archive)
            if not value:
                continue
            x,details=value
            probs=forecast([x],temp)[0]
            excluded=2 if probs[2]<=probs[0] else 0
            alt=np.tile(x,(2,1)).astype(float)
            np.fill_diagonal(alt,median)
            reference=forecast(alt,temp)
            match.update(prob=float(1-probs[excluded]),market='1X' if excluded==2 else 'X2',
                         breakdown=probs.tolist(),rankingFallback=details,
                         homeException=home_exception(None,match['table'],match['home'],match['away']),
                         why=[dict(name=label,value=float(x[i]),delta=float(reference[i,excluded]-probs[excluded]))
                              for i,label in enumerate(['UEFA coefficient advantage','UEFA ranking advantage'])])
            applied+=1
    result['forecastsAdded']=applied
    return result
