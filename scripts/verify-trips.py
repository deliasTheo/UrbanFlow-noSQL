"""Vérifie que /api/trips remonte bien aux lignes des fichiers TLC.

Les lignes renvoyées sont relues directement dans le Parquet, à leur numéro de ligne.
Les comptes sont comparés à ceux de F1 et de F2 sur les mêmes paramètres.

Usage (API lancée sur une base qui contient janvier) :
    python scripts/verify-trips.py
"""

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
JANUARY = "from=2024-01-01&to=2024-02-01"

parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("--api", default="http://127.0.0.1:8080")
args = parser.parse_args()


def get(path):
    with urllib.request.urlopen(args.api + path, timeout=180) as response:
        return json.load(response)


def compare_with_parquet(trips):
    """Chaque ligne renvoyée doit exister dans son fichier, au numéro annoncé."""
    frames = {}
    for trip in trips:
        name = trip["fileName"]
        if name not in frames:
            frames[name] = pd.read_parquet(ROOT / "data/raw" / name)
        row = frames[name].iloc[trip["rowNumber"]]
        assert row.tpep_pickup_datetime.strftime("%Y-%m-%dT%H:%M:%S") == trip["pickup"]
        assert row.tpep_dropoff_datetime.strftime("%Y-%m-%dT%H:%M:%S") == trip["dropoff"]
        assert int(row.PULocationID) == trip["pickupZoneId"]
        assert int(row.DOLocationID) == trip["dropoffZoneId"]
        assert row.total_amount == trip["totalAmount"]


# Mêmes comptes que F1, au départ et à l'arrivée.
activity = get(f"/api/activity?zoneId=181&direction=pickup&{JANUARY}")
listed = get(f"/api/trips?pickupZoneId=181&{JANUARY}&limit=200")
assert listed["totals"] == activity["totals"]
compare_with_parquet(listed["trips"])

activity = get(f"/api/activity?zoneId=181&direction=dropoff&{JANUARY}")
arrivals = get(f"/api/trips?dropoffZoneId=181&time=dropoff&{JANUARY}&limit=50")
assert arrivals["totals"] == activity["totals"]

# Mêmes comptes que F2 pour la paire la plus active de la zone, avec le profil flows.
flows = get(f"/api/flows?zoneIds=181&{JANUARY}")
pair = flows["pairs"][0]
origin, destination = pair["origin"]["id"], pair["destination"]["id"]
listed_pair = get(f"/api/trips?pickupZoneId={origin}&dropoffZoneId={destination}&{JANUARY}&profile=flows&limit=50")
assert listed_pair["totals"] == pair["counts"]
compare_with_parquet(listed_pair["trips"])

# Le filtre de qualité correspond aux comptes.
retained = get(f"/api/trips?pickupZoneId=132&{JANUARY}&status=retained&limit=1000")
excluded = get(f"/api/trips?pickupZoneId=132&{JANUARY}&status=excluded&limit=1000")
assert all(trip["retained"] for trip in retained["trips"])
assert not any(trip["retained"] for trip in excluded["trips"])
assert len(excluded["trips"]) == min(1000, excluded["totals"]["excluded"])
compare_with_parquet(excluded["trips"][:50])

# Le créneau horaire correspond à la répartition par heure de F1.
activity = get(f"/api/activity?zoneId=132&direction=pickup&{JANUARY}")
morning = sum(b["counts"]["raw"] for b in activity["byHour"] if 8 <= b["value"] < 12)
slot = get(f"/api/trips?pickupZoneId=132&{JANUARY}&startHour=8&endHour=12&limit=20")
assert slot["totals"]["raw"] == morning
assert all(8 <= int(trip["pickup"][11:13]) < 12 for trip in slot["trips"])

# La pagination suit un ordre stable, sans doublon d'une page à l'autre.
first = get(f"/api/trips?pickupZoneId=181&{JANUARY}&limit=20")["trips"]
second = get(f"/api/trips?pickupZoneId=181&{JANUARY}&offset=20&limit=20")["trips"]
assert not {t["id"] for t in first} & {t["id"] for t in second}

for query, status in [
    (JANUARY, 400),
    (f"pickupZoneId=9999&{JANUARY}", 404),
    (f"pickupZoneId=181&{JANUARY}&profile=autre", 400),
    (f"pickupZoneId=181&{JANUARY}&limit=5000", 400),
    (f"pickupZoneId=181&{JANUARY}&startHour=12&endHour=8", 400),
]:
    try:
        get("/api/trips?" + query)
        raise AssertionError("Erreur attendue : " + query)
    except urllib.error.HTTPError as error:
        assert error.code == status, query

print(json.dumps({"verified": True, "totals_zone_181": listed["totals"], "sources": listed["sources"]}, indent=2))
