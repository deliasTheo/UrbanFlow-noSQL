"""Montre ce que fait chaque serveur pour trois types de requêtes.

Pour ne pas réécrire les pipelines à la main, on appelle l'API avec les journaux
Spring détaillés, on récupère le pipeline réellement envoyé, puis on le rejoue
avec explain sur le déploiement. Le résultat dit quels serveurs sont contactés,
ce qu'ils calculent et ce qui est fusionné ensuite.

Usage :
    python scripts/explain-requests.py --deployment zone
"""

import argparse
import json
import re
import tempfile
from pathlib import Path

import common
from pymongo import MongoClient

REQUESTS = {
    "une_zone_chargee": common.REQUESTS["f1_jfk_pickup_march"],
    "plusieurs_zones": common.REQUESTS["f2_several_zones_semester"],
    "origine_destination_ville": common.REQUESTS["f5_city_across_april"],
}

AGGREGATION = re.compile(r"Executing aggregation: (\[.*\]) in collection trips")


def last_pipeline(log_path):
    found = AGGREGATION.findall(Path(log_path).read_text(encoding="utf-8", errors="replace"))
    return json.loads(found[-1])


def find_stats(node):
    """Cherche le bloc executionStats, dont la place varie selon le plan."""
    if isinstance(node, dict):
        if "totalDocsExamined" in node:
            return node
        for value in node.values():
            found = find_stats(value)
            if found:
                return found
    if isinstance(node, list):
        for value in node:
            found = find_stats(value)
            if found:
                return found
    return None


def stage_names(stages):
    return [next(iter(stage)) for stage in stages or []]


def instance_summary(plan):
    stats = find_stats(plan) or {}
    return {
        "documents_lus": stats.get("totalDocsExamined"),
        "cles_lues": stats.get("totalKeysExamined"),
        "documents_rendus": stats.get("nReturned"),
        "millisecondes": stats.get("executionTimeMillis"),
    }


def summarize_explain(explain):
    if "shards" not in explain:
        return {"contactes": ["server"], "par_serveur": {"server": instance_summary(explain)},
                "calcul_local": stage_names(explain.get("stages")), "fusion": None}
    split = explain.get("splitPipeline") or {}
    shards = explain["shards"]
    return {
        "contactes": sorted(shards),
        "par_serveur": {name: instance_summary(plan) for name, plan in shards.items()},
        "calcul_local": stage_names(split.get("shardsPart")),
        "fusion": stage_names(split.get("mergerPart")),
        "lieu_de_fusion": explain.get("mergeType"),
        "serveur_de_fusion": explain.get("mergeShardId"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--deployment", required=True, choices=list(common.DEPLOYMENTS))
    args = parser.parse_args()
    name = args.deployment

    common.start_deployment(name)
    results = {}
    with tempfile.TemporaryDirectory() as folder:
        log_path = Path(folder) / "api.log"
        api = common.start_api(name, log_path=log_path, debug_queries=True)
        try:
            with MongoClient(common.DEPLOYMENTS[name]["uri"]) as client:
                for label, path in REQUESTS.items():
                    status, seconds, _ = common.call_api(path)
                    pipeline = last_pipeline(log_path)
                    explain = client.urbanflow.command(
                        "explain", {"aggregate": "trips", "pipeline": pipeline, "cursor": {}, "allowDiskUse": True},
                        verbosity="executionStats")
                    results[label] = {"path": path, "status": status, "seconds": round(seconds, 3), **summarize_explain(explain)}
                    print(label, json.dumps(results[label], ensure_ascii=False), flush=True)
        finally:
            common.stop_api(api)

    common.write_json(common.RESULTS / "distributed" / "explain" / f"{name}.json", results)


if __name__ == "__main__":
    main()
