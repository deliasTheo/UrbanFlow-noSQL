"""Vérification indépendante de F3 sur janvier complet ; API sur base janvier seul."""
import argparse
import json
from pathlib import Path
import statistics
import urllib.request
import urllib.error
import pandas as pd

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--api',default='http://127.0.0.1:8083')
args=p.parse_args()
root=Path(__file__).resolve().parents[1]
f=pd.read_parquet(root/'data/raw/yellow_tripdata_2024-01.parquet')
f['kept']=~((f.total_amount<0)|f.duplicated())
zones=pd.read_csv(root/'data/raw/taxi_zone_lookup.csv')
results=[]
def get(query):
    with urllib.request.urlopen(args.api+'/api/unusual-activity?'+query,timeout=180) as r: return json.load(r)
for scope,direction,start,end in [('zoneIds=132','pickup',0,24),('borough=Brooklyn','pickup',0,24),('zoneIds=132','dropoff',8,12)]:
    response=get(f'{scope}&direction={direction}&from=2024-01-22&to=2024-02-01&referenceFrom=2024-01-01&referenceTo=2024-01-22&startHour={start}&endHour={end}')
    time=f['tpep_'+direction+'_datetime']
    mask=(time>=pd.Timestamp('2024-01-01'))&(time<pd.Timestamp('2024-02-01'))&(time.dt.hour>=start)&(time.dt.hour<end)
    subset=f.loc[mask,['PULocationID','DOLocationID','kept']].copy()
    subset['date']=time[mask].dt.strftime('%Y-%m-%d')
    field='PULocationID' if direction=='pickup' else 'DOLocationID'
    grouped=subset.groupby([field,'date']).kept.agg(['size','sum'])
    city=subset.groupby('date').kept.agg(['size','sum'])
    def counts(zone,date):
        if (zone,date) not in grouped.index: return {'raw':0,'retained':0,'excluded':0}
        r=grouped.loc[(zone,date)];return {'raw':int(r['size']),'retained':int(r['sum']),'excluded':int(r['size']-r['sum'])}
    for day in response['cityCoverage']:
        r=city.loc[day['date']]
        assert day['counts']=={'raw':int(r['size']),'retained':int(r['sum']),'excluded':int(r['size']-r['sum'])}
    for c in response['observations']:
        zone=c['zone']['id'];date=c['observed']['date']
        expected=counts(zone,date);assert c['observed']['counts']==expected
        refs=[d.strftime('%Y-%m-%d') for d in pd.date_range('2024-01-01','2024-01-21')
              if d.weekday()==pd.Timestamp(date).weekday() and d.day not in [1,15]]
        assert [r['date'] for r in c['references']]==refs
        values=[counts(zone,d)['retained'] for d in refs]
        for r in c['references']: assert r['counts']==counts(zone,r['date'])
        median=statistics.median(values);mad=statistics.median([abs(n-median) for n in values])
        assert c['baselineMedian']==median and c['medianAbsoluteDeviation']==mad
        expectedRelative=None if median==0 else (expected['retained']-median)/median
        expectedScore=None if mad==0 else (expected['retained']-median)/(1.4826*mad)
        assert c['relativeChange']==expectedRelative and c['robustScore']==expectedScore
        globalMedian=statistics.median([int(city.loc[d,'size']) for d in refs])
        assert c['cityRatio']==int(city.loc[date,'size'])/globalMedian
        assert ('CITY_VOLUME_SHIFT' in c['warnings'])==(c['cityRatio']<0.5 or c['cityRatio']>2)
        assert ('HIGH_EXCLUSION_RATE' in c['warnings'])==(expected['raw']>0 and expected['excluded']/expected['raw']>0.2)
        status='INSUFFICIENT_REFERENCE' if len(refs)<3 else 'LOW_BASELINE' if median<20 else 'USUAL'
        if status=='USUAL':
            delta=expected['retained']-median
            if abs(delta)>=20 and abs(delta/median)>=0.5 and (mad==0 or abs(delta/(1.4826*mad))>=3): status='UNUSUAL'
        assert c['status']==status,(zone,date,c['status'],status)
        if status=='UNUSUAL': assert c['change']==('HIGHER' if expected['retained']>median else 'LOWER')
        assert sum(s['counts']['retained'] for s in c['observed']['sources'])==expected['retained']
    assert len(response['unusual'])==sum(c['status']=='UNUSUAL' for c in response['observations'])
    assert {d['date'] for d in response['excludedReferenceDays']}=={'2024-01-01','2024-01-15'}
    results.append({'scope':scope,'direction':direction,'startHour':start,'endHour':end,'cells':len(response['observations']),'unusual':len(response['unusual'])})
# Exclusions calendaires de journées entières et couverture : aucun faux résultat normal.
for date,to,status in [('2024-03-10','2024-03-11','DST_DAY_EXCLUDED'),('2024-11-03','2024-11-04','DST_DAY_EXCLUDED'),
                       ('2024-02-19','2024-02-20',"HOLIDAY_EXCLUDED: Washington's Birthday"),('2024-02-20','2024-02-21','SOURCE_MONTH_MISSING')]:
    d=get(f'zoneIds=132&from={date}&to={to}&referenceFrom=2024-01-01&referenceTo=2024-01-22')
    assert d['observations'][0]['status']==status and not d['unusual']
for q in ['zoneIds=132&from=2024-01-22&to=2024-02-01&referenceFrom=2024-01-01&referenceTo=2024-01-23',
          'zoneIds=132&from=2024-01-22&to=2024-02-01&referenceFrom=2024-01-01&referenceTo=2024-01-22&startHour=12&endHour=8']:
    try: get(q);raise AssertionError('400 attendu')
    except urllib.error.HTTPError as e: assert e.code==400
print(json.dumps({'verified':True,'sourceRows':len(f),'checks':results,'calendarAndCoverageChecks':True},indent=2))
