"""Recalcul indépendant F4 sur janvier complet, sans lecture MongoDB."""
import argparse
import json
from pathlib import Path
import urllib.request
import urllib.error
import numpy as np
import pandas as pd

p=argparse.ArgumentParser(description=__doc__);p.add_argument('--api',default='http://127.0.0.1:8084');args=p.parse_args()
root=Path(__file__).resolve().parents[1]
f=pd.read_parquet(root/'data/raw/yellow_tripdata_2024-01.parquet')
duplicate=f.duplicated()
pu=f.tpep_pickup_datetime.dt.tz_localize('America/New_York',ambiguous='NaT',nonexistent='NaT').dt.tz_convert('UTC')
do=f.tpep_dropoff_datetime.dt.tz_localize('America/New_York',ambiguous='NaT',nonexistent='NaT').dt.tz_convert('UTC')
duration=(do-pu).dt.total_seconds();distance=f.trip_distance
activity=~((f.total_amount<0)|duplicate)
unresolved=(f.tpep_pickup_datetime.notna()&pu.isna())|(f.tpep_dropoff_datetime.notna()&do.isna())
usable=activity&~(f.PULocationID.isin([264,265])|f.DOLocationID.isin([264,265])|(duration<=0)|(duration>21600)|(distance==0)|(distance>100)|((duration>0)&(distance>0)&(distance/(duration/3600)>80))|unresolved)
f['duration']=duration;f['usable']=usable;f['activity']=activity

def get(query):
 with urllib.request.urlopen(args.api+'/api/journeys?'+query,timeout=60) as r:return json.load(r)
def close(a,b):
 assert (a is None and b is None) or (a is not None and b is not None and np.isclose(a,b,rtol=1e-12,atol=1e-9)),(a,b)
def metric(values,total,actual):
 values=np.asarray(values.dropna(),dtype=float);values=values[np.isfinite(values)]
 assert actual['count']==len(values) and actual['missing']==total-len(values)
 if not len(values):
  assert actual['median'] is None and actual['mean'] is None;return
 q25,med,q75,p90=np.quantile(values,[.25,.5,.75,.9],method='linear');iqr=q75-q25
 for key,value in [('min',values.min()),('q25',q25),('median',med),('q75',q75),('p90',p90),('max',values.max()),('mean',values.mean()),('populationStdDev',values.std(ddof=0)),('iqr',iqr)]: close(actual[key],value)
 assert actual['iqrOutliers']==int(((values<q25-1.5*iqr)|(values>q75+1.5*iqr)).sum())
def stats(frame,actual):
 assert actual['records']==len(frame)
 metric(frame.duration,len(frame),actual['durationSeconds']);metric(frame.trip_distance,len(frame),actual['distanceMiles'])
checks=[]
for origin,destination in [(132,161),(161,236),(181,89)]:
 response=get(f'originId={origin}&destinationId={destination}&from=2024-01-15&to=2024-02-01&referenceFrom=2024-01-01&referenceTo=2024-01-15')
 selected=f[(f.PULocationID==origin)&(f.DOLocationID==destination)]
 strata={}
 for label,start,end in [('reference','2024-01-01','2024-01-15'),('current','2024-01-15','2024-02-01')]:
  frame=selected[(selected.tpep_pickup_datetime>=pd.Timestamp(start))&(selected.tpep_pickup_datetime<pd.Timestamp(end))]
  data=response[label]; good=frame[frame.usable].copy();bad=frame[frame.activity&~frame.usable]
  assert data['raw']==len(frame) and data['retained']==len(good) and data['lessReliable']==len(bad) and data['activityExcluded']==int((~frame.activity).sum())
  stats(good,data['usable']);stats(bad,data['unreliable'])
  def key(r):
   miles='missing' if not np.isfinite(r.trip_distance) else '0-2' if r.trip_distance<2 else '2-5' if r.trip_distance<5 else '5-10' if r.trip_distance<10 else '10+'
   return ('weekend' if r.tpep_pickup_datetime.weekday()>=5 else 'weekday')+'_h'+str(r.tpep_pickup_datetime.hour//6*6)+'_mi'+miles
  good['stratum']=good.apply(key,axis=1) if len(good) else pd.Series(dtype=str)
  strata[label]={k:g for k,g in good.groupby('stratum')}
  assert [s['key'] for s in data['strata']]==sorted(strata[label])
  for s in data['strata']:stats(strata[label][s['key']],s['stats'])
  assert sum(s['retained'] for s in data['sources'])==len(good)
 keys=[k for k in strata['reference'].keys()&strata['current'].keys() if len(strata['reference'][k].duration.dropna())>=30 and len(strata['current'][k].duration.dropna())>=30]
 assert response['comparison']['commonStrata']==len(keys)
 if keys:
  total=sum(len(strata['reference'][k]) for k in keys)
  a=sum(len(strata['reference'][k])/total*strata['reference'][k].duration.mean() for k in keys)
  b=sum(len(strata['reference'][k])/total*strata['current'][k].duration.mean() for k in keys)
  close(response['comparison']['standardizedDurationDifferenceSeconds'],b-a)
 checks.append({'origin':origin,'destination':destination,'referenceRetained':response['reference']['retained'],'currentRetained':response['current']['retained'],'status':response['comparison']['status']})
# Cas sans effectif et couverture manquante, sans fausse comparaison concluante.
d=get('originId=181&destinationId=89&from=2024-02-01&to=2024-02-02&referenceFrom=2024-01-01&referenceTo=2024-01-15')
assert d['comparison']['status']=='SOURCE_MONTH_MISSING' and d['comparison']['standardizedDurationDifferenceSeconds'] is None
for query,status in [('originId=9999&destinationId=161&from=2024-01-15&to=2024-02-01&referenceFrom=2024-01-01&referenceTo=2024-01-15',404),('originId=132&destinationId=161&from=2024-01-15&to=2024-02-01&referenceFrom=2024-01-01&referenceTo=2024-01-16',400),('originId=132&destinationId=161&from=2024-01-15&to=2024-02-01&referenceFrom=2024-01-01&referenceTo=2024-01-15&minTrips=1',400)]:
 try:get(query);raise AssertionError('Erreur attendue')
 except urllib.error.HTTPError as e: assert e.code==status
print(json.dumps({'verified':True,'sourceRows':len(f),'checks':checks,'errorsAndCoverage':True},indent=2))
