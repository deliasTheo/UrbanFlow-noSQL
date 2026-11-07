"""Arrête un serveur de données et note ce que l'utilisateur reçoit.

Les réponses sans panne servent de référence. Pendant la panne, une réponse 200
n'est acceptable que si elle est identique à la référence : une réponse partielle
présentée comme complète ferait échouer le script.

Usage :
    python scripts/lose-instance.py --deployment zone
"""

import argparse
import json
import subprocess
import sys
import time

import common

# La requête F1 porte sur une zone et une période dont les trajets sont sur les
# deux shards, dans les deux placements. F5 regroupe toute la ville.
REQUESTS = {
    "f1_zone_sur_les_deux_shards": common.REQUESTS["f1_parkslope_dropoff_semester"],
    "f5_ville": common.REQUESTS["f5_city_across_april"],
}
# Requêtes qui ne touchent que le shard 1 selon le placement : elles peuvent encore répondre.
SHARD1_ONLY = {
    "month": "/api/activity?zoneId=181&direction=pickup&from=2024-01-01&to=2024-02-01",
}


def zone_on_shard1():
    placement = json.loads((common.RESULTS / "distributed/zone-placement.json").read_text())
    return placement["zones_per_shard"]["shard1"][0]


def stop_container(container):
    subprocess.run(["docker", "stop", container], check=True, stdout=subprocess.DEVNULL)


def start_container(container):
    subprocess.run(["docker", "start", container], check=True, stdout=subprocess.DEVNULL)


def wait_until_answers(path):
    """Après un redémarrage, mongos met un moment à retrouver le shard."""
    for _ in range(60):
        if common.call_api(path)[0] == 200:
            return
        time.sleep(2)
    raise RuntimeError("Le cluster ne répond plus normalement après le redémarrage")


def error_message(body):
    try:
        return json.loads(body).get("detail")
    except ValueError:
        return body[:200]


def compare(requests, references):
    """Appelle les requêtes et les compare à leur réponse sans panne."""
    results = {}
    for label, path in requests.items():
        status, seconds, body = common.call_api(path)
        entry = {"path": path, "http": status, "seconds": round(seconds, 1)}
        if status == 200:
            entry["identique_a_la_reference"] = json.loads(body) == references[label]
            if not entry["identique_a_la_reference"]:
                print(f"RÉPONSE PARTIELLE : {label}")
                sys.exit(1)
        else:
            entry["message"] = error_message(body)
        results[label] = entry
        print(label, entry, flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--deployment", required=True, choices=["zone", "month"])
    args = parser.parse_args()
    name = args.deployment
    containers = common.DEPLOYMENTS[name]["containers"]

    requests = dict(REQUESTS)
    if name == "zone":
        requests["f1_depart_zone_du_shard1"] = (
            f"/api/activity?zoneId={zone_on_shard1()}&direction=pickup&from=2024-01-01&to=2024-07-01")
    else:
        requests["f1_janvier_sur_shard1"] = SHARD1_ONLY["month"]

    common.start_deployment(name)
    api = common.start_api(name)
    report = {"deployment": name}
    try:
        references = {}
        for label, path in requests.items():
            status, _, body = common.call_api(path)
            if status != 200:
                raise RuntimeError(f"{label} échoue déjà sans panne : {body}")
            references[label] = json.loads(body)

        print("Arrêt de shard2", flush=True)
        stop_container(containers["shard2"])
        report["shard2_arrete"] = compare(requests, references)
        start_container(containers["shard2"])
        common.wait_for_primary(common.DEPLOYMENTS[name]["instances"]["shard2"])
        wait_until_answers(common.REQUESTS["f1_parkslope_dropoff_semester"])

        # shard1 porte aussi les collections zones et imports : tout s'arrête.
        print("Arrêt de shard1", flush=True)
        stop_container(containers["shard1"])
        report["shard1_arrete"] = compare(requests, references)
        start_container(containers["shard1"])
        common.wait_for_primary(common.DEPLOYMENTS[name]["instances"]["shard1"])
        wait_until_answers(common.REQUESTS["f1_parkslope_dropoff_semester"])

        print("Retour à la normale", flush=True)
        report["apres_redemarrage"] = compare(requests, references)
    finally:
        # Quoi qu'il arrive, on ne laisse pas un shard arrêté derrière nous.
        for container in containers.values():
            start_container(container)
        common.stop_api(api)

    common.write_json(common.RESULTS / "distributed" / f"lose-instance-{name}.json", report)


if __name__ == "__main__":
    main()
