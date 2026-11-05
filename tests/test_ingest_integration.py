"""Test explicite : URBANFLOW_INTEGRATION=1 python -m unittest discover -s tests -v."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

import pandas as pd
import pyarrow.parquet as pq
from pymongo import MongoClient

from urbanflow import config, ingest
from urbanflow.download import sha256_of


@unittest.skipUnless(os.environ.get('URBANFLOW_INTEGRATION') == '1', 'MongoDB et sources locales requis')
class MongoImportTest(unittest.TestCase):
    def test_resume_and_idempotence(self):
        # Petit extrait réel ; répétition d'une ligne uniquement pour tester la qualité.
        source = config.RAW_DIR / config.trip_file_name('2024-01')
        rows = next(pq.ParquetFile(source).iter_batches(batch_size=3)).to_pandas()
        rows = pd.concat([rows, rows.iloc[[0]]], ignore_index=True)
        with tempfile.TemporaryDirectory() as folder, MongoClient('mongodb://127.0.0.1:27017') as client:
            root = Path(folder)
            path = root / source.name
            rows.to_parquet(path, index=False)
            zones = root / config.ZONE_LOOKUP_FILE
            zones.write_bytes((config.RAW_DIR / config.ZONE_LOOKUP_FILE).read_bytes())
            entries = {p.name: {'sha256': sha256_of(p)} for p in (path, zones)}
            entries[path.name]['num_rows'] = len(rows)
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps({'files': entries}))
            db = client['urbanflow_test_' + uuid4().hex]
            original = ingest.documents
            def interrupted(*args):
                if args[3] >= 2:
                    raise RuntimeError('Interruption simulée')
                return original(*args)
            try:
                with patch.object(config, 'RAW_DIR', root), patch.object(config, 'MANIFEST_PATH', manifest):
                    with patch.object(ingest, 'documents', interrupted):
                        with self.assertRaises(RuntimeError):
                            ingest.ingest(db, '2024-01', 2)
                    self.assertEqual(db.trips.count_documents({}), 2)
                    self.assertEqual(db.imports.find_one({})['status'], 'failed')
                    summary = ingest.ingest(db, '2024-01', 1)
                    before = list(db.trips.find().sort('_id', 1))
                    self.assertEqual(len(before), 4)
                    self.assertEqual(summary['anomalies']['EXACT_DUPLICATE'], 1)
                    self.assertEqual(ingest.ingest(db, '2024-01', 3), summary)
                    self.assertEqual(list(db.trips.find().sort('_id', 1)), before)
                    self.assertEqual(db.ingestion_lock.count_documents({}), 0)
            finally:
                client.drop_database(db.name)
