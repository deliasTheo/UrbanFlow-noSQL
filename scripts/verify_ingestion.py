"""Vérifie janvier en base contre les sources et le rapport qualité versionné."""
import json
import os
import pandas as pd
from pymongo import MongoClient
from urbanflow import config
from urbanflow.ingest import value_for_mongo


def main():
    name = config.trip_file_name('2024-01')
    reference = next(r for r in json.loads((config.RESULTS_DIR/'quality/quality_report.json').read_text()) if r['file'] == name)
    manifest = json.loads(config.MANIFEST_PATH.read_text())['files'][name]
    with MongoClient(os.environ.get('MONGODB_URI', 'mongodb://127.0.0.1:27017')) as client:
        db = client.urbanflow
        file_id = manifest['sha256']
        match = {'source.file_id': file_id}
        assert db.imports.find_one({'_id': file_id})['status'] == 'complete'
        assert db.trips.count_documents(match) == reference['num_rows']
        assert db.zones.count_documents({}) == 265
        counts = {r['_id']: r['n'] for r in db.trips.aggregate([
            {'$match': match}, {'$unwind': '$quality_flags'},
            {'$group': {'_id': '$quality_flags', 'n': {'$sum': 1}}},
        ])}
        for code, expected in reference['anomalies'].items():
            assert counts.get(code, 0) == expected['count'], code
        raw = pd.read_parquet(config.RAW_DIR/name)
        for row in [0, 256, len(raw)-1]:
            doc = db.trips.find_one({'_id': f'{file_id}:{row}'})
            assert set(doc) == {'_id', 'source', 'data', 'duration_s', 'quality_flags'}
            assert doc['data'] == {col: value_for_mongo(v) for col, v in raw.iloc[row].items()}
        print(f"Vérification réussie : {len(raw):,} lignes, 265 zones, flags et exemples sources conformes.")


if __name__ == '__main__':
    main()
