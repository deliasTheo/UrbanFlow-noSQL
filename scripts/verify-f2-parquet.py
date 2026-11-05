"""Vérification indépendante F2 sur janvier complet, sans lire MongoDB.
API lancée sur la base contenant uniquement janvier complet.
"""
import argparse
import json
from pathlib import Path
import urllib.request
import urllib.error
import pandas as pd

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--api',default='http://127.0.0.1:8081')
args=p.parse_args()
root=Path(__file__).resolve().parents[1]
frame=pd.read_parquet(root/'data/raw/yellow_tripdata_2024-01.parquet')
# Recalcul direct depuis les colonnes originales, sans utiliser les flags MongoDB.
frame['retained']=~((frame.total_amount<0)|frame.duplicated()|frame.PULocationID.isin([264,265])|frame.DOLocationID.isin([264,265]))
frame=frame[(frame.tpep_pickup_datetime>=pd.Timestamp('2024-01-01'))&(frame.tpep_pickup_datetime<pd.Timestamp('2024-02-01'))].copy()
frame['week']=(frame.tpep_pickup_datetime.dt.normalize()-pd.to_timedelta(frame.tpep_pickup_datetime.dt.weekday,unit='D')).dt.strftime('%Y-%m-%d')
zones=pd.read_csv(root/'data/raw/taxi_zone_lookup.csv')
checks=[]
for scope,ids in [('zoneIds=181',[181]),('borough=Brooklyn',zones.loc[zones.Borough=='Brooklyn','LocationID'].tolist())]:
    url=f'{args.api}/api/flows?{scope}&from=2024-01-01&to=2024-02-01'
    with urllib.request.urlopen(url,timeout=150) as r: response=json.load(r)
    outgoing=frame[frame.PULocationID.isin(ids)]
    def counts(f): return dict(raw=len(f),retained=int(f.retained.sum()),excluded=len(f)-int(f.retained.sum()))
    assert response['totals']==counts(outgoing)
    grouped=outgoing.groupby(['PULocationID','DOLocationID']).retained.sum()
    expected=sorted([(int(o),int(d),int(n)) for (o,d),n in grouped.items() if n>=20],key=lambda v:(-v[2],v[0],v[1]))
    assert [(f['origin']['id'],f['destination']['id'],f['counts']['retained']) for f in response['pairs']]==expected[:10]
    assert response['eligiblePairs']==len(expected)
    for flow in response['pairs']:
        o,d=flow['origin']['id'],flow['destination']['id']
        f=outgoing[(outgoing.PULocationID==o)&(outgoing.DOLocationID==d)]
        assert flow['counts']==counts(f)
        reverse=frame[(frame.PULocationID==d)&(frame.DOLocationID==o)]
        assert flow['reverseRetained']==(None if o==d else int(reverse.retained.sum()))
        assert sum(s['counts']['retained'] for s in flow['reverseSources'])==(0 if o==d else int(reverse.retained.sum()))
        assert abs(flow['share']-f.retained.sum()/outgoing.retained.sum())<1e-12
        for w in flow['weeks']: assert w['counts']==counts(f[f.week==w['start']])
        assert sum(s['counts']['raw'] for s in flow['sources'])==len(f)
        full=[w for w in flow['weeks'] if w['completeWeek']]
        values=[int(f.loc[f.week==w['start'],'retained'].sum()) for w in full]
        qualifying=sum(n>=5 for n in values)
        peakShare=max(values)/sum(values) if sum(values) else None
        pattern='insufficient_history' if len(values)<3 else 'regular' if qualifying/len(values)>=0.75 else 'peak' if peakShare is not None and max(values)>=5 and peakShare>=0.5 else 'variable'
        assert flow['referenceWeeks']==len(values) and flow['qualifyingWeeks']==qualifying
        assert flow['peakWeekShare']==peakShare and flow['pattern']==pattern
    destinations=outgoing.groupby('DOLocationID').retained.sum()
    expectedDest=sorted([(int(d),int(n)) for d,n in destinations.items() if n>=20],key=lambda v:(-v[1],v[0]))
    assert [(d['zone']['id'],d['counts']['retained']) for d in response['destinations']]==expectedDest[:10]
    for dest in response['destinations']:
        assert sum(s['counts']['retained'] for s in dest['sources'])==dest['counts']['retained']
    checks.append({'scope':scope,'totals':response['totals'],'eligiblePairs':response['eligiblePairs'],'top':expected[:3]})
# Cas de validation de l'API, sans modification de la base.
for query,status in [
    ('zoneIds=181&borough=Brooklyn&from=2024-01-01&to=2024-02-01',400),
    ('zoneIds=9999&from=2024-01-01&to=2024-02-01',404),
    ('zoneIds=181&from=2024-01-01&to=2024-02-01&regularFraction=NaN',400),
    ('zoneIds=181&from=2024-02-01&to=2024-01-01',400),
    ('from=2024-01-01&to=2024-02-01',400)]:
    try:
        urllib.request.urlopen(args.api+'/api/flows?'+query)
        raise AssertionError('Erreur attendue : '+query)
    except urllib.error.HTTPError as error:
        assert error.code==status
for query in ['zoneIds=181,189&from=2024-01-01&to=2024-01-15',
              'zoneIds=181&from=2024-01-01&to=2024-02-02']:
    with urllib.request.urlopen(args.api+'/api/flows?'+query) as r: data=json.load(r)
    assert all(f['pattern']=='insufficient_history' for f in data['pairs'])
print(json.dumps({'verified':True,'sourceRows':2964624,'checks':checks},indent=2))
