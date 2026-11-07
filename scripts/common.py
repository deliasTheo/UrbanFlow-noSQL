"""Ce que les scripts d'expériences ont en commun : déploiements, API, compteurs."""

import json
import os
import platform
import socket
import statistics
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from pymongo import MongoClient

ROOT = Path(__file__).resolve().parents[1]
JAR = ROOT / "backend/target/urbanflow-api-0.1.0.jar"
RESULTS = ROOT / "results"
API_PORT = 8080
API = f"http://127.0.0.1:{API_PORT}"

# Un seul déploiement tourne à la fois : sinon ils se partageraient le processeur et le disque
# pendant les mesures. Les deux clusters utilisent aussi les mêmes ports.
DEPLOYMENTS = {
    "local": {
        "uri": "mongodb://127.0.0.1:27018",
        "compose": ["docker", "compose", "-p", "urbanflow", "-f", "compose.yaml"],
        "instances": {"server": 27018},
        "containers": {"server": "urbanflow-mongo-1"},
    },
    "zone": {
        "uri": "mongodb://127.0.0.1:27019",
        "compose": ["docker", "compose", "-p", "urbanflow-zone", "-f", "compose.cluster.yaml"],
        "instances": {"shard1": 27021, "shard2": 27022},
        "containers": {"shard1": "urbanflow-zone-shard1-1", "shard2": "urbanflow-zone-shard2-1"},
        "mongos": "urbanflow-zone-mongos-1",
    },
    "month": {
        "uri": "mongodb://127.0.0.1:27019",
        "compose": ["docker", "compose", "-p", "urbanflow-month", "-f", "compose.cluster.yaml"],
        "instances": {"shard1": 27021, "shard2": 27022},
        "containers": {"shard1": "urbanflow-month-shard1-1", "shard2": "urbanflow-month-shard2-1"},
        "mongos": "urbanflow-month-mongos-1",
    },
}


def run(command):
    subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stop_other_deployments(name):
    for other, deployment in DEPLOYMENTS.items():
        if other != name:
            run(deployment["compose"] + ["stop"])


def start_deployment(name, initialized=True):
    """Démarre un déploiement. Un cluster neuf n'a pas encore de primaire : initialized=False."""
    stop_other_deployments(name)
    run(DEPLOYMENTS[name]["compose"] + ["up", "-d"])
    for port in DEPLOYMENTS[name]["instances"].values():
        if initialized:
            wait_for_primary(port)
        else:
            wait_for_port(port)


def wait_for_port(port):
    client = MongoClient(f"mongodb://127.0.0.1:{port}/?directConnection=true", serverSelectionTimeoutMS=3000)
    for _ in range(60):
        try:
            client.admin.command("ping")
            client.close()
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError(f"Le port {port} ne répond pas")


def wait_for_primary(port):
    """Répondre au ping ne suffit pas : un shard redémarré doit aussi redevenir primaire."""
    wait_for_port(port)
    client = MongoClient(f"mongodb://127.0.0.1:{port}/?directConnection=true", serverSelectionTimeoutMS=3000)
    for _ in range(60):
        if client.admin.command("hello").get("isWritablePrimary"):
            client.close()
            return
        time.sleep(2)
    raise RuntimeError(f"Le port {port} n'a pas de primaire : le déploiement est-il chargé ?")


