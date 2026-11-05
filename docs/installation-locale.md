# Installer UrbanFlow sur son PC

La base de ton PC est indépendante de celle du cloud. Le code, les fichiers TLC
et les commandes ci-dessous permettent de reconstruire le même contenu.
Prérequis : Git, Python 3.12, Docker Desktop démarré (mode conteneurs Linux),
MongoDB Compass. Prévoir plusieurs Go de mémoire disponible et d’espace disque ;
le calcul qualité charge un mois entier en mémoire.

## 1. Cloner la branche

Dans un terminal :

```bash
git clone --branch feature/importation-data https://github.com/deliasTheo/UrbanFlow-noSQL.git
cd UrbanFlow-noSQL
python -m venv .venv
```

Sous Windows, si nécessaire, remplacer `python` par `py -3.12` pour créer le venv.

## 2. Installer les dépendances

Windows PowerShell, sans devoir activer le venv :

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Linux/macOS :

```bash
.venv/bin/python -m pip install -r requirements.txt
```

## 3. Démarrer MongoDB

À la racine du dépôt :

```bash
docker compose up -d --wait
docker compose ps
```

UrbanFlow utilise le port 27018 sur ton PC ; ton MongoDB habituel peut continuer
à utiliser le port 27017. Le conteneur conserve son port interne 27017.
Le conteneur utilise MongoDB 8.0.16 et le volume nommé `urbanflow_mongo-data`.

## 4. Télécharger puis importer janvier

Windows PowerShell :

```powershell
.\.venv\Scripts\python.exe -m urbanflow.download --months 2024-01
.\.venv\Scripts\python.exe -m urbanflow.ingest --month 2024-01
```

Linux/macOS :

```bash
.venv/bin/python -m urbanflow.download --months 2024-01
.venv/bin/python -m urbanflow.ingest --month 2024-01
```

Le téléchargement récupère aussi le référentiel des zones. L’import peut prendre
plusieurs minutes : attendre la fin et l’état `complete`. Janvier contient
2 964 624 lignes ; elles sont toutes conservées, y compris celles avec anomalies.
Relancer la commande d’import est sans effet sur un fichier déjà complet.

## 5. Ouvrir MongoDB Compass

Créer une connexion avec l’URI suivante :

```text
mongodb://127.0.0.1:27018
```

Cliquer sur Connect, puis ouvrir la base `urbanflow` :

- `trips` : les enregistrements TLC, dates locales dans `data`, durée et flags.
- `zones` : le référentiel (265 zones).
- `imports` : provenance, état et compteurs du fichier importé.
- `ingestion_lock` : verrou technique temporaire ; normalement vide hors import.

Dans `trips`, exemples de filtres Compass :

```javascript
{ "quality_flags": "NEGATIVE_AMOUNT" }
```

```javascript
{ "data.tpep_pickup_datetime": {
  "$gte": "2024-01-15T00:00:00",
  "$lt": "2024-01-16T00:00:00"
} }
```

La provenance est dans `source.file_id` et `source.row_number`. Le mois annoncé
par le fichier n’est pas forcément celui de chaque date enregistrée.

## 6. Vérifier depuis le terminal

```bash
docker compose exec mongo mongosh urbanflow --quiet --eval 'db.trips.countDocuments({})'
docker compose exec mongo mongosh urbanflow --quiet --eval 'db.imports.find({}, {status: 1, file_name: 1}).toArray()'
```

Attendu après janvier seul : 2 964 624 documents et un import `complete`.

## 7. Arrêter, reprendre ou mettre le code à jour

```bash
docker compose stop
docker compose up -d --wait
git pull --ff-only origin feature/importation-data
```

Le volume conserve les données après `stop` ou `docker compose down`.
**Ne pas utiliser `docker compose down -v` pour un arrêt normal : cela supprime
le volume et la base.**

Après un échec normal, corriger la cause puis relancer l’import : les lignes déjà
insérées sont conservées et les manquantes sont ajoutées. Un arrêt brutal peut
laisser le verrou ; uniquement après avoir vérifié qu’aucun import n’est encore
actif, le retirer puis relancer :

```bash
docker compose exec mongo mongosh urbanflow --quiet --eval 'db.ingestion_lock.deleteMany({})'
```

Une connexion Compass à cette URI montre la base de ton PC, pas la base cloud.
Pour février/mars, répéter téléchargement et import avec le mois correspondant.
Conserver avril à part pour tester F6. Cette version couvre les fichiers mensuels
identiques ; la gestion des extraits chevauchants reste à développer.

## Contrôles de développement (facultatif)

Utiliser le Python du venv comme plus haut :

```bash
python -m unittest discover -s tests -v
python -m scripts.verify_ingestion
```

La deuxième commande contrôle janvier dans la base `urbanflow`, ses flags et
des exemples contre les sources. Pour le test de reprise dans une base isolée,
activer `URBANFLOW_INTEGRATION=1` avant la première commande (PowerShell :
`$env:URBANFLOW_INTEGRATION="1"` ; bash : préfixer la commande avec
`URBANFLOW_INTEGRATION=1`). Le test supprime uniquement sa base de test aléatoire.
