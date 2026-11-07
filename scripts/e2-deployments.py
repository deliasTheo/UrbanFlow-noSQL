"""E2 : les mêmes requêtes, avec les mêmes paramètres, sur un déploiement chargé.

Pour chaque requête : le premier appel après redémarrage des serveurs (cache
froid côté MongoDB), un appel d'échauffement, puis cinq appels mesurés à la suite.
On note aussi le travail de chaque serveur, et on garde la dernière réponse pour
la comparaison entre déploiements (scripts/compare-deployments.py).

Usage :
    python scripts/e2-deployments.py --deployment local
"""

import argparse
import json
import sys

import common
from pymongo import MongoClient

REPETITIONS = 5

# Requêtes en plus pour la comparaison : elles passent d'un serveur à l'autre.
COMPARE_ONLY = {
    "f1_jfk_pickup_across_april": "/api/activity?zoneId=132&direction=pickup&from=2024-03-20&to=2024-04-10",
    "f2_several_zones_across_april": "/api/flows?zoneIds=132,161,237&from=2024-03-25&to=2024-04-08",
    "f3_several_zones_april": (
        "/api/unusual-activity?zoneIds=181,132,161&from=2024-04-08&to=2024-04-15"
        "&referenceFrom=2024-03-11&referenceTo=2024-04-08"
    ),
    "f4_across_april": (
        "/api/journeys?originId=161&destinationId=236&from=2024-04-01&to=2024-04-15"
        "&referenceFrom=2024-03-18&referenceTo=2024-04-01"
    ),
    "f5_several_zones_may": (
        "/api/flow-changes?zoneIds=132,181,161&from=2024-05-13&to=2024-05-20"
        "&referenceFrom=2024-05-06&referenceTo=2024-05-13&baselineFrom=2024-03-18&baselineTo=2024-05-13"
    ),
}


def dataset_fingerprint(name):
    """Contrôle que le déploiement contient bien les mêmes trajets que les autres."""
    pipeline = [{"$group": {
        "_id": "$source.file_id",
        "documents": {"$sum": 1},
        "total_distance": {"$sum": "$data.trip_distance"},
        "total_amount": {"$sum": "$data.total_amount"},
    }}, {"$sort": {"_id": 1}}]
    with MongoClient(common.DEPLOYMENTS[name]["uri"]) as client:
        rows = list(client.urbanflow.trips.aggregate(pipeline, allowDiskUse=True))
    for row in rows:
        row["total_distance"] = round(row["total_distance"], 2)
        row["total_amount"] = round(row["total_amount"], 2)
    return rows


def restart_data_servers(name):
    """Vide le cache de MongoDB. Le cache disque de la VM n'est pas vidé."""
    common.run(common.DEPLOYMENTS[name]["compose"] + ["restart"])
    for port in common.DEPLOYMENTS[name]["instances"].values():
        common.wait_for_primary(port)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--deployment", required=True, choices=list(common.DEPLOYMENTS))
    args = parser.parse_args()
    name = args.deployment

    common.start_deployment(name)
    restart_data_servers(name)
    common.write_environment(name)
    api = common.start_api(name)

    responses = common.ROOT / "data/staging/responses" / name
    responses.mkdir(parents=True, exist_ok=True)
    results = {}
    failures = 0
    output = common.RESULTS / "experiments" / "e2" / f"{name}.json"

    def save():
        common.write_json(output, {
            "deployment": name,
            "repetitions": REPETITIONS,
            "protocol": "premier appel après redémarrage des serveurs, un échauffement, puis cinq appels à la suite ; un seul client",
            "failures": failures,
            "requests": results,
        })

    try:
        cold = {}
        for label, path in common.REQUESTS.items():
            cold_status, seconds, _ = common.call_api(path)
            cold[label] = {"status": cold_status, "seconds": round(seconds, 3)}
            failures += cold_status != 200
            print(f"froid {label}: {seconds:.1f} s (HTTP {cold_status})", flush=True)

        for label, path in common.REQUESTS.items():
            common.call_api(path)
            before = common.instance_counters(name)
            times, errors, status, body = common.repeat_calls(path, REPETITIONS)
            after = common.instance_counters(name)
            failures += len(errors)
            (responses / f"{label}.json").write_text(json.dumps({"status": status, "body": body}), encoding="utf-8")
            results[label] = {
                "path": path,
                "status": status,
                "errors": errors,
                "cold": cold[label],
                **common.summarize(times),
                "work_per_instance_for_all_repetitions": common.counters_delta(before, after),
            }
            print(f"{label}: {results[label]['median']} s (HTTP {status}, {len(errors)} échec(s))", flush=True)
            save()

        for label, path in COMPARE_ONLY.items():
            status, seconds, body = common.call_api(path)
            failures += status != 200
            (responses / f"{label}.json").write_text(json.dumps({"status": status, "body": body}), encoding="utf-8")
            print(f"{label}: {seconds:.1f} s (HTTP {status})", flush=True)

        fingerprint = dataset_fingerprint(name)
        common.write_json(common.RESULTS / "distributed" / "fingerprints" / f"{name}.json", fingerprint)
        save()
    finally:
        common.stop_api(api)

    if failures:
        sys.exit(f"{failures} appel(s) en échec : ces mesures ne sont pas exploitables, voir {output}")


if __name__ == "__main__":
    main()
