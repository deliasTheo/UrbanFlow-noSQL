"""Vérifie le service F6 sur de vraies lignes TLC, dans une base de test à part.

Le script découpe de vrais fichiers en petits extraits et contrôle trois choses :
  1. un même fichier importé deux fois ne change rien ;
  2. un extrait qui recoupe un fichier déjà importé n'ajoute que les lignes nouvelles ;
  3. deux lignes identiques d'un même fichier sont gardées toutes les deux.

Sur un cluster, lancer d'abord urbanflow.deploy --database urbanflow_f6_test.

Usage :
    python scripts/verify-f6.py
    MONGODB_URI=mongodb://127.0.0.1:27019 python scripts/verify-f6.py --keep-database
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import pandas as pd
from pymongo import MongoClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from urbanflow.ingest import ingest, outside_entry  # noqa: E402

TEST_DATABASE = "urbanflow_f6_test"


def write_extract(frame, folder, name):
    path = Path(folder) / name
    frame.to_parquet(path, index=False)
    return path


def import_extract(db, path):
    return ingest(db, path, outside_entry(path), None)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep-database", action="store_true", help="ne pas supprimer la base (cluster préparé à l'avance)")
    args = parser.parse_args()

    uri = os.environ.get("MONGODB_URI", "mongodb://127.0.0.1:27018")
    client = MongoClient(uri)
    db = client[TEST_DATABASE]
    db.trips.delete_many({})
    db.imports.delete_many({})

    april = pd.read_parquet(ROOT / "data/raw/yellow_tripdata_2024-04.parquet")
    february = pd.read_parquet(ROOT / "data/raw/yellow_tripdata_2024-02.parquet")

    results = {}
    with tempfile.TemporaryDirectory() as folder:
        # Premier import : les lignes 0 à 19 999 d'avril.
        first = write_extract(april.iloc[0:20000], folder, "avril_a.parquet")
        summary = import_extract(db, first)
        assert summary["inserted"] == 20000 and summary["already_present"] == 0
        count = db.trips.count_documents({})
        assert count == 20000

        # Le même fichier une deuxième fois : aucun changement.
        import_extract(db, first)
        assert db.trips.count_documents({}) == count
        results["meme_fichier_deux_fois"] = {"documents_avant": count, "documents_apres": db.trips.count_documents({})}

        # Même contenu sous un autre nom, écrit dans un autre ordre : toujours rien de nouveau.
        renamed = april.iloc[0:20000].sample(frac=1, random_state=1)
        second = write_extract(renamed, folder, "avril_a_renomme.parquet")
        summary = import_extract(db, second)
        assert summary["inserted"] == 0 and summary["already_present"] == 20000
        results["meme_contenu_autre_nom"] = {"lignes_nouvelles": summary["inserted"], "deja_presentes": summary["already_present"]}

        # Extrait à cheval : 10 000 lignes déjà là, 10 000 nouvelles.
        third = write_extract(april.iloc[10000:30000], folder, "avril_b.parquet")
        summary = import_extract(db, third)
        assert summary["inserted"] == 10000 and summary["already_present"] == 10000
        assert db.trips.count_documents({}) == 30000
        results["extrait_a_cheval"] = {"lignes_nouvelles": summary["inserted"], "deja_presentes": summary["already_present"]}

        # Vraie ligne en double dans février : les deux copies doivent rester.
        copies = february[february.duplicated(keep=False)]
        assert len(copies) == 2, "février contient une seule paire de lignes identiques"
        before = db.trips.count_documents({})
        fourth = write_extract(copies, folder, "fevrier_doublon.parquet")
        summary = import_extract(db, fourth)
        assert summary["inserted"] == 2
        assert db.trips.count_documents({}) == before + 2
        stored = list(db.trips.find({"source.file_id": summary["file_id"]}, {"_id": 1, "quality_flags": 1}))
        assert sorted(doc["_id"].rsplit(":", 1)[1] for doc in stored) == ["0", "1"]
        flagged = [doc for doc in stored if "EXACT_DUPLICATE" in doc["quality_flags"]]
        assert len(flagged) == 1
        results["vrais_doublons"] = {"identifiants": [doc["_id"] for doc in stored]}

        # Un extrait n'annonce pas de mois : il ne compte pas comme un mois complet.
        statuses = [doc.get("file_month") for doc in db.imports.find({"status": "complete"})]
        assert all(month is None for month in statuses)

    if not args.keep_database:
        client.drop_database(TEST_DATABASE)
    client.close()

    print(json.dumps({"verified": True, "uri": uri, "checks": results}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
