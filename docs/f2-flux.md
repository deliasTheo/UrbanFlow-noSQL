# F2 — Flux origine–destination

F2 est une API Spring Boot ; elle utilise les mêmes MongoDB, imports, serveur et
conventions de dates que F1, et réutilise les deux index F1.

## Essayer dans Postman

```text
GET http://localhost:8080/api/flows?zoneIds=181&from=2024-01-01&to=2024-02-01
GET http://localhost:8080/api/flows?zoneIds=181,189&from=2024-01-01&to=2024-02-01
GET http://localhost:8080/api/flows?borough=Brooklyn&from=2024-01-01&to=2024-02-01
```

Choisir exactement une sélection : zoneIds (liste d'identifiants uniques après
déduplication) OU borough (nom insensible à la casse). Toute la ville reste
accessible via les boroughs ou une liste de zones. Les noms de zones ne sont
pas des identifiants. Une zone/borough inconnu donne 404 ; paramètres invalides
ou deux sélections simultanées donnent 400. Les erreurs MongoDB et l'absence
d'import complet donnent 503, sans réponse partielle.

L'intervalle porte toujours sur **le départ**, en heure locale de New York,
début inclus et fin exclue, pour les deux directions comparées.
Le profil flows exclut NEGATIVE_AMOUNT, EXACT_DUPLICATE et UNKNOWN_ZONE.
Les codes inconnus signalés par l'ingestion sont 264/265 ; ce profil n'est pas
une validation générale de tous les codes invalides possibles.

Paramètres de lecture, exposés pour éviter des seuils cachés :

| Paramètre | Défaut | Sens |
|---|---:|---|
| limit | 10 | Nombre maximal de destinations et de paires affichées, 1..100 |
| minTrips | 20 | Effectif retenu minimum d'une destination/paire affichée |
| minWeeklyTrips | 5 | Seuil d'une semaine suffisamment active |
| regularFraction | 0.75 | Fraction minimale de semaines actives pour regular |
| peakShare | 0.5 | Part minimale de la semaine dominante pour peak |

Ces valeurs sont des règles exploratoires, pas des seuils statistiques ou
prescrits par le sujet. Les seuils entiers sont positifs et les fractions dans ]0,1].

## Réponse et interprétation

`totals` compte tous les trajets au départ de l'aire avant limitation et seuils,
avec raw/retained/excluded. `destinations` classe les destinations en cumulant
les départs de toute l'aire. `pairs` classe chaque paire de zones séparément.
Les tris sont par effectif retenu décroissant, puis identifiants croissants pour
rendre les ex aequo déterministes. Les trajets internes à l'aire sont inclus.
Les parts ont pour dénominateur tous les départs retenus de l'aire, pas seulement
le top affiché. Le top ne somme donc pas nécessairement à 100 %.

`eligiblePairs` indique le nombre de paires au seuil ; `belowMinTripsPairs`
compte les paires brutes sous le seuil, y compris celles entièrement exclues.
Ces dernières ne deviennent pas des flux importants simplement parce qu'elles
ont une forte variation relative. Augmenter minTrips ne modifie pas les totaux.

Chaque paire contient :

- les zones avec leurs identifiants, noms et boroughs ; les comptes et sa part ;
- `reverseRetained`, le nombre dans le sens opposé sur le même intervalle de
  départ et avec le même profil, même si le retour est sous minTrips ;
- `directionalBalance = (aller-retour)/(aller+retour)`, entre -1 et 1. Ce n'est
  pas un test statistique. Pour une même zone origine/destination, retour et
  balance sont null : ce n'est pas une comparaison de deux directions ;
- toutes les semaines touchées par l'intervalle, avec zéros et effectifs
  bruts/retenus/exclus ; les semaines partielles sont indiquées ;
- les comptes par fichier source pour tracer ce résultat et ceux du retour
  (`reverseSources`, vide pour un trajet dans une même zone).

Les sources globales justifient les totaux sortants ; les sources par destination
et par paire justifient chacun de ces résultats. La valeur reverseRetained se retrouve en demandant la
zone opposée et en abaissant minTrips si nécessaire. Les sources consultées
restent les mêmes fichiers complets.

## Régularité et pics

Les semaines vont du lundi au lundi. La classification ne prend que les semaines
entièrement contenues dans l'intervalle : pas de comparaison d'une semaine de
sept jours avec une tranche de deux jours.

1. Si un mois source attendu manque ou s'il y a moins de trois semaines complètes :
   `insufficient_history`. Les comptes restent affichés.
2. Sinon, si au moins regularFraction des semaines complètes atteignent
   minWeeklyTrips : `regular`.
3. Sinon, si la semaine complète dominante atteint minWeeklyTrips et représente
   au moins peakShare des trajets des semaines complètes : `peak`.
4. Sinon : `variable`.

La priorité est regular puis peak : un lien régulier peut aussi avoir une semaine
très forte. `qualifyingWeeks`, `referenceWeeks` et `peakWeekShare` exposent les
preuves et permettent une autre lecture. peakWeekShare est null s'il n'y a aucun
trajet retenu dans les semaines de référence.

La présence d'un fichier mensuel complete ne prouve pas une couverture parfaite
chaque jour. `missingSourceMonths` est un contrôle conservateur des mois attendus,
pas une détection de toutes les lacunes. Les volumes sont des lignes sources
retenues, pas une mesure de demande ni une reconstruction des routes physiques.
Les semaines avec changement d'heure ne sont pas normalisées par heure ; les
comparaisons de calendrier plus fines relèvent de F3.

## Comprendre le pipeline MongoDB

