"""Mesure F2 avant/après index dans une base dédiée, sans suppression d'index.
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


def request(url):
    """Appelle l'API et renvoie la durée de l'appel et la réponse."""
    start = time.perf_counter()
    with urllib.request.urlopen(url, timeout=150) as reply:
        data = json.load(reply)
    return time.perf_counter() - start, data


def canonical(data):
    """Forme stable d'une réponse, pour pouvoir la comparer et calculer son empreinte."""
    return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--uri', default=os.environ.get('MONGODB_URI', 'mongodb://127.0.0.1:27018'))
    parser.add_argument('--api', default='http://127.0.0.1:8081')
    parser.add_argument('--java', default='java')
    parser.add_argument('--output', default='results/performance/f2')
    args = parser.parse_args()

    # La mesure n'a de sens que sur une base dédiée, sans index, avec janvier complet.
    if not args.database.startswith('urbanflow_f2_benchmark'):
        parser.error('Utiliser une base dédiée nommée urbanflow_f2_benchmark...')
    db = MongoClient(args.uri)[args.database]
    if list(db.trips.index_information()) != ['_id_']:
        parser.error('La référence doit avoir uniquement _id_ : aucun index ne sera supprimé automatiquement.')
    imports = list(db.imports.find({'status': 'complete'}))
    if not imports or any(doc['file_month'] != '2024-01' for doc in imports):
        parser.error('Ce protocole attend janvier 2024 complet uniquement.')
    count = db.trips.count_documents({})
    if count != 2964624 or sum(doc['num_rows'] for doc in imports) != count:
        parser.error('Janvier complet requis : 2 964 624 lignes.')

    output_dir = ROOT / args.output
    output_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(doc['_id'] for doc in imports)
    zones = sorted(doc['_id'] for doc in db.zones.find({'Borough': 'Brooklyn'}))
    queries = {'zone181': ('zoneIds=181', [181]), 'brooklyn': ('borough=Brooklyn', zones)}
    results = {
        'database': args.database,
        'documents': count,
        'imports': files,
        'mongoVersion': db.command('buildInfo')['version'],
        'platform': platform.platform(),
        'logicalCpus': os.cpu_count(),
        'warmupCallsPerQueryPerPhase': 1,
        'measuredCallsPerQueryPerPhase': 3,
        'cachePolicy': 'Caches conservés ; aucune mesure à froid garantie.',
        'queries': {},
        'phases': {},
    }

    with tempfile.TemporaryDirectory(prefix='urbanflow-f2-java-') as temp_dir:
        # Les classes du jar servent à générer le pipeline réellement envoyé par l'API.
        with zipfile.ZipFile(ROOT / 'backend/target/urbanflow-api-0.1.0.jar') as jar:
            jar.extractall(temp_dir)
        classpath = os.pathsep.join([str(Path(temp_dir) / 'BOOT-INF/classes'), str(Path(temp_dir) / 'BOOT-INF/lib/*')])

        pipelines = {}
        for name, (scope, zone_ids) in queries.items():
            url = f'{args.api}/api/flows?{scope}&from=2024-01-01&to=2024-02-01'
            results['queries'][name] = {'url': url}
            pipeline_text = subprocess.check_output(
                [
                    args.java, '--class-path', classpath, str(ROOT / 'scripts/ExportFlowPipeline.java'),
                    ','.join(map(str, zone_ids)), '2024-01-01', '2024-02-01', ','.join(files),
                ],
                text=True,
            )
            pipelines[name] = json_util.loads(pipeline_text)
            (output_dir / f'{name}-pipeline.json').write_text(pipeline_text)

        baseline = {}
        for phase in ['withoutIndexes', 'withIndexes']:
            if phase == 'withIndexes':
                start = time.perf_counter()
                db.trips.create_index(
                    [('data.PULocationID', 1), ('data.tpep_pickup_datetime', 1)], name='f1_pickup_zone_datetime')
                db.trips.create_index(
                    [('data.DOLocationID', 1), ('data.tpep_dropoff_datetime', 1)], name='f1_dropoff_zone_datetime')
                results['indexCreationSeconds'] = time.perf_counter() - start

            results['phases'][phase] = {
                'indexInformation': db.trips.index_information(),
                'collectionStats': db.command('collStats', 'trips'),
                'measurements': {},
            }

            for name in queries:
                url = results['queries'][name]['url']
                # Le premier appel sert d'échauffement, il n'entre pas dans les mesures.
                warmup, response = request(url)
                assert sorted(source['fileId'] for source in response['sources']) == files, 'API et base de mesure incohérentes'

                timings = []
                for _ in range(3):
                    seconds, repeated = request(url)
                    assert repeated == response, f'Réponses instables : {name}'
                    timings.append(seconds)

                # Un index ne doit changer que le temps, jamais la réponse.
                if phase == 'withoutIndexes':
                    baseline[name] = response
                else:
                    assert response == baseline[name], f'Réponse différente après index : {name}'

                (output_dir / f'{name}-{phase}-response.json').write_bytes(canonical(response))
                results['phases'][phase]['measurements'][name] = {
                    'warmupSeconds': warmup,
                    'seconds': timings,
                    'medianSeconds': statistics.median(timings),
                    'minSeconds': min(timings),
                    'maxSeconds': max(timings),
                    'stdevSeconds': statistics.stdev(timings),
                    'responseSha256': hashlib.sha256(canonical(response)).hexdigest(),
                }

                explain = db.command(
                    'explain',
                    {'aggregate': 'trips', 'pipeline': pipelines[name], 'cursor': {}, 'allowDiskUse': True, 'maxTimeMS': 120000},
                    verbosity='executionStats',
                )
                (output_dir / f'{name}-{phase}-explain.json').write_text(json_util.dumps(explain, indent=2))
                print(phase, name, timings, flush=True)

            # Écrit après chaque phase : un arrêt ne perd pas les phases déjà faites.
            (output_dir / 'measurements.json').write_text(json_util.dumps(results, indent=2))

    print('Réponses strictement identiques sans/avec index. Résultats :', output_dir)


if __name__ == '__main__':
    main()
