"""Prépare une base vide avant l'import : index, et placement des trajets si cluster.

Usage :
    python -m urbanflow.deploy --placement local    # serveur de compose.yaml
    python -m urbanflow.deploy --placement zone     # shards par zone de départ
    python -m urbanflow.deploy --placement month    # shards par période

Les trois déploiements ont exactement les mêmes index, pour que les écarts
mesurés viennent du placement et pas d'un index en plus ou en moins.
"""

import argparse
import json
import time

import pandas as pd
from bson.max_key import MaxKey
from bson.min_key import MinKey
from pymongo import ASCENDING, MongoClient
from pymongo.errors import OperationFailure, ServerSelectionTimeoutError

from urbanflow import config

PICKUP_ZONE = "data.PULocationID"
PICKUP_TIME = "data.tpep_pickup_datetime"
DROPOFF_ZONE = "data.DOLocationID"
DROPOFF_TIME = "data.tpep_dropoff_datetime"

INDEXES = {
    "f1_pickup_zone_datetime": [PICKUP_ZONE, PICKUP_TIME],
    "f1_dropoff_zone_datetime": [DROPOFF_ZONE, DROPOFF_TIME],
    "f4_pair_pickup_datetime": [PICKUP_ZONE, DROPOFF_ZONE, PICKUP_TIME],
    # Clé de partition du placement par période. Elle sert aussi au contrôle
    # ville de F3, qui sinon relit toute la collection.
    "pickup_datetime_zone": [PICKUP_TIME, PICKUP_ZONE],
}

LOCAL_URI = "mongodb://127.0.0.1:27018"
MONGOS_URI = "mongodb://127.0.0.1:27019"
CONFIG_PORT = 27020
SHARD_PORTS = {"shard1": 27021, "shard2": 27022}

# Limite entre les deux shards du placement par période : les trois mois
# initiaux sur le premier, le mois de F6 et les suivants sur le second.
MONTH_BOUNDARY = "2024-04-01T00:00:00"

LAST_ZONE_ID = 265


def create_indexes(db):
    for name, fields in INDEXES.items():
        db.trips.create_index([(field, ASCENDING) for field in fields], name=name)


def direct_client(port):
    return MongoClient(f"mongodb://127.0.0.1:{port}/?directConnection=true", serverSelectionTimeoutMS=60000)


def start_replica_set(port, name, host, is_config=False):
    """Chaque shard est un replica set à un seul membre : MongoDB l'impose, sans copie."""
    client = direct_client(port)
    settings = {"_id": name, "members": [{"_id": 0, "host": host}]}
    if is_config:
        settings["configsvr"] = True
    try:
        client.admin.command("replSetInitiate", settings)
    except OperationFailure as error:
        if "already initialized" not in str(error):
            raise
    while not client.admin.command("hello").get("isWritablePrimary"):
        time.sleep(1)
    client.close()


def wait_for_mongos():
    client = MongoClient(MONGOS_URI, serverSelectionTimeoutMS=5000)
    for _ in range(60):
        try:
            client.admin.command("ping")
            return client
        except ServerSelectionTimeoutError:
            time.sleep(2)
    raise RuntimeError("mongos ne répond pas")


def assign_zones_to_shards():
    """Répartit les zones entre les shards pour équilibrer le nombre de départs.

    On part des trois mois initiaux : la plus grosse zone restante va sur le
    shard le moins chargé. Une zone reste entière sur un seul shard.
    """
    counts = pd.Series(dtype="int64")
    for month in config.STUDY_MONTHS:
        path = config.RAW_DIR / config.trip_file_name(month)
        pickups = pd.read_parquet(path, columns=["PULocationID"])["PULocationID"]
        counts = counts.add(pickups.value_counts(), fill_value=0)

    loads = {name: 0 for name in SHARD_PORTS}
    assignment = {}
    biggest_first = sorted(range(1, LAST_ZONE_ID + 1), key=lambda z: (-counts.get(z, 0), z))
    for zone in biggest_first:
        shard = min(loads, key=lambda name: (loads[name], name))
        assignment[zone] = shard
        loads[shard] += int(counts.get(zone, 0))

    output = config.RESULTS_DIR / "distributed"
    output.mkdir(parents=True, exist_ok=True)
    (output / "zone-placement.json").write_text(json.dumps({
        "built_from": config.STUDY_MONTHS,
        "pickups_per_shard": loads,
        "zones_per_shard": {
            name: sorted(zone for zone, shard in assignment.items() if shard == name)
            for name in loads
        },
    }, indent=2) + "\n")
    return assignment


def zone_ranges():
    """Plages de clé par zone de départ, en regroupant les zones voisines d'un même shard."""
    assignment = assign_zones_to_shards()
    ranges = []
    start = {PICKUP_ZONE: MinKey(), PICKUP_TIME: MinKey()}
    for zone in range(1, LAST_ZONE_ID):
        if assignment[zone] != assignment[zone + 1]:
            end = {PICKUP_ZONE: zone + 1, PICKUP_TIME: MinKey()}
            ranges.append((start, end, assignment[zone]))
            start = end
    ranges.append((start, {PICKUP_ZONE: MaxKey(), PICKUP_TIME: MaxKey()}, assignment[LAST_ZONE_ID]))
    return ranges


def month_ranges():
    middle = {PICKUP_TIME: MONTH_BOUNDARY, PICKUP_ZONE: MinKey()}
    return [
        ({PICKUP_TIME: MinKey(), PICKUP_ZONE: MinKey()}, middle, "shard1"),
        (middle, {PICKUP_TIME: MaxKey(), PICKUP_ZONE: MaxKey()}, "shard2"),
    ]


def setup_cluster(placement, database):
    start_replica_set(CONFIG_PORT, "cfg", "config:27017", is_config=True)
    for name, port in SHARD_PORTS.items():
        start_replica_set(port, name, f"{name}:27017")

    client = wait_for_mongos()
    admin = client.admin
    for name in SHARD_PORTS:
        admin.command("addShard", f"{name}/{name}:27017", name=name)
        admin.command("addShardToZone", name, zone=name)

    # Le placement est fixé d'avance : aucun déplacement de données pendant les mesures.
    admin.command("balancerStop")
    admin.command("enableSharding", database, primaryShard="shard1")

    if placement == "zone":
        key = {PICKUP_ZONE: 1, PICKUP_TIME: 1}
        ranges = zone_ranges()
    else:
        key = {PICKUP_TIME: 1, PICKUP_ZONE: 1}
        ranges = month_ranges()

    namespace = f"{database}.trips"
    for start, end, shard in ranges:
        admin.command("updateZoneKeyRange", namespace, min=start, max=end, zone=shard)

    create_indexes(client[database])
    admin.command("shardCollection", namespace, key=key)

    chunks = client.config.chunks.count_documents({})
    print(f"Cluster prêt : placement {placement}, {len(ranges)} plages, {chunks} chunks")
    client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--placement", required=True, choices=["local", "zone", "month"])
    parser.add_argument("--database", default="urbanflow")
    args = parser.parse_args()

    if args.placement == "local":
        with MongoClient(LOCAL_URI, serverSelectionTimeoutMS=10000) as client:
            create_indexes(client[args.database])
        print("Serveur local prêt")
    else:
        setup_cluster(args.placement, args.database)


if __name__ == "__main__":
    main()