def start_api(name, log_path=None, debug_queries=False):
    """Lance l'API sur un déploiement et attend qu'elle réponde."""
    # Une API restée allumée répondrait à la place de la nouvelle, peut-être sur un autre déploiement.
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", API_PORT)) == 0:
            raise RuntimeError(f"Le port {API_PORT} est déjà pris : arrêter l'API qui tourne encore")

    command = ["java", "-Xmx768m", "-jar", str(JAR)]
    if debug_queries:
        command.append("--logging.level.org.springframework.data.mongodb.core.MongoTemplate=DEBUG")
    uri = DEPLOYMENTS[name]["uri"] + "/?serverSelectionTimeoutMS=10000&connectTimeoutMS=10000"
    environment = {**os.environ, "MONGODB_URI": uri}
    if log_path:
        # Java garde sa propre copie du fichier. Sous Windows, un fichier resté ouvert ici
        # empêcherait ensuite de supprimer le dossier qui le contient.
        with open(log_path, "w") as log:
            process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=log, stderr=log)
    else:
        process = subprocess.Popen(command, cwd=ROOT, env=environment,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(120):
        if process.poll() is not None:
            raise RuntimeError("L'API s'est arrêtée au démarrage")
        try:
            urllib.request.urlopen(API + "/api/zones", timeout=2).close()
            return process
        except OSError:
            time.sleep(1)
    process.terminate()
    raise RuntimeError("L'API ne répond pas")


def stop_api(process):
    process.terminate()
    process.wait(timeout=30)


def call_api(path, method="GET", timeout=700):
    """Appelle l'API et renvoie (code HTTP, secondes, texte de la réponse). Code 0 : pas de réponse."""
    request = urllib.request.Request(API + path, method=method)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            body = response.read()
    except urllib.error.HTTPError as error:
        status = error.code
        body = error.read()
    except OSError as error:
        return 0, time.perf_counter() - started, str(error)
    return status, time.perf_counter() - started, body.decode("utf-8")


def repeat_calls(path, repetitions):
    """Répète une requête et renvoie (temps des réussites, codes des échecs, dernier code, dernier texte).

    Le temps d'une erreur ne mesure pas la requête : il n'entre pas dans les statistiques.
    """
    times, errors = [], []
    status, body = 0, ""
    for _ in range(repetitions):
        status, seconds, body = call_api(path)
        if status == 200:
            times.append(seconds)
        else:
            errors.append(status)
    return times, errors, status, body


def container_usage(container):
    """Temps CPU cumulé (secondes) et mémoire utilisée (Mo) d'un conteneur."""
    cpu = subprocess.check_output(["docker", "exec", container, "cat", "/sys/fs/cgroup/cpu.stat"], text=True)
    memory = subprocess.check_output(["docker", "exec", container, "cat", "/sys/fs/cgroup/memory.current"], text=True)
    usage = int(cpu.splitlines()[0].split()[1])
    return usage / 1e6, int(memory) / 1e6


def instance_counters(name):
    """Compteurs cumulés de chaque serveur de données, à comparer avant et après une charge."""
    counters = {}
    deployment = DEPLOYMENTS[name]
    for instance, port in deployment["instances"].items():
        with MongoClient(f"mongodb://127.0.0.1:{port}/?directConnection=true") as client:
            status = client.admin.command("serverStatus")
        cpu, memory = container_usage(deployment["containers"][instance])
        counters[instance] = {
            "keys_scanned": status["metrics"]["queryExecutor"]["scanned"],
            "docs_scanned": status["metrics"]["queryExecutor"]["scannedObjects"],
            "bytes_sent": status["network"]["bytesOut"],
            "cpu_seconds": cpu,
            "memory_mb": memory,
        }
    # mongos ne stocke rien, mais il reçoit les résultats des shards et peut faire la fusion.
    if "mongos" in deployment:
        with MongoClient(deployment["uri"]) as client:
            status = client.admin.command("serverStatus")
        cpu, memory = container_usage(deployment["mongos"])
        counters["mongos"] = {"bytes_sent": status["network"]["bytesOut"], "cpu_seconds": cpu, "memory_mb": memory}
    return counters


def counters_delta(before, after):
    """Travail fait par chaque serveur entre deux relevés. La mémoire reste une valeur à l'instant t."""
    delta = {}
    for instance, values in after.items():
        delta[instance] = {key: round(value - before[instance][key], 3) for key, value in values.items()}
        delta[instance]["memory_mb"] = round(values["memory_mb"], 1)
    return delta


def instance_storage(name, database="urbanflow"):
    """Lignes et place disque de chaque serveur de données."""
    storage = {}
    for instance, port in DEPLOYMENTS[name]["instances"].items():
        with MongoClient(f"mongodb://127.0.0.1:{port}/?directConnection=true") as client:
            stats = client[database].command("collStats", "trips")
        storage[instance] = {
            "documents": stats["count"],
            "storage_mb": round(stats["storageSize"] / 1e6, 1),
            "index_mb": round(stats["totalIndexSize"] / 1e6, 1),
        }
    return storage


def summarize(times):
    """Tendance centrale et dispersion d'une série de temps."""
    if not times:
        return {"times": [], "median": None, "min": None, "max": None, "stdev": None}
    return {
        "times": [round(t, 3) for t in times],
        "median": round(statistics.median(times), 3),
        "min": round(min(times), 3),
        "max": round(max(times), 3),
        "stdev": round(statistics.stdev(times), 3) if len(times) > 1 else 0,
    }


def write_environment(name):
    """Note le matériel, les versions et les limites, que les mesures seules ne disent pas."""
    docker = json.loads(subprocess.check_output(["docker", "info", "--format", "{{json .}}"], encoding="utf-8"))
    java = subprocess.run(["java", "-version"], capture_output=True, encoding="utf-8").stderr.splitlines()[0]
    instances = {}
    for instance, port in DEPLOYMENTS[name]["instances"].items():
        with MongoClient(f"mongodb://127.0.0.1:{port}/?directConnection=true") as client:
            status = client.admin.command("serverStatus")
        instances[instance] = {
            "mongodb": status["version"],
            "cache_bytes": status["wiredTiger"]["cache"]["maximum bytes configured"],
        }
    write_json(RESULTS / "experiments" / "environment" / f"{name}.json", {
        "date": time.strftime("%Y-%m-%d"),
        "machine": {"system": platform.platform(), "processor": platform.processor(), "logical_cpus": os.cpu_count()},
        "docker": {"version": docker["ServerVersion"], "cpus": docker["NCPU"],
                   "memory_gb": round(docker["MemTotal"] / 1e9, 1), "kernel": docker["KernelVersion"]},
        "python": platform.python_version(),
        "java": java,
        "api_heap": "-Xmx768m",
        "instances": instances,
    })


def write_json(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# Requêtes fixes des expériences. Elles sont les mêmes partout, avec les mêmes paramètres.
BROOKLYN_WEEKS = (
    "borough=Brooklyn&from=2024-03-25&to=2024-04-01&referenceFrom=2024-03-18&referenceTo=2024-03-25"
    "&baselineFrom=2024-01-08&baselineTo=2024-03-25"
)
CITY_ACROSS_APRIL = (
    "from=2024-04-01&to=2024-04-08&referenceFrom=2024-03-25&referenceTo=2024-04-01"
    "&baselineFrom=2024-03-04&baselineTo=2024-04-01"
)

REQUESTS = {
    # Une zone très active, peu de jours : une petite partie des données.
    "f1_jfk_pickup_march": "/api/activity?zoneId=132&direction=pickup&from=2024-03-01&to=2024-04-01",
    # Une zone de Brooklyn à l'arrivée sur tout le semestre : les trajets viennent de partout.
    "f1_parkslope_dropoff_semester": "/api/activity?zoneId=181&direction=dropoff&from=2024-01-01&to=2024-07-01",
    # Plusieurs zones et un semestre : traverse tous les serveurs.
    "f2_several_zones_semester": "/api/flows?zoneIds=181,189,33,52,97&from=2024-01-01&to=2024-07-01",
    "f2_brooklyn_quarter": "/api/flows?borough=Brooklyn&from=2024-01-01&to=2024-04-01",
    "f3_brooklyn_march": (
        "/api/unusual-activity?borough=Brooklyn&from=2024-03-11&to=2024-03-18"
        "&referenceFrom=2024-01-08&referenceTo=2024-03-10"
    ),
    "f4_jfk_midtown": (
        "/api/journeys?originId=132&destinationId=161&from=2024-03-11&to=2024-04-01"
        "&referenceFrom=2024-02-12&referenceTo=2024-03-04"
    ),
    "f5_brooklyn_march": "/api/flow-changes?" + BROOKLYN_WEEKS,
    # Toute la ville, avec des périodes de part et d'autre du 1er avril.
    "f5_city_across_april": "/api/flow-changes?" + CITY_ACROSS_APRIL,
}
