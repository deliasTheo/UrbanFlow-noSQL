# F3 — Activité inhabituelle : utilisation et explication MongoDB

Ce guide et les mesures sont des supports au rapport final unique.

## Appels et entrées

Après mise à jour et redémarrage du backend Spring, essayer dans Postman :

```text
http://localhost:8080/api/unusual-activity?zoneIds=132&direction=pickup&from=2024-03-01&to=2024-04-01&referenceFrom=2024-01-01&referenceTo=2024-03-01
http://localhost:8080/api/unusual-activity?borough=Brooklyn&direction=dropoff&from=2024-03-01&to=2024-04-01&referenceFrom=2024-01-01&referenceTo=2024-03-01&startHour=8&endHour=12
```

ZoneIds peut contenir plusieurs identifiants séparés par des virgules. Choisir
zoneIds OU borough. Le service examine **chaque zone séparément**, et non la somme
du borough : cela permet de repérer où se produit une variation. Le classement
`unusual` réunit les cellules zone/date signalées.

Les quatre bornes sont des dates locales ; les fins sont exclues. La référence
est explicite et entièrement antérieure à la période étudiée, sans chevauchement.
Le calendrier embarqué couvre 2024 : les autres années sont refusées (400), plutôt
que traitées avec un calendrier férié incomplet. Une cellule est une zone, un jour
et le créneau [startHour,endHour[, identique tous les jours ; défaut 0..24.
Les créneaux traversant minuit ne sont pas acceptés ; faire deux requêtes.

Pickup utilise zone et date de départ, dropoff zone et date d'arrivée, comme F1.
Seuls les imports complete contribuent et le profil activity exclut
NEGATIVE_AMOUNT et EXACT_DUPLICATE. Aucune nouvelle collection, aucun nouveau flag
et aucun index dédié F3 ne sont créés par l'API.

| Paramètre | Défaut | Rôle |
|---|---:|---|
| minReferenceDays | 3 | Minimum de jours comparables, au moins 3 |
| minBaseline | 20 | Médiane de référence minimale |
| minAbsoluteChange | 20 | Écart minimal en nombre de lignes retenues |
| minRelativeChange | 0.5 | Écart relatif minimal (0,5 = 50 %) |
| minRobustScore | 3 | Seuil sur le score descriptif médiane/MAD |

Les seuils sont positifs, visibles et modifiables dans l'URL. Il s'agit de choix
exploratoires, pas de prescriptions du sujet ni de tests de significativité.
Une zone inconnue donne 404, les entrées invalides 400, une base inaccessible,
une agrégation interrompue ou l'absence d'import complet 503. Chaque agrégation
est limitée à 120 s ; les deux requêtes sont successives, pas une limite de 120 s
pour le GET entier. Aucune réponse partielle n'est présentée comme complète.

## Choisir des jours réellement comparables

Pour un mardi de mars à 8..12 h, les références sont les mardis de la période
antérieure sur le même créneau, dans la même zone et avec le même profil.
Chaque référence admissible est affichée avec ses comptes et fichiers sources.
Un zéro local est inclus si les contrôles de couverture passent : supprimer ces
zéros gonflerait artificiellement la référence.

Les jours fériés fédéraux observés en 2024 sont transcrits du calendrier officiel
OPM, dont l'URL figure dans Calendar2024.java et dans la réponse. Ils sont exclus
des références et de la détection ordinaire ; leurs comptes restent accessibles
quand ils sont dans la période cible. Ils ne sont donc pas comparés à un lundi
ordinaire avec une simple étiquette ajoutée après coup. Ce calendrier n'inclut
pas toutes les fêtes locales, vacances scolaires, événements ni perturbations
météorologiques. L'exclusion ne mesure pas l'effet causal d'un jour férié.

Pour le changement d'heure, Java mesure la durée entre deux minuits locaux avec
America/New_York. Une journée différente de 24 h est exclue intégralement :
10 mars et 3 novembre 2024, y compris si le créneau ne traverse pas 2 h.
Cela suit le choix du projet et ne repose pas sur DST_SPANNING, qui ne signale
que les trajets traversant la transition. Aucun flag supplémentaire n'est stocké.

Avant comparaison, une date nécessite un import complet pour son mois source et
au moins une ligne brute au niveau de la ville sur le créneau. Sinon, son statut
est SOURCE_MONTH_MISSING ou NO_CITY_RECORDS : on n'interprète pas son zéro comme
une activité normale ni comme une baisse inhabituelle. Ce sont des contrôles
conservateurs : les mois de fichiers ne décrivent pas parfaitement leurs dates
réelles, et un volume ville non nul ne garantit pas chaque heure/zone complète.

## Critère de variation et minimum de preuve

Sur les comptes retenus des jours comparables :

```text
m = médiane des effectifs de référence
MAD = médiane des |effectif de référence - m|
delta = effectif observé - m
variation relative = delta / m
score robuste descriptif = delta / (1,4826 × MAD)
```

La médiane résiste mieux qu'une moyenne à quelques références extrêmes. MAD décrit
leur dispersion. Le facteur 1,4826 est une convention d'échelle ; il ne prouve pas
que les comptes suivent une loi normale. Avec seulement trois références,
l'estimation reste fragile ; les jours et seuils sont exposés pour le montrer.

Le statut est INSUFFICIENT_REFERENCE si moins de minReferenceDays sont admissibles,
puis LOW_BASELINE si m < minBaseline. Sinon, UNUSUAL exige **les trois** conditions :
écart absolu minimal, écart relatif minimal et score robuste minimal.
Lorsque MAD=0, on n'invente pas un score infini : robustScore=null et
ZERO_REFERENCE_MAD est signalé ; les critères absolu et relatif suffisent alors.
Ce comportement est explicitement différent d'un test de significativité.

Exemple **illustratif**, non présenté comme résultat TLC : m=100, MAD=10,
observé=180 donne +80 %, delta=80 et un score d'environ 5,4 ; les seuils par défaut
sont franchis. Une médiane de 2 avec une hausse de 100 % reste LOW_BASELINE.

Les cellules comparables sans dépassement sont USUAL ; les autres portent leur
motif d'exclusion. Les anomalies sont HIGHER ou LOWER, classées par variation
relative absolue décroissante, puis zone et date pour départager les ex aequo.
Toutes les observations restent dans `observations`, indépendamment du classement.

## Couverture et qualité : expliquer sans attribuer une cause

Un second pipeline compte la ville entière, jour par jour, sur le même créneau.
`cityCoverage` expose les comptes bruts, retenus, exclus et sources. `cityRatio`
compare le volume brut ville de la date à la médiane ville des mêmes références.
CITY_VOLUME_SHIFT avertit si le ratio est inférieur à 0,5 ou supérieur à 2.
HIGH_EXCLUSION_RATE avertit si plus de 20 % des candidats locaux sont exclus.
Ces seuils sont des diagnostics descriptifs fixes, pas des critères de détection.

Une anomalie accompagnée d'une forte baisse générale peut être liée à un contexte
collectif ou à une lacune de couverture ; le système ne prétend pas trancher.
Les comptes avant/après qualité permettent aussi d'examiner des données irrégulières.
La couverture locale ne peut pas être prouvée par les seuls trajets observés.

Pour dropoff, PREVIOUS_SOURCE_MONTH_ABSENT prévient lorsque le fichier du mois
précédent est absent, car certaines arrivées peuvent provenir de ses départs.
Ce diagnostic conservateur peut concerner tout un mois ; il ne garantit pas non
plus la couverture lorsque le mois précédent est présent. Les fichiers sont tous
consultés selon les dates réelles, et ne sont pas restreints à leurs mois annoncés.
Convention conservée : pas d'import concurrent ; les deux lectures ne constituent
pas un instantané transactionnel commun.

## Les requêtes MongoDB, étape par étape

Comme F1/F2, ActivityRepository lit zones et imports pour résoudre les paramètres.
UnusualRepository utilise ensuite deux fois le même constructeur de pipeline :
une fois pour les zones sélectionnées et une fois pour la ville.

### 1. `$match` : sélectionner fichiers et dates, puis les zones

```javascript
{ $match: {
  "source.file_id": { $in: [ /* SHA-256 complets */ ] },
  "data.PULocationID": { $in: [132] },
  $or: [
    { "data.tpep_pickup_datetime": {
      $gte: "2024-03-01T00:00:00", $lt: "2024-04-01T00:00:00"
    } },
    { "data.tpep_pickup_datetime": {
      $gte: "2024-01-01T00:00:00", $lt: "2024-03-01T00:00:00"
    } }
  ]
} }
```

`$match` est un filtre ; les clés au même niveau se combinent par ET.
`$in` signifie appartenir à la liste ; `$or` accepte la période cible OU la
référence. `$gte` inclut la borne de début et `$lt` exclut la fin. Dans le pipeline
ville, le filtre de zone est absent ; dans dropoff, les champs départ deviennent
les champs arrivée. Les dates restent des chaînes ISO locales, comparées dans
le format produit par l'ingestion.

### 2. `$project` : conserver/calculer les champs utiles

`$project` prépare zone, date, heure, source et retained sans écrire en base.
`$substrBytes` extrait AAAA-MM-JJ. `$dateFromString` puis `$hour` extrait les
chiffres de l'heure locale sans les déplacer : comme F1, l'interprétation UTC
intermédiaire sert au calendrier, pas aux durées physiques.

`$ifNull` donne un tableau vide si les flags sont absents. `$setIntersection`
trouve les motifs communs avec le profil activity ; `$size` les compte et
`$eq` vérifie que le nombre vaut zéro. Le booléen retained empêche de compter
plusieurs fois une exclusion cumulant plusieurs flags.

Pour la ville, `$literal: 0` crée une clé de groupe constante. Dans un project,
écrire simplement `zone: 0` signifierait supprimer le champ, pas lui attribuer
zéro : `$literal` évite cette ambiguïté.

### 3. Second `$match` : sélectionner les heures

L'heure calculée doit satisfaire `$gte: startHour` et `$lt: endHour`.
On conserve le même créneau chaque jour, avec une fin exclue. Ce filtre suit
le project car le champ hour n'existe pas dans les documents stockés.

### 4. `$group` : compter par zone, date et fichier

```javascript
{ $group: {
  _id: { zone: "$zone", date: "$date", source: "$source" },
  raw: { $sum: 1 },
  retained: { $sum: { $cond: ["$retained", 1, 0] } }
} }
```

`_id` désigne la clé du groupe de résultat, pas l'identité d'un trajet.
`$sum: 1` compte les lignes brutes ; `$cond` vaut 1 pour une ligne retenue,
0 sinon. Les comptes exclus sont raw-retained. Les fichiers restent dans la
clé pour conserver la traçabilité de chaque date et de chaque référence.

MongoDB effectue les scans et comptages sur les trajets. Java reçoit les groupes,
ajoute les zéros justifiés, exclut les dates calendaires, choisit les références
et calcule médianes/MAD. Ces calculs sur de petits groupes sont plus explicites
à lire en Java que dans un très gros pipeline statistique.

### Index et coût de la requête globale

Le pipeline par zone réutilise l'index F1 zone/date correspondant au sens. Le
pipeline ville n'a pas de filtre zone : les index dont le premier champ est une
zone ne fournissent pas un accès temporel aussi sélectif. Il peut donc continuer
à parcourir la collection. Accélérer le pipeline local ne garantit pas un gros
gain du GET entier : le benchmark inclut les deux calculs et archive leurs plans
séparément. Aucun index supplémentaire n'est ajouté sans mesure.

## Tests, mesures et reproduction

`results/performance/f3/` conserve les requêtes, réponses, plans explain,
répétitions et synthèse. Les mesures cloud utilisent janvier complet dans une
base dédiée, pas des données fabriquées ni les trois mois PC. Le calendrier DST
est contrôlé séparément ; aucune anomalie réelle de mars n'est validée par un
jeu limité à janvier.

Le benchmark exige une base urbanflow_f3_benchmark... contenant janvier complet
et uniquement _id_ sur trips ; il ne supprime pas les index d'une base existante.
Lancer l'API avec cette base, PORT=8083, après avoir compilé le backend courant :

```bash
python scripts/benchmark-f3.py --database urbanflow_f3_benchmark
python scripts/verify-f3-parquet.py --api http://127.0.0.1:8083
```

Il fait un échauffement puis trois mesures par requête sans index, crée les deux
index F1 et répète avec index. Les caches restent actifs. Toutes les réponses
JSON sont comparées strictement. ExportUnusualPipelines.java réutilise les deux
pipelines de production pour explain ; un JDK 21 est nécessaire.

La vérification indépendante relit le Parquet et recalcule directement les flags
activity, comptes quotidiens, références, médianes, MAD, statuts et directions,
sans lire MongoDB. Les exclusions de journées DST, jours fériés, mois absents et
paramètres invalides sont aussi contrôlées. Les exemples réels et les limites
statistiques restent à reprendre dans le rapport final, avec les expériences du collègue.

Le contrôle calendaire isolé est reproductible avec :

```bash
java --class-path backend/target/classes scripts/VerifyCalendar2024.java
```

Les résultats réels, exemples et limites sont dans
[la synthèse F3](../results/performance/f3/synthese.md).
