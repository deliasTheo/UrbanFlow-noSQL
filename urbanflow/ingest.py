"""Import des fichiers TLC dans MongoDB. C'est aussi le service F6.

Deux façons de l'appeler :
    python -m urbanflow.ingest --month 2024-04
    python -m urbanflow.ingest --file extrait.parquet

Identité d'un trajet
--------------------
La source n'a pas d'identifiant. On construit donc celui-ci :

    heure de départ | empreinte de toutes les colonnes : rang

Le rang compte les lignes identiques à l'intérieur du fichier. Deux vrais
trajets identiques dans un fichier ont donc des rangs 0 et 1 et sont gardés
tous les deux. Réimporter le fichier redonne les mêmes identifiants : MongoDB
refuse les insertions et rien ne change. Un extrait qui recoupe un fichier
déjà importé ne crée pas non plus de doublon pour les lignes communes.
"""

import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
from pymongo import MongoClient, UpdateOne
from pymongo.errors import BulkWriteError

from urbanflow import config
from urbanflow.download import sha256_of
from urbanflow.quality import ANOMALY_CODES, PROFILES, flag_trips, usable_mask

DUPLICATE_KEY = 11000


def manifest_entry(name):
    entry = json.loads(config.MANIFEST_PATH.read_text())["files"][name]
    if sha256_of(config.RAW_DIR / name) != entry["sha256"]:
        raise ValueError(f"Empreinte incorrecte : {name}")
    return entry


def outside_entry(path):
    """Fichier absent du manifeste, par exemple un extrait fourni à la soutenance."""
    return {
        "url": None,
        "retrieved_at": None,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_of(path),
        "num_rows": pq.ParquetFile(path).metadata.num_rows,
    }


def value_for_mongo(value):
    return None if pd.isna(value) else value


def trip_identity(trips):
    """Empreinte du contenu et rang parmi les lignes identiques, pour chaque ligne."""
    # Les types sont forcés pour qu'une même ligne donne la même empreinte même
    # si un extrait a été écrit avec d'autres types que le fichier d'origine.
    canonical = pd.DataFrame(index=trips.index)
    for name in sorted(trips.columns, key=str.lower):
        column = trips[name]
        if pd.api.types.is_datetime64_any_dtype(column):
            canonical[name] = column.astype("datetime64[ns]").astype("int64")
        elif pd.api.types.is_numeric_dtype(column):
            canonical[name] = column.astype("float64")
        else:
            canonical[name] = column.astype(str)

    hashes = pd.util.hash_pandas_object(canonical, index=False)
    ranks = hashes.groupby(hashes).cumcount()
    return hashes.to_numpy(), ranks.to_numpy()


def column_values(column):
    """Valeurs d'une colonne pour MongoDB, avec None à la place de NaN et NaT."""
    if pd.api.types.is_datetime64_any_dtype(column):
        column = column.dt.strftime("%Y-%m-%dT%H:%M:%S")
    return column.astype(object).where(column.notna(), None).tolist()


def documents(trips, flags, file_id, start, stop, identity=None):
    """Documents des lignes start à stop. Les flags portent sur le fichier entier."""
    if identity is None:
        identity = trip_identity(trips)
    hashes, ranks = identity

    batch = trips.iloc[start:stop]
    columns = {name: column_values(batch[name]) for name in batch.columns}
    durations = flags["duration_s"].iloc[start:stop].to_numpy()
    unresolved = flags["DST_UNRESOLVED"].iloc[start:stop].to_numpy()
    flag_values = [(code, flags[code].iloc[start:stop].to_numpy()) for code in ANOMALY_CODES]

    for i in range(stop - start):
        row = start + i
        data = {name: values[i] for name, values in columns.items()}
        duration = durations[i]
        yield {
            "_id": f"{data['tpep_pickup_datetime']}|{hashes[row]:016x}:{ranks[row]}",
            "source": {"file_id": file_id, "row_number": row},
            "data": data,
            "duration_s": None if unresolved[i] or pd.isna(duration) else float(duration),
            "quality_flags": [code for code, values in flag_values if values[i]],
        }


def insert_batch(db, docs):
    """Insère un lot et renvoie le nombre de lignes vraiment ajoutées."""
    try:
        return len(db.trips.insert_many(docs, ordered=False).inserted_ids)
    except BulkWriteError as error:
        # Un identifiant déjà présent est normal : c'est ce qui empêche les doublons.
        for write_error in error.details["writeErrors"]:
            if write_error["code"] != DUPLICATE_KEY:
                raise
        return error.details["nInserted"]


def import_zones(db):
    entry = manifest_entry(config.ZONE_LOOKUP_FILE)
    zones = pd.read_csv(config.RAW_DIR / config.ZONE_LOOKUP_FILE)
    operations = []
    for _, row in zones.iterrows():
        fields = {col: value_for_mongo(v) for col, v in row.items() if col != "LocationID"}
        fields["source"] = {"file_id": entry["sha256"], "file_name": config.ZONE_LOOKUP_FILE}
        operations.append(UpdateOne({"_id": int(row.LocationID)}, {"$set": fields}, upsert=True))
    db.zones.bulk_write(operations)


