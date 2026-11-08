# F4 — Comparer durées et distances

Ce guide explique les choix et les requêtes. Les mesures brutes et la synthèse
sont dans `results/performance/f4/`.

## API et paramètres

Exemples à essayer dans Postman :

```text
http://localhost:8080/api/journeys?originId=132&destinationId=161&from=2024-02-01&to=2024-03-01&referenceFrom=2024-01-01&referenceTo=2024-02-01
http://localhost:8080/api/journeys?originId=161&destinationId=236&from=2024-02-01&to=2024-03-01&referenceFrom=2024-01-01&referenceTo=2024-02-01
```

Le service compare une paire orientée à la fois ; on peut changer les deux zones
et les deux intervalles à chaque requête. Les départs déterminent l'appartenance
à une période, en heure locale de New York. Les fins sont exclues. Les périodes
sont non vides, sans chevauchement, référence avant période courante.
`minTrips=30` par défaut, minimum autorisé 2, règle exploratoire modifiable.

Retour 400 si paramètres invalides, 404 si zone inconnue, 503 si MongoDB est
indisponible ou aucun import complete disponible, 422 si plus de 200 000 lignes
candidates sont sélectionnées. Dans ce dernier cas, réduire les intervalles ;
aucune réponse partielle n'est présentée comme complète.

Les comparaisons portent sur les trajets enregistrés et leurs caractéristiques,
pas sur la vitesse de circulation d'un itinéraire précis. Les zones sont des
aires ; les routes physiques suivies ne sont pas connues.

## Trois ensembles explicites dans chaque période

- `raw` : toutes les lignes candidates des imports complete pour la paire et les dates.
- `activityExcluded` : montants négatifs et doublons exacts, écartés des statistiques.
- `retained` : lignes respectant le profil journey, utilisées dans `usable`.
- `lessReliable` : lignes restantes, utilisables selon activity mais exclues par
  journey, décrites séparément dans `unreliable`.

L'identité vérifiable est `raw = activityExcluded + retained + lessReliable`.
Les motifs d'exclusion sont comptés sur les candidats et peuvent se chevaucher.
Les comptes par fichier justifient chaque ensemble.

Journey reprend exactement les flags définis dans quality.py : NEGATIVE_AMOUNT,
EXACT_DUPLICATE, UNKNOWN_ZONE, NON_POSITIVE_DURATION, EXCESSIVE_DURATION,
ZERO_DISTANCE, IMPLAUSIBLE_DISTANCE, IMPLAUSIBLE_SPEED et DST_UNRESOLVED.
Les seuils de plausibilité restent ceux de l'ingestion : durée > 0 et <= 6 h,
distance non nulle et <= 100 miles, vitesse <= 80 mph, zones 264/265 exclues.
Ce profil n'est pas une validation générale de tous les codes invalides ou champs
manquants : F4 compte séparément les valeurs numériques absentes.

Les valeurs de unreliable sont descriptives, pas des estimations fiables : on
peut y voir des durées négatives, des distances nulles ou extrêmes. Les montants
négatifs/doublons n'y sont pas réintroduits. Les durées non résolues sont null,
non remplacées par une différence locale trompeuse.

## Statistiques exactes et interprétables

Pour durée (secondes) et distance (miles), chaque ensemble renvoie : nombre de
valeurs finies, valeurs manquantes, min, q25, médiane, q75, p90, max, moyenne,
écart-type de population et écart interquartile IQR=q75-q25.
Un ensemble vide a des statistiques null.

Les quantiles utilisent l'interpolation linéaire à l'indice `(n-1)*p`, comme
NumPy quantile(method="linear"). Par exemple, sur 10,20,30,40,
la médiane vaut 25 et q25 vaut 17,5. Ce n'est pas une approximation par digest.
La dispersion est calculée sur les valeurs observées ; ce n'est pas un intervalle
de confiance. Un grand nombre de lignes ne garantit pas l'indépendance des trajets.

`iqrOutliers` compte les valeurs strictement hors [q25-1,5 IQR,q75+1,5 IQR].
Elles restent dans les statistiques : le seuil est descriptif, pas une nouvelle
règle de suppression. Médiane, quartiles et p90 montrent la partie typique et la
queue de distribution que masquerait une seule moyenne.