`FlowController` reçoit les paramètres ; `FlowService` résout l'aire via zones,
lit les imports complets et traite de petits comptes agrégés. `FlowRepository`
construit et exécute trois étapes sur les trajets. Il ne charge pas les trajets
détaillés en Java. Exemple simplifié pour la zone 181 :

```javascript
[
  { $match: {
    "source.file_id": { $in: [ /* imports complete */ ] },
    "data.tpep_pickup_datetime": {
      $gte: "2024-01-01T00:00:00", $lt: "2024-02-01T00:00:00"
    },
    $or: [
      { "data.PULocationID": { $in: [181] } },
      { "data.DOLocationID": { $in: [181] } }
    ]
  } },
  // $project : origin, destination, week, source, retained
  // $group : clé { origin, destination, week, source }, raw et retained
]
```

### `$match`, `$or`, `$in` : lire les départs ET les retours

`$match` filtre les documents. Les conditions principales sont combinées par ET.
`$or` exige au moins l'une des deux conditions : départ dans l'aire OU arrivée
dans l'aire. On a besoin de cette seconde branche pour comparer un aller vers
Manhattan à son retour depuis Manhattan. Un trajet interne satisfaisant les
deux branches ne sort qu'une fois : `$or` ne duplique pas les documents.
`$in` accepte une valeur appartenant à une liste de zones ou de fichiers.

### `$project` : préparer la semaine et la qualité

Comme F1, `$project` crée des champs intermédiaires sans écrire dans la base.
`origin`, `destination` et `source` reprennent les champs existants. Le booléen
retained utilise `$ifNull`, `$setIntersection`, `$size` et `$eq` : aucun flag du
profil flows ne doit être présent. Une ligne cumulant deux flags reste une
seule exclusion, grâce au booléen.

`$dateFromString` permet les calculs calendaires sur la chaîne ISO locale.
`$dateTrunc` avec unit=week et startOfWeek=monday trouve le lundi de cette
semaine. `$dateToString` le remet au format AAAA-MM-JJ. Comme F1, on préserve
les chiffres locaux sans appliquer un décalage UTC : il s'agit du calendrier,
pas d'un calcul de durée. Les flags stockés restent inchangés.

### `$group`, `$sum`, `$cond` : compter dans MongoDB

La clé `_id` du groupe est un objet {origin,destination,week,source}. Chaque
combinaison produit une ligne résumée. `$sum: 1` compte les candidats bruts ;
`$sum: {$cond: ["$retained",1,0]}` compte les retenus.

Contrairement à F1, on ne met pas toutes les paires d'une grande aire dans un
unique `$facet` : le tableau résultant pourrait atteindre la limite BSON de
16 Mo. MongoDB renvoie plusieurs documents agrégés. Le group peut utiliser le
disque (`allowDiskUse`) et est limité à 120 secondes (`maxTime`). Java rassemble
les comptes par paire et destination, ajoute les semaines à zéro, calcule les
parts et classe les résultats. Ce compromis évite des requêtes séparées par
paire mais conserve en mémoire les groupes, pas seulement le top : le coût augmente
avec la durée et l'étendue de l'aire.

### Index réutilisés de F1

Chaque branche du `$or` peut exploiter un index zone/date :

```javascript
{ "data.PULocationID": 1, "data.tpep_pickup_datetime": 1 }
{ "data.DOLocationID": 1, "data.tpep_dropoff_datetime": 1 }
```

Les retours restent filtrés sur leur date de départ. Dans l'index d'arrivée F1,
le second champ est une date d'arrivée : il peut donc aider par la zone, sans
borner directement la date de départ. Aucun troisième index n'est ajouté sans
mesure. Pour une aire large, MongoDB peut préférer COLLSCAN ; on ne force pas
un index par hint. Les plans réels sont archivés avec le benchmark.

## Reproduire les contrôles et mesures

Le protocole utilise une base dédiée, janvier 2024 **complet** et deux requêtes :
zone 181 et Brooklyn.

```bash
python -m urbanflow.ingest --month 2024-01 --database urbanflow_f2_benchmark
# Dans backend : ./mvnw package (Windows : .\mvnw.cmd package)
# Lancer l'API avec MONGODB_DATABASE=urbanflow_f2_benchmark et PORT=8081
python scripts/benchmark-f2.py --database urbanflow_f2_benchmark
python scripts/verify-f2-parquet.py --api http://127.0.0.1:8081
```

Le benchmark refuse de partir d'une collection déjà indexée autrement que par
_id_ ; il ne supprime jamais les index d'une base existante. Utiliser une nouvelle
base dédiée et l'API associée pour une répétition. Il crée ensuite les deux index
F1 et les laisse en place. Ne pas exécuter en parallèle avec un import.

Chaque phase fait un échauffement puis trois appels mesurés par requête. Les
caches restent actifs, sans promesse de froid. Le script compare toutes les
réponses JSON avant/après et archive temps, variabilité, tailles et explain.
`ExportFlowPipeline.java` réutilise exactement le constructeur Java du pipeline
de production pour explain ; il nécessite un JDK 21 et le jar compilé courant.

Dans explain, COLLSCAN signifie lecture de collection ; IXSCAN, parcours d'index ;
FETCH, lecture du document après l'index ; OR/SUBPLAN peut combiner les branches.
`totalDocsExamined` compte les documents examinés et `totalKeysExamined` les clés
d'index consultées. Ces nombres expliquent mieux le travail que le temps seul.
La vérification indépendante relit le Parquet, recalcule les exclusions et les
comptes sans MongoDB, puis compare totaux, classement, retours et séries hebdomadaires.


Les résultats réellement mesurés, exemples vérifiés et limites sont rassemblés
dans [la synthèse F2](../results/performance/f2/synthese.md).
