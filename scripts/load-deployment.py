"""Charge les six mois dans un déploiement et mesure le coût de l'ingestion.

Déroulé, le même partout :
  janvier à mars importés en ligne de commande, puis avril importé via l'API
  (service F6) et réimporté pour vérifier que rien ne change, puis mai et juin.

Sur le local, --measure relève aussi les latences à 1, 3 et 6 mois (E1).
--quick sert d'essai : janvier, puis avril par F6, sans les autres mois.

Usage :
    python scripts/load-deployment.py --deployment local --measure
    python scripts/load-deployment.py --deployment zone
    python scripts/load-deployment.py --deployment month
"""

import argparse
import json
import os
import subprocess
import sys
import time

import common
from pymongo import MongoClient

sys.path.insert(0, str(common.ROOT))
from urbanflow.config import EXPERIMENT_MONTHS, STUDY_MONTHS, UPDATE_MONTH  # noqa: E402

# Requêtes de E1. Celles du premier groupe restent sur janvier : la réponse ne
# change pas quand la base grossit, seul le volume stocké change.
E1_FIXED_WINDOW = {
    "f1_parkslope_january": "/api/activity?zoneId=181&direction=pickup&from=2024-01-01&to=2024-02-01",
    "f1_jfk_january": "/api/activity?zoneId=132&direction=pickup&from=2024-01-01&to=2024-02-01",
    "f2_brooklyn_january": "/api/flows?borough=Brooklyn&from=2024-01-01&to=2024-02-01",
    "f3_brooklyn_january": (
        "/api/unusual-activity?borough=Brooklyn&from=2024-01-22&to=2024-02-01"
        "&referenceFrom=2024-01-01&referenceTo=2024-01-22"
    ),
    "f4_jfk_midtown_january": (
        "/api/journeys?originId=132&destinationId=161&from=2024-01-15&to=2024-02-01"
        "&referenceFrom=2024-01-01&referenceTo=2024-01-15"
    ),
    "f5_brooklyn_january": (
        "/api/flow-changes?borough=Brooklyn&from=2024-01-22&to=2024-01-29"
        "&referenceFrom=2024-01-15&referenceTo=2024-01-22&baselineFrom=2024-01-01&baselineTo=2024-01-22"
    ),
}
# Ici la fenêtre suit la base : la réponse grossit avec le volume.
E1_WHOLE_BASE = {
    "f1_parkslope_whole_base": "/api/activity?zoneId=181&direction=pickup&from=2024-01-01&to=2024-07-01",
    "f2_brooklyn_whole_base": "/api/flows?borough=Brooklyn&from=2024-01-01&to=2024-07-01",
}
REPETITIONS = 5


def import_month(name, month):
    """Import en ligne de commande. Renvoie le résumé écrit par ingest."""
    environment = {**os.environ, "MONGODB_URI": common.DEPLOYMENTS[name]["uri"], "PYTHONIOENCODING": "utf-8"}
    subprocess.run([sys.executable, "-m", "urbanflow.ingest", "--month", month],
                   cwd=common.ROOT, env=environment, check=True, stdout=subprocess.DEVNULL)
    path = common.RESULTS / "ingestion" / f"{month}.json"
    return json.loads(path.read_text())


def document_count(name):
    with MongoClient(common.DEPLOYMENTS[name]["uri"]) as client:
        return client.urbanflow.trips.estimated_document_count()


def f1_april_totals():
    status, _, body = common.call_api("/api/activity?zoneId=181&direction=pickup&from=2024-04-01&to=2024-05-01")
    return json.loads(body)["totals"] if status == 200 else status


def update_with_f6(name):
    """Importe le mois réservé par l'API, deux fois, et note ce qui change."""
    before_documents = document_count(name)
    before_f1 = f1_april_totals()

    status, seconds, body = common.call_api(f"/api/imports?month={UPDATE_MONTH}", method="POST", timeout=7200)
    if status != 200:
        raise RuntimeError(f"F6 a échoué : {body}")
    after_documents = document_count(name)
    after_f1 = f1_april_totals()

    status, second_seconds, body = common.call_api(f"/api/imports?month={UPDATE_MONTH}", method="POST", timeout=7200)
    if status != 200:
        raise RuntimeError(f"Le second import F6 a échoué : {body}")
    again_documents = document_count(name)
    if again_documents != after_documents:
        raise RuntimeError("Le second import a modifié la base")

    return {
        "http_seconds": round(seconds, 1),
        "documents_before": before_documents,
        "documents_after": after_documents,
        "documents_after_second_import": again_documents,
        "second_import_seconds": round(second_seconds, 1),
        "f1_zone181_april_before": before_f1,
        "f1_zone181_april_after": after_f1,
    }


