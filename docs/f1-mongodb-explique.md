# Comprendre F1 et ses requêtes MongoDB

Ce document complète le guide `f1-activite.md`, opérateur par opérateur.

## Du GET aux documents stockés

Postman appelle `GET /api/activity` avec zoneId, direction, from et to.
Spring convertit les dates et le sens ; le service vérifie l'intervalle et la zone.
Le repository utilise `MongoTemplate`, le client MongoDB de Spring : il envoie des
requêtes au serveur MongoDB. Ni JPA ni SQL ne sont employés.

Avant l'agrégation, deux lectures ont lieu :

```javascript
db.zones.findOne({ _id: 181 });
db.imports.find({ status: "complete" });
```

La première vérifie l'identifiant et récupère le nom. La seconde fournit les
SHA-256 autorisés. On ne filtre pas ces imports sur leur mois annoncé : les dates
réelles d'un trajet peuvent déborder du mois du fichier.

Un pipeline est une liste ordonnée d'étapes. Chaque étape reçoit le résultat de
la précédente. Dans le code Java, `Document` construit les objets BSON compris
par MongoDB ; `context -> new Document("$match", match)` est simplement la
représentation Java d'une étape. `aggregate(..., "trips", Document.class)` exécute
ces étapes dans la collection trips et lit les petits résultats agrégés en Java.

## 1. `$match` : sélectionner les lignes candidates

Pour les départs de Park Slope en janvier, la première étape équivaut à :

```javascript
{ $match: {
  "data.PULocationID": 181,
  "data.tpep_pickup_datetime": {
    $gte: "2024-01-01T00:00:00", $lt: "2024-02-01T00:00:00"
  },
  "source.file_id": { $in: [ /* SHA-256 des imports complete */ ] }
} }
```

Les conditions au même niveau sont combinées par ET. `$gte` signifie supérieur
ou égal, `$lt` strictement inférieur. `$in` signifie appartenir à la liste.
En dropoff, on remplace les deux champs par DOLocationID et tpep_dropoff_datetime.
Les dates sont des chaînes ISO locales : leur ordre lexical est chronologique
dans le format écrit par l'ingestion. La borne de fin exclue évite de compter
minuit deux fois entre janvier et février.

## 2. `$project` : préparer les valeurs à regrouper

`$project` conserve ou calcule des champs, sans modifier les documents stockés.
Le code produit heure, jour de semaine, date, identifiant source et `retained`.

- `$dateFromString` transforme la chaîne en date pour les opérateurs calendaires.
  Sans décalage, elle est interprétée en UTC, puis l'heure UTC est extraite : on
  retrouve ainsi les chiffres de l'heure locale enregistrée, sans les décaler.
  Ce procédé est réservé à ces regroupements ; il ne calcule pas une durée réelle.
- `$hour` extrait 0..23 ; `$isoDayOfWeek` donne lundi=1 à dimanche=7.
- `$substrBytes` extrait les dix premiers caractères, soit AAAA-MM-JJ.
- `$ifNull` remplace un tableau quality_flags absent/null par un tableau vide.
- `$setIntersection` trouve les flags communs entre ceux du trajet et
  `["NEGATIVE_AMOUNT", "EXACT_DUPLICATE"]`.
- `$size` compte ces flags ; `$eq: [nombre, 0]` produit un booléen : la ligne est
  retenue seulement si aucun motif d'exclusion ne s'applique.

Par exemple, une ligne portant les deux flags reste une seule ligne
brute, avec retained=false. Elle sera exclue une seule fois du total.

Une chaîne `"$source.file_id"` représente la valeur du champ, alors que
`"source.file_id"` utilisée comme clé de filtre désigne le nom du champ.
Le préfixe `$` est donc significatif dans les expressions d'agrégation.

## 3. `$facet` : calculer plusieurs vues sur les mêmes candidats

`$facet` crée plusieurs branches à partir des lignes sélectionnées. F1 calcule
les totaux, les heures, les jours de semaine, les dates, les sources et les motifs.
Cela évite une requête de scan par répartition. Chaque branche renvoie un tableau.

Le coeur des branches de comptage est :

```javascript
{ $group: {
  _id: "$hour",
  raw: { $sum: 1 },
  retained: { $sum: { $cond: ["$retained", 1, 0] } }
} },
{ $sort: { _id: 1 } }
```

`$group` rassemble les lignes ayant la même clé `_id`. Ici une sortie par heure.
`_id` est la clé du groupe de résultat, pas l'identifiant d'un trajet.
`$sum: 1` compte toutes les lignes ; `$cond` vaut 1 pour une ligne retenue et 0
sinon. Pour le total global, `_id: null` met toutes les lignes dans un seul groupe.
`$sort: { _id: 1 }` classe les heures dans l'ordre croissant.
Java calcule `excluded = raw - retained` et ajoute les heures/jours absents avec
zéro. Les dates sans ligne brute ne sont pas ajoutées. Il ne recompte aucun trajet.

Pour les motifs, `$unwind: "$quality_flags"` produit une ligne par flag du
trajet, puis `$match` ne conserve que les motifs exclus, et `$group` les compte.
Les comptes par motif peuvent donc se chevaucher, contrairement au total exclu.

## 4. Pourquoi les index accélèrent le filtre

```javascript
{ "data.PULocationID": 1, "data.tpep_pickup_datetime": 1 }
{ "data.DOLocationID": 1, "data.tpep_dropoff_datetime": 1 }
```

Un index composé est une structure triée sur plusieurs champs, ici la zone
puis la date. MongoDB peut chercher une zone précise puis une plage de dates,
au lieu de lire tous les documents (COLLSCAN). Le plan peut contenir IXSCAN
(parcours de l'index) puis FETCH (lecture des documents correspondants).

Les documents doivent encore être lus : source.file_id et quality_flags ne sont
pas dans ces index, et les regroupements doivent être effectués. Il ne s'agit
pas d'un cache des réponses. Les index sont non uniques ; ils ne changent pas
l'identité des lignes ni les règles de déduplication.

Les premières mesures, leurs conditions et leurs limites sont dans
`results/performance/f1-indexes.md`.
La baisse avec répétition sans index est distincte de l'amélioration après index.
Les index sont créés par `urbanflow/deploy.py` ; MongoDB les maintient ensuite
pendant les écritures. Ils ne modifient aucun résultat attendu.
