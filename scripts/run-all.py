"""Enchaîne tout : chargement, expériences, comparaison, pannes et vérifications.

Une seule étape tourne à la fois, sur un seul déploiement : les mesures ne se gênent pas.
Chaque étape écrit son journal dans results/experiments/logs. Une étape réussie n'est pas
relancée : après un arrêt, relancer la même commande reprend là où ça s'est arrêté.

Usage :
    python scripts/run-all.py --quick --reset    # essai : janvier et avril, résultats dans results-test/
    python scripts/run-all.py --reset            # vraie exécution : six mois, résultats dans results/
    python scripts/run-all.py                    # reprise après un arrêt

--reset EFFACE les volumes Docker des trois déploiements, puis repart de zéro.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

import common
from pymongo import MongoClient

ORDER = ["local", "zone", "month"]
TEST_DATABASE = "urbanflow_test"
F6_DATABASE = "urbanflow_f6_test"
MONTHS = ["2024-01", "2024-02", "2024-03", "2024-04", "2024-05", "2024-06"]


def python(log, *command, uri=None):
    """Lance un script ou un module Python. Une erreur arrête l'étape."""
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    if uri:
        environment["MONGODB_URI"] = uri
    subprocess.run([sys.executable, *command], cwd=common.ROOT, env=environment,
                   stdout=log, stderr=subprocess.STDOUT, check=True)


def script(name, *arguments):
    def step(log):
        python(log, f"scripts/{name}", *arguments)
    return step


def verify_january(log):
    """Vérifications sur une base qui ne contient que janvier, comme elles l'attendent."""
    common.start_deployment("local")
    python(log, "-m", "urbanflow.deploy", "--placement", "local", "--database", TEST_DATABASE)
    python(log, "-m", "urbanflow.ingest", "--month", "2024-01", "--database", TEST_DATABASE)
    api = common.start_api("local", database=TEST_DATABASE)
    try:
        for name in ["verify-f2-parquet.py", "verify-f3-parquet.py", "verify-f4-parquet.py",
                     "verify-f5-parquet.py", "verify-trips.py"]:
            print(f"    {name}", flush=True)
            python(log, f"scripts/{name}", "--api", common.API)
    finally:
        common.stop_api(api)
    python(log, "scripts/verify-f4-dst.py")
    with MongoClient(common.DEPLOYMENTS["local"]["uri"]) as client:
        client.drop_database(TEST_DATABASE)


def verify_f6(name):
    def step(log):
        common.start_deployment(name)
        uri = common.DEPLOYMENTS[name]["uri"]
        if name == "local":
            python(log, "scripts/verify-f6.py", uri=uri)
            return
        python(log, "-m", "urbanflow.deploy", "--placement", name, "--database", F6_DATABASE)
        python(log, "scripts/verify-f6.py", "--keep-database", uri=uri)
        with MongoClient(uri) as client:
            client.drop_database(F6_DATABASE)
    return step


def verify_six_months(log):
    common.start_deployment("local")
    api = common.start_api("local")
    try:
        python(log, "scripts/verify-registered-period.py")
        python(log, "scripts/verify-trips.py", "--api", common.API)
    finally:
        common.stop_api(api)


def build_steps(quick):
    """(nom, fonction, l'exécution peut-elle continuer si l'étape échoue)."""
    steps = []
    if quick:
        steps.append(("verifications-janvier", verify_january, False))
    for name in ORDER:
        arguments = ["--deployment", name]
        if name == "local":
            arguments.append("--measure")
        if quick:
            arguments.append("--quick")
        # Sans chargement, les étapes suivantes n'ont pas de sens.
        steps.append((f"chargement-{name}", script("load-deployment.py", *arguments), False))
    for name in ORDER:
        steps.append((f"explain-{name}", script("explain-requests.py", "--deployment", name), True))
    for name in ORDER:
        steps.append((f"e2-{name}", script("e2-deployments.py", "--deployment", name), True))
    steps.append(("comparaison", script("compare-deployments.py"), True))
    for name in ORDER:
        steps.append((f"e3-{name}", script("e3-workloads.py", "--deployment", name), True))
    for name in ["zone", "month"]:
        steps.append((f"panne-{name}", script("lose-instance.py", "--deployment", name), True))
    if not quick:
        steps.append(("verification-six-mois", verify_six_months, True))
    # À la fin : ces essais écrivent dans des bases à part, qui ne doivent pas gêner les mesures.
    for name in ORDER:
        steps.append((f"f6-{name}", verify_f6(name), True))
    return steps


def check_prerequisites(quick):
    problems = []
    if not common.JAR.exists():
        problems.append("Jar absent : lancer le build dans backend/ (mvnw -DskipTests package).")
    months = MONTHS[:4] if quick else MONTHS
    for month in months:
        if not (common.ROOT / "data/raw" / f"yellow_tripdata_{month}.parquet").exists():
            problems.append(f"Fichier de {month} absent : lancer python -m urbanflow.download")
            break
    if subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
        problems.append("Docker ne répond pas : démarrer Docker Desktop.")
    if problems:
        sys.exit("\n".join(problems))


def reset_volumes():
    print("Suppression des volumes des trois déploiements", flush=True)
    for name in ORDER:
        common.run(common.DEPLOYMENTS[name]["compose"] + ["down", "-v"])
    shutil.rmtree(common.ROOT / "data/staging/responses", ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quick", action="store_true", help="essai sur janvier et avril, dans results-test/")
    parser.add_argument("--reset", action="store_true", help="efface les volumes Docker des trois déploiements")
    args = parser.parse_args()

    results = common.ROOT / ("results-test" if args.quick else "results")
    os.environ["URBANFLOW_RESULTS"] = str(results)
    journal_path = results / "experiments" / "run-all.json"
    logs = results / "experiments" / "logs"
    logs.mkdir(parents=True, exist_ok=True)

    check_prerequisites(args.quick)
    if args.reset:
        reset_volumes()
        journal_path.unlink(missing_ok=True)
    journal = json.loads(journal_path.read_text(encoding="utf-8")) if journal_path.exists() else {}

    started = time.perf_counter()
    for name, step, can_continue in build_steps(args.quick):
        if journal.get(name, {}).get("status") == "ok":
            print(f"{name} : déjà fait", flush=True)
            continue
        print(f"{name} ...", flush=True)
        step_started = time.perf_counter()
        with open(logs / f"{name}.log", "w", encoding="utf-8") as log:
            try:
                step(log)
                status = "ok"
            except Exception as error:
                # Une étape en échec ne doit pas faire perdre le reste de la nuit.
                log.write(f"\n{error}\n")
                status = "echec"
        seconds = round(time.perf_counter() - step_started)
        journal[name] = {"status": status, "seconds": seconds}
        common.write_json(journal_path, journal)
        print(f"{name} : {status} en {seconds} s", flush=True)
        if status != "ok" and not can_continue:
            sys.exit(f"Arrêt : voir {logs / (name + '.log')}")

    failed = [name for name, entry in journal.items() if entry["status"] != "ok"]
    print(f"Terminé en {round((time.perf_counter() - started) / 60)} min, {len(failed)} étape(s) en échec")
    if failed:
        sys.exit("En échec : " + ", ".join(failed))


if __name__ == "__main__":
    main()
