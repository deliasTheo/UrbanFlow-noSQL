"""Mesure F3 avant/après index dans une base dédiée, sans suppression d'index.
Lancer l'API sur cette même base et compiler backend/target/urbanflow-api-0.1.0.jar.
Nécessite pymongo ; --java doit désigner un JDK 21 (lanceur de source Java).
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import tempfile
import time
import urllib.request
import zipfile

from bson import json_util
from pymongo import MongoClient

ROOT = Path(__file__).resolve().parents[1]

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database', required=True)
    p.add_argument('--uri', default=os.environ.get('MONGODB_URI', 'mongodb://127.0.0.1:27018'))
    p.add_argument('--api', default='http://127.0.0.1:8083')
    p.add_argument('--java', default='java')
    p.add_argument('--output', default='results/performance/f3')
    args = p.parse_args()
    if not args.database.startswith('urbanflow_f3_benchmark'):
        p.error('Utiliser une base dédiée nommée urbanflow_f3_benchmark...')
    db = MongoClient(args.uri)[args.database]
    if list(db.trips.index_information()) != ['_id_']:
        p.error('La référence doit avoir uniquement _id_ : aucun index ne sera supprimé automatiquement.')
    imports = list(db.imports.find({'status':'complete'}))
    if not imports or any(d['file_month'] != '2024-01' for d in imports):
        p.error('Ce protocole attend janvier 2024 complet uniquement.')
    count = db.trips.count_documents({})
    if count != 2964624 or sum(d['num_rows'] for d in imports) != count:
        p.error('Janvier complet requis : 2 964 624 lignes.')
    out = ROOT / args.output
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(d['_id'] for d in imports)
    zones = sorted(d['_id'] for d in db.zones.find({'Borough':'Brooklyn'}))
    queries = {'zone132': ('zoneIds=132',[132]), 'brooklyn': ('borough=Brooklyn',zones)}
    results = {'database':args.database, 'documents':count, 'imports':files,
               'mongoVersion':db.command('buildInfo')['version'], 'platform':platform.platform(),
               'logicalCpus':os.cpu_count(), 'warmupCallsPerQueryPerPhase':1,
               'measuredCallsPerQueryPerPhase':3, 'cachePolicy':'Caches conservés ; aucune mesure à froid garantie.',
               'queries':{}, 'phases':{}}
    def request(url):
        start = time.perf_counter()
        with urllib.request.urlopen(url, timeout=150) as r:
            data = json.load(r)
        return time.perf_counter()-start, data
    def canonical(data):
        return json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    with tempfile.TemporaryDirectory(prefix='urbanflow-f2-java-') as tmp:
        with zipfile.ZipFile(ROOT/'backend/target/urbanflow-api-0.1.0.jar') as jar:
            jar.extractall(tmp)
        classpath = os.pathsep.join([str(Path(tmp)/'BOOT-INF/classes'),str(Path(tmp)/'BOOT-INF/lib/*')])
        pipelines = {}
        for name,(scope,ids) in queries.items():
            url=f'{args.api}/api/unusual-activity?{scope}&direction=pickup&from=2024-01-22&to=2024-02-01&referenceFrom=2024-01-01&referenceTo=2024-01-22'
            results['queries'][name]={'url':url}
            text=subprocess.check_output([args.java,'--class-path',classpath,str(ROOT/'scripts/ExportUnusualPipelines.java'),
                    ','.join(map(str,ids)),'pickup','2024-01-22','2024-02-01','2024-01-01','2024-01-22','0','24',','.join(files)],text=True)
            pipelines[name]=json_util.loads(text)
            (out/f'{name}-pipeline.json').write_text(text)
        baseline={}
        for phase in ['withoutIndexes','withIndexes']:
            if phase=='withIndexes':
                start=time.perf_counter()
                db.trips.create_index([('data.PULocationID',1),('data.tpep_pickup_datetime',1)],name='f1_pickup_zone_datetime')
                db.trips.create_index([('data.DOLocationID',1),('data.tpep_dropoff_datetime',1)],name='f1_dropoff_zone_datetime')
                results['indexCreationSeconds']=time.perf_counter()-start
            results['phases'][phase]={'indexInformation':db.trips.index_information(),
                    'collectionStats':db.command('collStats','trips'), 'measurements':{}}
            for name in queries:
                url=results['queries'][name]['url']
                warmup,data=request(url)
                assert sorted(data['sourceFiles'])==files, 'API et base de mesure incohérentes'
                timings=[]
                for _ in range(3):
                    seconds,current=request(url)
                    assert current==data, f'Réponses instables : {name}'
                    timings.append(seconds)
                if phase=='withoutIndexes': baseline[name]=data
                else: assert data==baseline[name], f'Réponse différente après index : {name}'
                (out/f'{name}-{phase}-response.json').write_bytes(canonical(data))
                results['phases'][phase]['measurements'][name]={
                    'warmupSeconds':warmup,'seconds':timings,'medianSeconds':statistics.median(timings),
                    'minSeconds':min(timings),'maxSeconds':max(timings),'stdevSeconds':statistics.stdev(timings),
                    'responseSha256':hashlib.sha256(canonical(data)).hexdigest()}
                for part,pipeline in pipelines[name].items():
                    explain=db.command('explain', {'aggregate':'trips','pipeline':pipeline, 'cursor':{},
                        'allowDiskUse':True,'maxTimeMS':120000}, verbosity='executionStats')
                    (out/f'{name}-{phase}-{part}-explain.json').write_text(json_util.dumps(explain,indent=2))
                print(phase,name,timings,flush=True)
            (out/'measurements.json').write_text(json_util.dumps(results,indent=2))
    print('Réponses strictement identiques sans/avec index. Résultats :',out)

if __name__=='__main__': main()
