"""Import direct des fichiers TLC dans MongoDB (serveur Docker ou URI fournie)."""

import argparse
import json
import math
import os
import re
from datetime import datetime, timezone

import pandas as pd
from pymongo import MongoClient, UpdateOne

from urbanflow import config
from urbanflow.download import sha256_of
from urbanflow.quality import ANOMALY_CODES, PROFILES, flag_trips, usable_mask


def source_entry(name):
    entry = json.loads(config.MANIFEST_PATH.read_text())["files"][name]
    if sha256_of(config.RAW_DIR / name) != entry["sha256"]:
        raise ValueError(f"Empreinte incorrecte : {name}")
    return entry


def value_for_mongo(value):
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Valeur numérique infinie dans la source")
    return value


def documents(trips, flags, file_id, start, stop):
    """Les flags sont calculés sur le fichier entier, avant découpage en lots."""
    columns = trips.columns
    for row, values in enumerate(trips.iloc[start:stop].itertuples(index=False, name=None), start):
        duration = flags.at[row, "duration_s"]
        yield {
            "_id": f"{file_id}:{row}",
            "source": {"file_id": file_id, "row_number": row},
            "data": {col: value_for_mongo(v) for col, v in zip(columns, values)},
            "duration_s": None if flags.at[row, "DST_UNRESOLVED"] or pd.isna(duration) else float(duration),
            "quality_flags": [code for code in ANOMALY_CODES if flags.at[row, code]],
        }


def ingest(db, month, batch_size=5000):
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month) or batch_size <= 0:
        raise ValueError("Mois AAAA-MM et taille de lot positive requis")
    # Un seul processus d'ingestion à la fois par base. Verrou global sans expiration
    # pour ne pas reprendre un import lent encore actif.
    db.ingestion_lock.insert_one({"_id": "writer", "started_at": datetime.now(timezone.utc)})
    try:
        return _ingest(db, month, batch_size)
    finally:
        db.ingestion_lock.delete_one({"_id": "writer"})


def _ingest(db, month, batch_size):
    name = config.trip_file_name(month)
    entry = source_entry(name)
    file_id = entry["sha256"]
    db.trips.create_index("source.file_id")
    previous = db.imports.find_one({"_id": file_id})
    if previous and previous.get("status") == "complete":
        if db.trips.count_documents({"source.file_id": file_id}) != entry["num_rows"]:
            raise ValueError("Import déclaré complet mais effectif incorrect")
        print(f"{name} : déjà importé, aucun changement")
        return previous["summary"]
    zones_entry = source_entry(config.ZONE_LOOKUP_FILE)
    zones = pd.read_csv(config.RAW_DIR / config.ZONE_LOOKUP_FILE)
    db.zones.bulk_write([
        UpdateOne({"_id": int(row.LocationID)}, {"$set": {
            **{col: value_for_mongo(v) for col, v in row.items() if col != 'LocationID'},
            "source": {"file_id": zones_entry["sha256"], "file_name": config.ZONE_LOOKUP_FILE},
        }}, upsert=True) for _, row in zones.iterrows()
    ])
    db.imports.update_one({"_id": file_id}, {"$set": {
        **entry, "file_name": name, "file_month": month, "status": "loading",
        "started_at": datetime.now(timezone.utc),
    }, "$unset": {"error_type": "", "finished_at": ""}}, upsert=True)
    try:
        trips = pd.read_parquet(config.RAW_DIR / name)
        if len(trips) != entry["num_rows"]:
            raise ValueError("Effectif source différent du manifeste")
        flags = flag_trips(trips, month)
        for start in range(0, len(trips), batch_size):
            stop = min(start + batch_size, len(trips))
            db.trips.bulk_write([
                UpdateOne({"_id": doc["_id"]}, {"$setOnInsert": doc}, upsert=True)
                for doc in documents(trips, flags, file_id, start, stop)
            ], ordered=False)
            if start == 0 or stop == len(trips) or stop % 100000 == 0:
                print(f"{name} : {stop:,}/{len(trips):,}", flush=True)
        count = db.trips.count_documents({"source.file_id": file_id})
        if count != len(trips):
            raise ValueError("Effectif en base incorrect")
        summary = {
            "file": name, "file_id": file_id, "num_rows": count,
            "anomalies": {c: int(flags[c].sum()) for c in ANOMALY_CODES},
            "profiles": {p.name: int(usable_mask(flags, p).sum()) for p in PROFILES},
        }
        db.imports.update_one({"_id": file_id}, {"$set": {
            "status": "complete", "finished_at": datetime.now(timezone.utc), "summary": summary,
        }})
        return summary
    except Exception as exc:
        db.imports.update_one({"_id": file_id}, {"$set": {"status": "failed", "error_type": type(exc).__name__}})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--month', required=True)
    parser.add_argument('--batch-size', type=int, default=5000)
    parser.add_argument('--database', default='urbanflow')
    args = parser.parse_args()
    with MongoClient(os.environ.get('MONGODB_URI', 'mongodb://127.0.0.1:27017'), serverSelectionTimeoutMS=10000) as client:
        client.admin.command('ping')
        summary = ingest(client[args.database], args.month, args.batch_size)
        output = config.RESULTS_DIR / 'ingestion'
        output.mkdir(parents=True, exist_ok=True)
        (output / f'{args.month}.json').write_text(json.dumps(summary, indent=2) + '\n')
        print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
