# UrbanFlow

Plateforme d'analyse de la mobilité urbaine construite sur les enregistrements
de trajets des taxis jaunes de New York (NYC TLC Yellow Taxi Trip Records).

Projet 3 — Big Data et NoSQL, Master 2 SLCD, Université Côte d'Azur (2026-2027).

## Périmètre

| Élément | Valeur |
|---|---|
| Mois d'étude | 2024-01, 2024-02, 2024-03 (passage à l'heure d'été le 10 mars) |
| Mois de mise à jour (F6) | 2024-04 |
| Zone d'étude | Brooklyn |
| Mois d'expérience (E1–E3, six mois) | 2024-05, 2024-06 |

La plateforme couvre toute la ville ; Brooklyn sert aux exemples détaillés. Ce
périmètre se modifie dans `urbanflow/config.py`.

## Arborescence

```
urbanflow/
  config.py          chemins, URL des sources, périmètre d'étude
  download.py        téléchargement des fichiers et manifeste de provenance
  ingest.py          import MongoDB, identité des trajets, service F6
  deploy.py          index, et placement des trajets sur le cluster
  timeutil.py        conversion des heures locales en UTC, durées robustes aux changements d'heure
  quality.py         catalogue des anomalies et profils de filtrage
  quality_report.py  rapport de qualité (fréquences, exemples, effet du filtrage)
backend/             API Spring Boot : services F1 à F6
scripts/             expériences, comparaisons et vérifications indépendantes
data/
  raw/               fichiers TLC (non versionnés, re-téléchargeables)
  manifest.json      provenance : URL, date, taille, SHA-256, nombre de lignes
results/             rapport de qualité, mesures brutes et vérifications
compose.yaml         serveur MongoDB local
compose.cluster.yaml cluster : deux shards, un serveur de configuration, un routeur mongos
docs/                modèle de données, guides des services, prédiction de E3
```

## Installation

