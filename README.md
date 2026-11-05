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

Ce périmètre peut être modifié dans `urbanflow/config.py`.

Le [document de conception du modèle de données](docs/modele-donnees.md)
décrit le stockage proposé, les choix liés aux services F1–F6 et les validations
à réaliser avant l'ingestion en base.

## Arborescence

```
urbanflow/
  config.py          chemins, URL des sources, périmètre d'étude
  download.py        téléchargement des fichiers et manifeste de provenance
  ingest.py          import MongoDB direct, provenance et qualité
  timeutil.py        conversion des heures locales en UTC, durées robustes aux changements d'heure
  quality.py         catalogue des anomalies et profils de filtrage
  quality_report.py  rapport de qualité (fréquences, exemples, effet du filtrage)
data/
  raw/               fichiers TLC (non versionnés, re-téléchargeables)
  manifest.json      provenance : URL, date, taille, SHA-256, nombre de lignes
results/
  quality/           rapport de qualité (JSON + Markdown)
  ingestion/         compteurs des imports terminés
compose.yaml         serveur MongoDB local et volume persistant
docs/                modèle de données et guide d’installation locale
```

## Installation

Prérequis : Python 3.12, Docker Desktop (pour les étapes MongoDB).

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows ; source .venv/bin/activate sous Linux/macOS
pip install -r requirements.txt
```

## Utilisation

### 1. Récupération des données

```bash
python -m urbanflow.download
```

Télécharge la table des zones, les mois d'étude, le mois de mise à jour et les
mois d'expérience dans `data/raw/`, puis écrit `data/manifest.json`. Un fichier
déjà présent n'est pas re-téléchargé ; son empreinte est recontrôlée à chaque
exécution. D'autres mois peuvent être ajoutés :

```bash
python -m urbanflow.download --months 2024-07
```

### 2. Rapport de qualité

```bash
python -m urbanflow.quality_report
```

Produit `results/quality/quality_report.md` et `quality_report.json`
(quelques minutes pour six mois).

## Choix de préparation des données

**Affectation temporelle.** Un trajet appartient à la période qui contient son
heure de prise en charge, en heure locale de New York, indépendamment du
fichier mensuel qui le contient. Pour F1 en mode arrivées, le filtrage et les
regroupements utilisent toutefois la date et l'heure d'arrivée.

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

Le détail des règles se trouve dans `urbanflow/quality.py`.

### 3. Importer dans MongoDB

```bash
docker compose up -d --wait
python -m urbanflow.download --months 2024-01
python -m urbanflow.ingest --month 2024-01
```

Le [guide d’installation locale](docs/installation-locale.md) détaille toutes les
étapes, du clonage à MongoDB Compass, ainsi que la reprise d’un import.

Le script vérifie l’empreinte source, importe les zones, calcule les flags sur le
mois entier puis écrit les documents par lots de 5 000 (`--batch-size`). Le mois
entier reste chargé en mémoire pour détecter les doublons et annulations entre
lots. Les UTC sont temporaires ; seuls les dates locales sources et `duration_s`
sont conservés. Une durée non déterminable vaut `null`. Aucune ligne n’est supprimée.

La collection `imports` suit les états `loading`, `failed`, `complete`. Les futurs
services doivent sélectionner uniquement les fichiers `complete`. Les identités
fichier + ligne et les upserts permettent la reprise sans ajout de doublons.
Un fichier déjà complet est vérifié puis ignoré. Les extraits chevauchants ou les
versions modifiées demandent une politique supplémentaire avant F6.

`MONGODB_URI` permet de choisir le serveur ; `--database` choisit la base (défaut
`urbanflow`). `results/ingestion/AAAA-MM.json` contient les compteurs de contrôle.
MongoDB écoute uniquement sur localhost, sans authentification pour cet usage
local ; ne pas exposer ce port sur Internet. Les volumes ne vont pas dans Git.

## API — F1

Le backend Spring Boot (JDK 21) permet d'explorer l'activité d'une zone dans
Postman. Voir [F1 : installation, endpoints et règles de comptage](docs/f1-activite.md).
Le code est dans `backend/` ; les agrégations sont exécutées par MongoDB via
`MongoTemplate`. L'ingestion Python reste inchangée.

## API — F2

[F2 : flux origine–destination, règles, pipeline et mesures](docs/f2-flux.md).
Pour comprendre les opérateurs utilisés par F1, voir
[l'explication MongoDB de F1](docs/f1-mongodb-explique.md).

## API — F3

[F3 : activité inhabituelle, références, calendrier et pipelines MongoDB](docs/f3-activite-inhabituelle.md).
Les mesures et vérifications reproductibles sont dans `results/performance/f3/`.
