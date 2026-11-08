# Installer UrbanFlow

Prérequis : Git, Python 3.12, JDK 21, Docker Desktop démarré (mode conteneurs
Linux). MongoDB Compass est utile pour explorer la base. Prévoir plusieurs Go de
mémoire et d'espace disque : le calcul qualité charge un mois entier en mémoire.

## 1. Cloner le dépôt

```bash
git clone https://github.com/deliasTheo/UrbanFlow-noSQL.git
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

L'API lance elle-même l'import F6 avec le Python de `.venv` quand il existe.

## 3. Compiler l'API

```powershell
cd backend
.\mvnw.cmd -DskipTests package
cd ..
```

Sous Linux/macOS : `./mvnw -DskipTests package`. Maven est téléchargé par le wrapper
au premier lancement. Le résultat est `backend/target/urbanflow-api-0.1.0.jar`.

## 4. Démarrer MongoDB et créer les index

```bash
docker compose up -d --wait
docker compose ps
.venv/bin/python -m urbanflow.deploy --placement local      # Windows : .\.venv\Scripts\python.exe -m urbanflow.deploy --placement local
```

UrbanFlow utilise le port 27018, pour laisser libre le port 27017 d'un autre
MongoDB. Le conteneur utilise MongoDB 8.0.16 et le volume nommé
`urbanflow_mongo-data`. `urbanflow.deploy` crée les index utilisés par les services.

## 5. Télécharger puis importer janvier

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

Le téléchargement récupère aussi le référentiel des zones. L'import prend plusieurs
minutes : attendre la fin et l'état `complete`. Janvier contient 2 964 624 lignes ;
elles sont toutes conservées, y compris celles avec anomalies. Relancer la commande
sur un fichier déjà complet ne change rien.

Répéter ces deux commandes pour février et mars. Avril reste réservé au service F6.

## 6. Ouvrir MongoDB Compass

Créer une connexion avec l'URI suivante :

```text
mongodb://127.0.0.1:27018
```

Cliquer sur Connect, puis ouvrir la base `urbanflow` :

- `trips` : les enregistrements TLC, dates locales dans `data`, durée et flags.
- `zones` : le référentiel (265 zones).
- `imports` : provenance, état et compteurs des fichiers importés.

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
par le fichier n'est pas forcément celui de chaque date enregistrée.

## 7. Vérifier depuis le terminal

```bash
docker compose exec mongo mongosh urbanflow --quiet --eval 'db.trips.countDocuments({})'
docker compose exec mongo mongosh urbanflow --quiet --eval 'db.imports.find({}, {status: 1, file_name: 1}).toArray()'
```

Attendu après janvier seul : 2 964 624 documents et un import `complete`.

## 8. Lancer l'API

```bash
java -jar backend/target/urbanflow-api-0.1.0.jar
```

L'API écoute sur `http://127.0.0.1:8080`. Les requêtes de chaque service sont dans
le [README](../README.md#services).

## 9. Arrêter ou reprendre

```bash
docker compose stop
docker compose up -d --wait
```

Le volume conserve les données après `stop` ou `docker compose down`.
**Ne pas utiliser `docker compose down -v` pour un arrêt normal : cela supprime
le volume et la base.**

Après un import interrompu, corriger la cause puis relancer la même commande : les
lignes déjà insérées sont conservées et les manquantes sont ajoutées.