Prérequis : Python 3.12, JDK 21, Docker Desktop. Le
[guide d'installation](docs/installation-locale.md) détaille chaque étape.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows ; source .venv/bin/activate sous Linux/macOS
pip install -r requirements.txt
python -m urbanflow.download
cd backend && ./mvnw -DskipTests package && cd ..      # Windows : .\mvnw.cmd
```

`urbanflow.download` récupère la table des zones et les six mois dans `data/raw/`,
puis écrit `data/manifest.json`. Un fichier déjà présent n'est pas re-téléchargé ;
son empreinte est recontrôlée à chaque exécution.

## Déploiement local

```bash
docker compose up -d --wait
python -m urbanflow.deploy --placement local
python -m urbanflow.ingest --month 2024-01
python -m urbanflow.ingest --month 2024-02
python -m urbanflow.ingest --month 2024-03
java -jar backend/target/urbanflow-api-0.1.0.jar
```

L'API écoute sur `http://127.0.0.1:8080`. MongoDB écoute uniquement sur localhost,
sans authentification : ne pas exposer ces ports sur Internet.

## Déploiement réparti

Deux configurations existent, chacune avec ses propres volumes. Elles utilisent
les mêmes ports : une seule tourne à la fois.

| Configuration | Placement | Projet Docker |
|---|---|---|
| `zone` | chaque zone de départ est entière sur un shard, les zones sont réparties pour équilibrer les départs | `urbanflow-zone` |
| `month` | janvier à mars sur le premier shard, à partir d'avril sur le second | `urbanflow-month` |

Sous PowerShell, pour le placement par zone :

```powershell
docker compose -p urbanflow-zone -f compose.cluster.yaml up -d
python -m urbanflow.deploy --placement zone
$env:MONGODB_URI = "mongodb://127.0.0.1:27019"
python -m urbanflow.ingest --month 2024-01
java -jar backend/target/urbanflow-api-0.1.0.jar
```

| Port | Rôle |
|---|---|
| 27018 | serveur local |
| 27019 | routeur mongos, le seul point d'entrée de l'API |
| 27020 | serveur de configuration |
| 27021, 27022 | shards |

Le cache MongoDB est fixé à 1,4 Go au total dans les deux déploiements.

## Services

| Service | Requête | Guide |
|---|---|---|
| F1, activité d'une zone | `GET /api/activity` | [F1](docs/f1-activite.md), [opérateurs MongoDB](docs/f1-mongodb-explique.md) |
| F2, flux origine-destination | `GET /api/flows` | [F2](docs/f2-flux.md) |
| F3, activité inhabituelle | `GET /api/unusual-activity` | [F3](docs/f3-activite-inhabituelle.md) |
| F4, durées et distances | `GET /api/journeys` | [F4](docs/f4-caracteristiques-trajets.md) |
| F5, changements de parts des flux | `GET /api/flow-changes` | [F5](docs/f5-changements-flux.md) |
| F6, mise à jour de l'archive | `POST /api/imports`, `GET /api/imports` | ci-dessous |
| Référentiel des zones | `GET /api/zones` | [F1](docs/f1-activite.md) |

### F6 : importer un mois ou un extrait

```text
POST http://localhost:8080/api/imports?month=2024-04
POST http://localhost:8080/api/imports?file=chemin/extrait.parquet
POST http://localhost:8080/api/imports?file=chemin/mai.parquet&month=2024-05
GET  http://localhost:8080/api/imports
```

- `month` seul importe un mois du manifeste.
- `file` importe un Parquet hors manifeste. Sans `month`, il compte comme un
  extrait : ses trajets sont visibles, mais le mois n'est pas considéré comme couvert.
- Avec `file` et `month`, le fichier est déclaré couvrir le mois entier.

La même chose existe en ligne de commande : `python -m urbanflow.ingest --month 2024-04`
ou `--file extrait.parquet`. La réponse contient le résumé de l'import : lignes
ajoutées, lignes déjà présentes, anomalies et effet des profils de filtrage. Un
paramètre invalide donne 400, un échec d'import 500, et un second import
simultané 409.

L'identité d'un trajet est expliquée dans
[le modèle de données](docs/modele-donnees.md#identité-dun-trajet).

## Choix de préparation des données

**Affectation temporelle.** Un trajet appartient à la période qui contient son
heure de prise en charge, en heure locale de New York, indépendamment du
fichier mensuel qui le contient. Pour F1 et F3 en mode arrivées, le filtrage et
les regroupements utilisent la date et l'heure d'arrivée.

**Durées.** Les heures locales sont converties en UTC avant soustraction, ce
qui corrige les trajets à cheval sur un changement d'heure. Les heures
inexistantes (passage à l'heure d'été) ou ambiguës (retour à l'heure d'hiver)
ne peuvent pas être converties : ces trajets sont signalés `DST_UNRESOLVED`.

**Annulations.** Une écriture d'annulation reprend le fournisseur, les
horodatages et les zones d'un trajet avec un montant total opposé. Elle est
exclue des comptages ; le trajet d'origine est conservé, car le déplacement a
bien été enregistré.

**Profils de filtrage.** Aucune ligne n'est supprimée à l'ingestion. Chaque
service applique le profil qui le concerne :

| Profil | Services | Anomalies exclues |
|---|---|---|
| `activity` | F1, F3 | montant négatif, doublon exact |
| `flows` | F2, F5 | `activity` + zone inconnue (264/265) |
| `journey` | F4 | `flows` + durée ≤ 0 ou > 6 h, distance nulle ou > 100 miles, vitesse > 80 mph, heure non convertible |

Le détail des règles se trouve dans `urbanflow/quality.py`. Le rapport de qualité
s'obtient avec `python -m urbanflow.quality_report` et s'écrit dans `results/quality/`.

## Reproduire les expériences

Chaque script démarre le déploiement voulu et arrête les autres. Le port 8080 doit
être libre. Le chargement refuse une base non vide, car un mois déjà importé ne
serait pas remesuré ; la commande pour repartir de volumes vides s'affiche alors.
Elle efface les données du déploiement concerné.

```bash
# E1 et coût d'ingestion
python scripts/load-deployment.py --deployment local --measure
python scripts/load-deployment.py --deployment zone
python scripts/load-deployment.py --deployment month

# Travail de chaque instance pour trois types de requêtes
python scripts/explain-requests.py --deployment local
python scripts/explain-requests.py --deployment zone
python scripts/explain-requests.py --deployment month

# E2, puis comparaison automatique des réponses
python scripts/e2-deployments.py --deployment local
python scripts/e2-deployments.py --deployment zone
python scripts/e2-deployments.py --deployment month
python scripts/compare-deployments.py

# E3 : déposer d'abord docs/prediction-e3.md
python scripts/e3-workloads.py --deployment local
python scripts/e3-workloads.py --deployment zone
python scripts/e3-workloads.py --deployment month

# Perte d'une instance
python scripts/lose-instance.py --deployment zone
python scripts/lose-instance.py --deployment month
```

| Sortie | Contenu |
|---|---|
| `results/experiments/environment/` | matériel, versions et cache réel de chaque déploiement |
| `results/experiments/ingestion/` | temps d'import, stockage, latences de E1, résultat de F6 |
| `results/experiments/e2/`, `e3/` | temps, dispersion et travail de chaque instance |
| `results/distributed/` | placement, plans `explain`, comparaison, perte d'instance |

Les scripts `e2` et `e3` se terminent en erreur si un appel a échoué : ces mesures
ne sont alors pas exploitables.

## Vérifications

**Service F6, sur de vraies lignes TLC et dans une base à part :**

```powershell
python scripts/verify-f6.py
python -m urbanflow.deploy --placement zone --database urbanflow_f6_test
$env:MONGODB_URI = "mongodb://127.0.0.1:27019"
python scripts/verify-f6.py --keep-database
```

**Résultats sur six mois, recalculés depuis les Parquet sans lire MongoDB**, API
lancée sur n'importe quel déploiement chargé :

```bash
python scripts/verify-registered-period.py
```

**Résultats sur janvier seul.** Ces scripts attendent une base qui ne contient que
janvier, et une API lancée sur cette base avec `MONGODB_DATABASE` et `PORT` :

| Service | Base | Port | Commandes |
|---|---|---|---|
| F2 | `urbanflow_f2_benchmark` | 8081 | `benchmark-f2.py`, `verify-f2-parquet.py` |
| F3 | `urbanflow_f3_benchmark` | 8083 | `benchmark-f3.py`, `verify-f3-parquet.py` |
| F4 | `urbanflow_f4_benchmark` | 8084 | `benchmark-f4.py`, `verify-f4-parquet.py`, `verify-f4-dst.py` |
| F5 | `urbanflow_f5_benchmark` | 8086 | `benchmark-f5.py`, `verify-f5-parquet.py` |

La base se remplit avec `python -m urbanflow.ingest --month 2024-01 --database <base>`.
Les benchmarks comparent les index et exigent une base sans index analytique.
Les mesures et les vérifications déjà réalisées sont dans `results/performance/`.
