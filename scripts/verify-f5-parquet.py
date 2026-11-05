"""Recalcul indépendant F5 sur janvier complet, sans lire MongoDB."""
import argparse
import json
from pathlib import Path
import urllib.request
import urllib.error
import numpy as np
import pandas as pd

p=argparse.ArgumentParser(description=__doc__);p.add_argument('--api',default='http://127.0.0.1:8086');args=p.parse_args()
root=Path(__file__).resolve().parents[1]
f=pd.read_parquet(root/'data/raw/yellow_tripdata_2024-01.parquet')
f['kept']=~((f.total_amount<0)|f.duplicated()|f.PULocationID.isin([264,265])|f.DOLocationID.isin([264,265]))
f=f.loc[(f.tpep_pickup_datetime>=pd.Timestamp('2024-01-01'))&(f.tpep_pickup_datetime<pd.Timestamp('2024-01-29')),['PULocationID','DOLocationID','tpep_pickup_datetime','kept']].copy()
f['week']=(f.tpep_pickup_datetime.dt.normalize()-pd.to_timedelta(f.tpep_pickup_datetime.dt.weekday,unit='D')).dt.strftime('%Y-%m-%d')
zones=pd.read_csv(root/'data/raw/taxi_zone_lookup.csv')
base='from=2024-01-22&to=2024-01-29&referenceFrom=2024-01-15&referenceTo=2024-01-22&baselineFrom=2024-01-01&baselineTo=2024-01-22'
def get(q):
 with urllib.request.urlopen(args.api+'/api/flow-changes?'+q,timeout=150) as r:return json.load(r)
def close(a,b):assert np.isclose(a,b,rtol=1e-12,atol=1e-12),(a,b)
checks=[]
for scope,ids in [('zoneIds=132',[132]),('borough=Brooklyn',zones.loc[zones.Borough=='Brooklyn','LocationID'].tolist()),('',zones.LocationID.tolist())]:
 response=get((scope+'&' if scope else '')+base)
 sub=f[f.PULocationID.isin(ids)]
 counts=sub.groupby(['PULocationID','DOLocationID','week']).kept.agg(['size','sum'])
 weekly=sub.groupby('week').kept.agg(['size','sum'])
 def n(o,d,w):return int(counts.loc[(o,d,w),'sum']) if (o,d,w) in counts.index else 0
 def raw(o,d,w):return int(counts.loc[(o,d,w),'size']) if (o,d,w) in counts.index else 0
 wa=['2024-01-01','2024-01-08','2024-01-15'];a='2024-01-15';b='2024-01-22'
 for label,w in [('reference',a),('current',b)]:
  assert response[label]['counts']=={'raw':int(weekly.loc[w,'size']),'retained':int(weekly.loc[w,'sum']),'excluded':int(weekly.loc[w,'size']-weekly.loc[w,'sum'])}
 expected={}
 for o,d in counts.index.droplevel(2).unique():
  ca,cb=n(o,d,a),n(o,d,b)
  if not ca and not cb:continue
  pa,pb=ca/weekly.loc[a,'sum'],cb/weekly.loc[b,'sum'];delta=pb-pa
  shares=[n(o,d,w)/weekly.loc[w,'sum'] for w in wa];diffs=np.diff(shares);p90=float(np.quantile(abs(diffs),.9,method='linear'));ratio=abs(delta)/max(p90,.001)
  status='LOW_COUNTS' if max(ca,cb)<20 else 'LOW_BASELINE_COUNTS' if sum(n(o,d,w) for w in wa)<20 else 'SMALL_SHARE_CHANGE' if abs(delta)<.001 else 'WITHIN_WEEKLY_VARIATION' if ratio<2 else 'CHANGED'
  expected[(int(o),int(d))]=dict(ca=ca,cb=cb,pa=pa,pb=pb,delta=delta,p90=p90,ratio=ratio,status=status,diffs=diffs)
 rank=lambda k:(-abs(expected[k]['delta']),k[0],k[1])
 qualified=sorted([k for k,v in expected.items() if v['status']=='CHANGED'],key=rank)
 assert response['status']=='COMPARABLE' and response['pairsConsidered']==len(expected) and response['qualifiedPairs']==len(qualified)
 for field,keys in [('increases',[k for k in qualified if expected[k]['delta']>0]),('decreases',[k for k in qualified if expected[k]['delta']<0]),('otherLargestChanges',sorted([k for k,v in expected.items() if v['status']!='CHANGED'],key=rank))]:
  assert [(c['origin']['id'],c['destination']['id']) for c in response[field]]==keys[:10]
  for c in response[field]:
   o,d=c['origin']['id'],c['destination']['id'];e=expected[(o,d)]
   assert c['status']==e['status'] and c['referenceCounts']['retained']==e['ca'] and c['currentCounts']['retained']==e['cb']
   for field2,key in [('referenceShare','pa'),('currentShare','pb'),('shareChange','delta'),('p90WeeklyChange','p90'),('variationRatio','ratio')]:close(c[field2],e[key])
   close(c['percentagePointChange'],100*e['delta'])
   close(c['volumeOnlyCountChange']+c['residualCountChange'],e['cb']-e['ca'])
   for week in c['baselineWeeks']:
    assert week['counts']['retained']==n(o,d,week['start']) and week['counts']['raw']==raw(o,d,week['start'])
    assert sum(s['counts']['retained'] for s in week['sources'])==week['counts']['retained']
 checks.append({'scope':scope or 'citywide','pairs':len(expected),'qualified':len(qualified),'referenceTotal':response['reference']['counts']['retained'],'currentTotal':response['current']['counts']['retained']})
for q,status in [('zoneIds=9999&'+base,404),('zoneIds=132&borough=Brooklyn&'+base,400),('zoneIds=132&'+base.replace('from=2024-01-22','from=2024-01-23'),400),('zoneIds=132&'+base.replace('baselineTo=2024-01-22','baselineTo=2024-01-29'),400)]:
 try:get(q);raise AssertionError('Erreur attendue')
 except urllib.error.HTTPError as e:assert e.code==status
missing=get('zoneIds=132&'+base.replace('from=2024-01-22&to=2024-01-29','from=2024-02-05&to=2024-02-12'))
assert missing['status']=='INCOMPLETE_OR_LOW_VOLUME_PERIOD' and not missing['increases'] and not missing['decreases']
short=get('zoneIds=132&'+base.replace('baselineTo=2024-01-22','baselineTo=2024-01-15'))
assert short['status']=='INSUFFICIENT_BASELINE' and not short['increases'] and not short['decreases']
print(json.dumps({'verified':True,'sourceRows':2964624,'checks':checks,'coverageAndInputChecks':True},indent=2))