Les calculs trient les mêmes valeurs avant de sommer pour rendre les sorties
reproductibles malgré un ordre de lecture MongoDB différent selon l'index.

## Comparer des compositions différentes

Une période peut contenir davantage de trajets longs ou de départs en pointe.
Une différence globale de durée ne suffit donc pas à conclure à un changement
de conditions de déplacement.

F4 expose les statistiques des trajets retenus par strate :

- lundi–vendredi / samedi–dimanche (jour ouvré au sens calendaire simplifié) ;
- créneaux de six heures : [0,6[, [6,12[, [12,18[, [18,24[ ;
- distances [0,2[, [2,5[, [5,10[, [10,+inf[ miles ; une catégorie missing
  reste visible si une distance manque malgré les flags existants.

Le jour et le créneau sont ceux du départ. Les jours fériés ne sont pas retirés
et ne sont pas reclassés en week-end : cette convention est explicite. Les
classes de distance sont grossières, pas un ajustement exact kilomètre par kilomètre.

La comparaison standardisée ne garde que les strates présentes avec au moins
minTrips durées valides dans les deux périodes. Elle prend leurs proportions
de la période de référence comme poids, identiques pour les deux moyennes de
durée. Leur différence est donc à composition commune sur ces strates.

`commonStrata`, les effectifs communs et leur fraction de chaque période exposent
la couverture de cet ajustement. Une fraction faible limite sa représentativité.
Le résultat est une **différence de moyennes pondérées**, distincte de la différence
des médianes globales ; ces deux indicateurs ne doivent pas être confondus.

Si un mois source manque : SOURCE_MONTH_MISSING et résultat standardisé null.
Si les durées valides globales sont sous minTrips : INSUFFICIENT_SAMPLE.
Si aucune strate commune n'atteint le seuil : NO_COMMON_STRATA.
Sinon COMPARABLE signifie que ces conditions descriptives sont remplies, pas
qu'une causalité est établie. Les différences globales disponibles restent
descriptives même si la standardisation n'est pas possible.

Les imports complets ne garantissent pas la couverture horaire ; les fichiers
consultés ne sont pas filtrés selon leur mois annoncé car des dates débordent.
Aucun taux de volume par jour n'est déduit de périodes de longueurs différentes.

## Durées et changement d'heure

Le repository lit **duration_s stockée à l'ingestion**. Il ne soustrait jamais les
chaînes locales pour calculer une durée. America/New_York -> UTC -> soustraction
est déjà effectué par Python. DST_SPANNING reste utilisable si journey l'autorise,
et son effectif retenu est exposé. DST_UNRESOLVED est exclu, durée null.

Contrairement à F3, on n'exclut pas toute la journée DST : F4 étudie précisément
des durées individuelles correctement calculées. Les comparaisons de composition
restent descriptives, pas une correction générale des effets du calendrier.

## Requête MongoDB exacte et rôle de chaque opérateur

ActivityRepository vérifie les zones et lit les imports complete. JourneyRepository
exécute ensuite un pipeline de deux étapes, envoyé via MongoTemplate.

### `$match` : sélectionner la paire, les fichiers et les deux périodes

```javascript
{ $match: {
  "data.PULocationID": 132,
  "data.DOLocationID": 161,
  "source.file_id": { $in: [ /* SHA-256 complete */ ] },
  $or: [
    { "data.tpep_pickup_datetime": {
      $gte: "2024-02-01T00:00:00", $lt: "2024-03-01T00:00:00"
    } },
    { "data.tpep_pickup_datetime": {
      $gte: "2024-01-01T00:00:00", $lt: "2024-02-01T00:00:00"
    } }
  ]
} }
```

Les clés au même niveau signifient ET. `$or` accepte l'une des deux périodes,
`$in` un fichier de la liste, `$gte` inclut le début, `$lt` exclut la fin.
Les deux zones sont des égalités : c'est un trajet 132 -> 161, pas un trajet qui
touche l'une ou l'autre zone. Les chaînes ISO locales sont comparables dans le
format écrit par l'ingestion.

### `$project` : transmettre seulement les champs nécessaires

Il retire `_id` de la réponse intermédiaire (`_id:0`) et conserve durée, distance,
source et flags. `$ifNull` remplace un tableau de flags manquant par un tableau vide.
`$cond` choisit current ou reference en comparant la date de départ au début de
la période courante ; le match et l'ordre des périodes garantissent ce classement.

`$dateFromString` puis `$hour` et `$isoDayOfWeek` extraient heure et jour pour les
strates. Comme F1, l'interprétation sans décalage préserve les chiffres locaux ;
elle n'est pas utilisée pour calculer la durée. La valeur physique reste duration_s.

### Curseur et calcul exact en Java

`aggregateStream` ouvre un curseur, c'est-à-dire une lecture progressive des
résultats MongoDB. Les lots sont de 2 000 documents projetés. Le try-with-resources
ferme le curseur en succès ou en erreur. L'agrégation a une limite serveur de 120 s.

F4 ne fait pas de `$group` sur les trajets : pour calculer des quantiles exacts,
Java conserve les valeurs de la paire sélectionnée et les trie. Un `$group` avec
un énorme `$push` pourrait dépasser la limite BSON de 16 Mo ; un `$percentile`
approximatif ne donnerait pas les mêmes garanties de quantiles exacts. Ce choix
simple a un coût réseau/mémoire proportionnel aux lignes de la paire, contrairement
aux seuls comptes agrégés de F1–F3. Il est borné à 200 000 candidats au total.
Les valeurs sont conservées pour les statistiques globales et les strates : le
curseur seul ne rend donc pas l'utilisation mémoire constante.

Aucune ligne brute n'est renvoyée au client. Les DTO renvoient les statistiques
et preuves par source. La pagination n'est pas utilisée, car calculer des quantiles
sur une page ne décrirait pas toute la sélection.

## Index mesurés

F4 peut réutiliser les index F1, puis un index spécifique :

```javascript
{ "data.PULocationID": 1, "data.DOLocationID": 1,
  "data.tpep_pickup_datetime": 1 }
```

Les deux égalités viennent avant l'intervalle. MongoDB peut chercher directement
la paire puis la plage de dates. Avec l'index F1 départ, il trouve la zone/date,
mais doit encore examiner les documents de cette origine pour tester l'arrivée.
L'index F4 ne couvre pas les flags et métriques : FETCH reste nécessaire.

Les mesures comparent _id_ seul, les deux index F1, puis F1 + F4. L'API ne force
pas le plan par hint. `urbanflow/deploy.py` crée cet index avec les autres, et
MongoDB le maintient ensuite aux écritures, avec un coût disque et d'ingestion.

## Vérification et reproduction

Les mesures portent sur janvier complet, dans une base dédiée. Les
périodes mesurées sont [1er,15 janvier[ et [15 janvier,1er février[ ; les deux paires
sont 132 -> 161 et 161 -> 236. Un échauffement, trois répétitions par phase,
caches actifs ; réponses comparées strictement. Les plans explain sont exportés
du constructeur du pipeline Java réel par ExportJourneyPipeline.java.

Sur une base dédiée urbanflow_f4_benchmark contenant janvier complet et seulement
_id_, après compilation du jar et lancement de l'API avec PORT=8084 :

```bash
python scripts/benchmark-f4.py --database urbanflow_f4_benchmark
python scripts/verify-f4-parquet.py --api http://127.0.0.1:8084
python scripts/verify-f4-dst.py
```

Le benchmark refuse une référence déjà indexée : aucune suppression automatique
d'index sur une base existante. Il crée les index dans la base dédiée. La
vérification Parquet recalcule qualité, durées UTC, statistiques et standardisation
sans lire MongoDB. La vérification DST utilise une base temporaire et un serveur
API isolé, avec de vraies lignes de mars ; elle supprime cette base après contrôle.
Un import complete de sous-ensemble y est simulé uniquement pour exercer le
service : il ne prouve pas la couverture de mars ni la conformité F6 des extraits.

Voir [les mesures, exemples et limites](../results/performance/f4/synthese.md).