def check_archive(db):
    """Le nombre de documents doit valoir la somme des imports, sans relire la collection."""
    if db.imports.count_documents({"status": {"$ne": "complete"}}):
        return  # un import inachevé a pu laisser des lignes : le total ne dirait rien
    expected = sum(doc["summary"]["inserted"] for doc in db.imports.find({}, {"summary.inserted": 1}))
    if db.trips.estimated_document_count() != expected:
        raise ValueError("Import déclaré complet mais effectif incorrect")


def ingest(db, path, entry, file_month, batch_size=5000):
    """Importe un fichier. Sans effet s'il a déjà été importé en entier."""
    if batch_size <= 0:
        raise ValueError("La taille de lot doit être positive")
    file_id = entry["sha256"]

    previous = db.imports.find_one({"_id": file_id})
    if previous and previous.get("status") == "complete":
        check_archive(db)
        print(f"{path.name} : déjà importé, aucun changement")
        return previous["summary"]

    # Reprise après une interruption : ces lignes sont déjà là et comptent pour ce fichier.
    already_stored = db.trips.count_documents({"source.file_id": file_id}) if previous else 0

    started = time.perf_counter()
    import_zones(db)
    db.imports.update_one({"_id": file_id}, {"$set": {
        **entry, "file_name": path.name, "file_month": file_month, "status": "loading",
        "started_at": datetime.now(timezone.utc),
    }, "$unset": {"error_type": "", "finished_at": ""}}, upsert=True)

    try:
        trips = pd.read_parquet(path)
        if len(trips) != entry["num_rows"]:
            raise ValueError("Effectif source différent du manifeste")
        flags = flag_trips(trips, file_month)
        identity = trip_identity(trips)

        documents_before = db.trips.estimated_document_count()
        inserted_now = 0
        for start in range(0, len(trips), batch_size):
            stop = min(start + batch_size, len(trips))
            inserted_now += insert_batch(db, list(documents(trips, flags, file_id, start, stop, identity)))
            if stop == len(trips) or stop % 500000 == 0:
                print(f"{path.name} : {stop:,}/{len(trips):,}", flush=True)

        added = db.trips.estimated_document_count() - documents_before
        if added != inserted_now:
            raise ValueError(f"{inserted_now} insertions annoncées, mais {added} documents en plus")
        inserted = already_stored + inserted_now

        summary = {
            "file": path.name,
            "file_id": file_id,
            "num_rows": len(trips),
            "inserted": inserted,
            "already_present": len(trips) - inserted,
            "seconds": round(time.perf_counter() - started, 1),
            "anomalies": {code: int(flags[code].sum()) for code in ANOMALY_CODES},
            "profiles": {p.name: int(usable_mask(flags, p).sum()) for p in PROFILES},
        }
        db.imports.update_one({"_id": file_id}, {"$set": {
            "status": "complete", "finished_at": datetime.now(timezone.utc), "summary": summary,
        }})
        return summary
    except Exception as error:
        db.imports.update_one({"_id": file_id}, {"$set": {"status": "failed", "error_type": type(error).__name__}})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--month", help="mois complet du manifeste, au format AAAA-MM")
    parser.add_argument("--file", help="chemin d'un fichier Parquet hors manifeste (extrait)")
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--database", default="urbanflow")
    args = parser.parse_args()

    if args.month and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", args.month):
        parser.error("--month attend le format AAAA-MM")
    if not args.month and not args.file:
        parser.error("il faut --month ou --file")

    if args.file:
        # Avec --file, --month indique que le fichier couvre le mois entier.
        # Sans --month, le fichier est un extrait et ne compte pas comme un mois complet.
        path = Path(args.file)
        if not path.is_file():
            parser.error(f"fichier introuvable : {path}")
        entry = outside_entry(path)
    else:
        path = config.RAW_DIR / config.trip_file_name(args.month)
        if path.name not in json.loads(config.MANIFEST_PATH.read_text())["files"] or not path.is_file():
            parser.error(f"{path.name} n'est pas disponible : lancer d'abord urbanflow.download")
        entry = manifest_entry(path.name)

    uri = os.environ.get("MONGODB_URI", "mongodb://127.0.0.1:27018")
    with MongoClient(uri, serverSelectionTimeoutMS=10000) as client:
        client.admin.command("ping")
        summary = ingest(client[args.database], path, entry, args.month, args.batch_size)

    # Le résumé d'un extrait est dans imports : il ne remplace pas celui d'un mois.
    if not args.file:
        output = config.RESULTS_DIR / "ingestion"
        output.mkdir(parents=True, exist_ok=True)
        (output / f"{args.month}.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