def measure_latencies(requests):
    """Un appel d'échauffement, puis REPETITIONS appels mesurés pour chaque requête."""
    results = {}
    for label, path in requests.items():
        _, warmup, _ = common.call_api(path)
        times, errors, status, _ = common.repeat_calls(path, REPETITIONS)
        results[label] = {"status": status, "errors": errors, "warmup": round(warmup, 3), **common.summarize(times)}
        print(f"  {label}: {results[label]['median']} s (HTTP {status}, {len(errors)} échec(s))", flush=True)
    return results


def require_empty_database(name):
    """Un mois déjà importé serait ignoré : son temps d'import ne serait pas remesuré."""
    with MongoClient(common.DEPLOYMENTS[name]["uri"]) as client:
        db = client.urbanflow
        if db.trips.estimated_document_count() or db.imports.count_documents({}):
            command = " ".join(common.DEPLOYMENTS[name]["compose"])
            sys.exit(f"La base de {name} n'est pas vide. Pour repartir de zéro : {command} down -v")


def checkpoint(name, months_loaded, requests):
    """État du déploiement quand la base contient `months_loaded` mois."""
    with MongoClient(common.DEPLOYMENTS[name]["uri"]) as client:
        db = client.urbanflow
        complete = list(db.imports.find({"status": "complete"}))
    rows = sum(doc["summary"]["num_rows"] for doc in complete)
    retained = sum(doc["summary"]["profiles"]["activity"] for doc in complete)
    return {
        "months": months_loaded,
        "source_rows": rows,
        "distinct_trips_activity_profile": retained,
        "documents": document_count(name),
        "storage": common.instance_storage(name),
        "latency": measure_latencies(requests) if requests else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--deployment", required=True, choices=list(common.DEPLOYMENTS))
    parser.add_argument("--measure", action="store_true", help="relever aussi les latences de E1")
    parser.add_argument("--quick", action="store_true", help="essai : janvier et avril seulement")
    args = parser.parse_args()
    name = args.deployment
    study_months = STUDY_MONTHS[:1] if args.quick else STUDY_MONTHS
    later_months = [] if args.quick else EXPERIMENT_MONTHS

    common.start_deployment(name, initialized=False)
    subprocess.run([sys.executable, "-m", "urbanflow.deploy", "--placement", name], cwd=common.ROOT,
                   check=True, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    require_empty_database(name)
    common.write_environment(name)

    months = {}
    checkpoints = []
    api = None
    output = common.RESULTS / "experiments" / "ingestion" / f"{name}.json"
    started = time.perf_counter()

    def save():
        common.write_json(output, {
            "deployment": name,
            "months": months,
            # Le temps du script comprend aussi les latences de E1 : seul le premier se compare.
            "ingestion_seconds": round(sum(month["seconds"] for month in months.values()), 1),
            "script_seconds": round(time.perf_counter() - started, 1),
            "checkpoints": checkpoints,
            "f6": f6,
        })

    f6 = None
    try:
        for position, month in enumerate(study_months, start=1):
            print(f"Import de {month}", flush=True)
            months[month] = import_month(name, month)
            save()
            if args.measure and position in (1, 3):
                api = common.start_api(name)
                requests = {**E1_FIXED_WINDOW, **E1_WHOLE_BASE}
                checkpoints.append(checkpoint(name, position, requests))
                common.stop_api(api)
                api = None
                save()

        api = common.start_api(name)
        print(f"Import de {UPDATE_MONTH} par F6", flush=True)
        f6 = update_with_f6(name)
        months[UPDATE_MONTH] = json.loads((common.RESULTS / "ingestion" / f"{UPDATE_MONTH}.json").read_text())
        save()
        common.stop_api(api)
        api = None

        for month in later_months:
            print(f"Import de {month}", flush=True)
            months[month] = import_month(name, month)
            save()

        api = common.start_api(name)
        requests = {**E1_FIXED_WINDOW, **E1_WHOLE_BASE} if args.measure else None
        checkpoints.append(checkpoint(name, len(months), requests))
        save()
    finally:
        if api is not None:
            common.stop_api(api)

    print(f"Terminé en {round(time.perf_counter() - started)} s", flush=True)


if __name__ == "__main__":
    main()
