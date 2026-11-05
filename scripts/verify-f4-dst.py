"""Exerce F4 sur de vraies lignes TLC de mars dans une base temporaire supprimée.
Ce sous-ensemble n'est pas une validation de couverture du mois de mars.
"""
import argparse
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request
import pandas as pd
import pyarrow.parquet as pq
from pymongo import MongoClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from urbanflow.quality import flag_trips
from urbanflow.ingest import documents, value_for_mongo

p=argparse.ArgumentParser(description=__doc__);p.add_argument('--java',default='java');p.add_argument('--port',type=int,default=8085);args=p.parse_args()
root=Path(__file__).resolve().parents[1]
parts=[];offset=0
for batch in pq.ParquetFile(root/'data/raw/yellow_tripdata_2024-03.parquet').iter_batches(batch_size=65536):
 frame=batch.to_pandas();frame.index=pd.RangeIndex(offset,offset+len(frame));offset+=len(frame)
 mask=((frame.tpep_pickup_datetime>=pd.Timestamp('2024-03-10'))&(frame.tpep_pickup_datetime<pd.Timestamp('2024-03-11'))) | ((frame.tpep_dropoff_datetime>=pd.Timestamp('2024-03-10'))&(frame.tpep_dropoff_datetime<pd.Timestamp('2024-03-11')))
 if mask.any():parts.append(frame[mask])
day=pd.concat(parts);source_rows=day.index.to_list();day=day.reset_index(drop=True)
flags=flag_trips(day,'2024-03')
span=flags.index[flags.DST_SPANNING&~flags[['NEGATIVE_AMOUNT','EXACT_DUPLICATE','UNKNOWN_ZONE','NON_POSITIVE_DURATION','EXCESSIVE_DURATION','ZERO_DISTANCE','IMPLAUSIBLE_DISTANCE','IMPLAUSIBLE_SPEED','DST_UNRESOLVED']].any(axis=1)][0]
unresolved=flags.index[flags.DST_UNRESOLVED][0]
file='yellow_tripdata_2024-03.parquet';file_id=json.loads((root/'data/manifest.json').read_text())['files'][file]['sha256']
records=[]
for i in [span,unresolved]:
 doc=next(documents(day,flags,file_id,int(i),int(i)+1));row=source_rows[i]
 doc['_id']=f'{file_id}:{row}';doc['source']['row_number']=row;records.append(doc)
client=MongoClient(os.environ.get('MONGODB_URI','mongodb://127.0.0.1:27018'));name='urbanflow_f4_dst_check'
assert name not in client.list_database_names(),'Base temporaire déjà présente'
db=client[name];process=None
try:
 db.trips.insert_many(records)
 lookup=pd.read_csv(root/'data/raw/taxi_zone_lookup.csv')
 db.zones.insert_many([{'_id':int(r.LocationID),'Borough':value_for_mongo(r.Borough),'Zone':value_for_mongo(r.Zone)} for r in lookup.itertuples()])
 db.imports.insert_one({'_id':file_id,'file_name':file,'file_month':'2024-03','status':'complete','verification_subset':True,'num_rows':len(records)})
 env={**os.environ,'MONGODB_DATABASE':name,'PORT':str(args.port)}
 with open(Path(tempfile.gettempdir())/'urbanflow-f4-dst-api.log','w') as log:
  process=subprocess.Popen([args.java,'-jar',str(root/'backend/target/urbanflow-api-0.1.0.jar')],env=env,stdout=log,stderr=log)
  url=f'http://127.0.0.1:{args.port}'
  for _ in range(100):
   try:
    urllib.request.urlopen(url+'/api/zones',timeout=1).close();break
   except (OSError,urllib.error.URLError):time.sleep(.2)
  else:raise RuntimeError('API non disponible')
  checks=[]
  for i,doc in zip([span,unresolved],records):
   r=day.iloc[i];pu=r.tpep_pickup_datetime.tz_localize('America/New_York',ambiguous='NaT',nonexistent='NaT');do=r.tpep_dropoff_datetime.tz_localize('America/New_York',ambiguous='NaT',nonexistent='NaT')
   real=None if pd.isna(pu) or pd.isna(do) else (do.tz_convert('UTC')-pu.tz_convert('UTC')).total_seconds()
   assert doc['duration_s']==real
   start=r.tpep_pickup_datetime.normalize().date();end=start+timedelta(days=1)
   query=f'/api/journeys?originId={int(r.PULocationID)}&destinationId={int(r.DOLocationID)}&from={start}&to={end}&referenceFrom=2024-01-01&referenceTo=2024-01-02'
   with urllib.request.urlopen(url+query,timeout=15) as response:data=json.load(response)
   if i==span:
    assert data['current']['dstSpanningRetained']>=1
    assert data['current']['usable']['durationSeconds']['median']==real
    assert real!=(r.tpep_dropoff_datetime-r.tpep_pickup_datetime).total_seconds()
   else:
    assert data['current']['exclusionReasons']['DST_UNRESOLVED']>=1
    assert doc['duration_s'] is None
   checks.append({'source':doc['source'],'pickup':str(r.tpep_pickup_datetime),'dropoff':str(r.tpep_dropoff_datetime),'realDurationSeconds':real,'naiveDurationSeconds':(r.tpep_dropoff_datetime-r.tpep_pickup_datetime).total_seconds(),'flags':doc['quality_flags']})
  print(json.dumps({'verified':True,'fixture':'Deux lignes originales de mars ; import complete simulé uniquement dans cette base de test','checks':checks},indent=2))
finally:
 if process is not None:
  process.terminate();process.wait(timeout=15)
 client.drop_database(name)
