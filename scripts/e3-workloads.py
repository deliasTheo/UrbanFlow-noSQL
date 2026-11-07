"""E3 : deux charges opposées et leurs mélanges, sur un déploiement chargé.

Charge A : quelques zones très actives et des fenêtres courtes (F1 départs, F4).
Charge B : beaucoup de zones et de périodes (F1 arrivées, F2, F5).
La suite de requêtes est tirée avec une graine fixe, donc la même partout.

La prédiction doit être déposée avant de lancer ce script : docs/prediction-e3.md.

Usage :
    python scripts/e3-workloads.py --deployment local
"""

import argparse
import random
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import common

MIXES = {"100A": 1.0, "70A_30B": 0.7, "30A_70B": 0.3, "100B": 0.0}
REQUESTS_PER_MIX = 24
CLIENTS = 3
SEED = 2024

HOT_ZONES = [132, 161, 236, 237]
HOT_PAIRS = [(132, 161), (161, 236), (237, 236), (236, 237)]
OTHER_ZONES = [181, 189, 33, 52, 97, 25, 7, 129, 95, 138, 74, 42, 68, 48, 79, 107]
BOROUGHS = ["Brooklyn", "Queens"]

FIRST_DAY = date(2024, 1, 8)
LAST_MONDAY = date(2024, 6, 17)


def random_monday(rng, earliest=FIRST_DAY):
    weeks = (LAST_MONDAY - earliest).days // 7
    return earliest + timedelta(weeks=rng.randint(0, weeks))


def hot_request(rng):
    start = random_monday(rng, date(2024, 1, 22))
    if rng.random() < 0.5:
        zone = rng.choice(HOT_ZONES)
        return f"/api/activity?zoneId={zone}&direction=pickup&from={start}&to={start + timedelta(days=7)}"
    origin, destination = rng.choice(HOT_PAIRS)
    return (f"/api/journeys?originId={origin}&destinationId={destination}"
            f"&from={start}&to={start + timedelta(days=7)}"
            f"&referenceFrom={start - timedelta(days=14)}&referenceTo={start}")


def wide_request(rng):
    choice = rng.random()
    if choice < 0.35:
        zone = rng.choice(OTHER_ZONES)
        return f"/api/activity?zoneId={zone}&direction=dropoff&from=2024-01-01&to=2024-07-01"
    if choice < 0.65:
        start = random_monday(rng)
        return f"/api/flows?borough={rng.choice(BOROUGHS)}&from={start}&to={start + timedelta(weeks=4)}"
    start = random_monday(rng, date(2024, 3, 11))
    return (f"/api/flow-changes?borough={rng.choice(BOROUGHS)}&from={start}&to={start + timedelta(days=7)}"
            f"&referenceFrom={start - timedelta(days=7)}&referenceTo={start}"
            f"&baselineFrom={start - timedelta(days=35)}&baselineTo={start}")


def build_workload(share_of_a):
    """Autant de requêtes A et B que le mélange le demande, dans un ordre tiré au sort."""
    rng = random.Random(SEED)
    count_a = round(REQUESTS_PER_MIX * share_of_a)
    requests = [("A", hot_request(rng)) for _ in range(count_a)]
    requests += [("B", wide_request(rng)) for _ in range(REQUESTS_PER_MIX - count_a)]
    rng.shuffle(requests)
    return requests


def timed_call(item):
    kind, path = item
    status, seconds, _ = common.call_api(path)
    return {"kind": kind, "path": path, "status": status, "seconds": round(seconds, 3)}


def run_mix(name, requests):
    before = common.instance_counters(name)
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=CLIENTS) as clients:
        calls = list(clients.map(timed_call, requests))
    wall_seconds = time.perf_counter() - started
    after = common.instance_counters(name)

    summary = {"wall_seconds": round(wall_seconds, 1),
               "requests_per_minute": round(60 * len(calls) / wall_seconds, 2),
               "errors": sum(call["status"] != 200 for call in calls),
               "work_per_instance": common.counters_delta(before, after),
               "calls": calls}
    for kind in ["A", "B"]:
        times = [call["seconds"] for call in calls if call["kind"] == kind]
        if times:
            summary[f"median_{kind}"] = round(statistics.median(times), 3)
            summary[f"max_{kind}"] = round(max(times), 3)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--deployment", required=True, choices=list(common.DEPLOYMENTS))
    args = parser.parse_args()
    name = args.deployment

    common.start_deployment(name)
    api = common.start_api(name)
    results = {"deployment": name, "clients": CLIENTS, "requests_per_mix": REQUESTS_PER_MIX, "seed": SEED, "mixes": {}}
    output = common.RESULTS / "experiments" / "e3" / f"{name}.json"
    try:
        # Une passe à blanc de chaque charge, pour que tous les mélanges partent d'un cache chaud.
        print("Échauffement", flush=True)
        run_mix(name, build_workload(0.5))
        for label, share_of_a in MIXES.items():
            print(f"Mélange {label}", flush=True)
            results["mixes"][label] = run_mix(name, build_workload(share_of_a))
            mix = results["mixes"][label]
            print(f"  {mix['wall_seconds']} s, {mix['errors']} erreurs, A {mix.get('median_A')} s, B {mix.get('median_B')} s", flush=True)
            common.write_json(output, results)
    finally:
        common.stop_api(api)


if __name__ == "__main__":
    main()
