# F5 — Changements de parts des flux

Ce guide et les mesures sont des supports au rapport final unique.
F5 est exposé par Spring Boot dans la même API que F1–F4.

## Appels Postman

Exemple utilisable sur janvier complet, notamment pour reproduire les mesures :

```text
http://localhost:8080/api/flow-changes?zoneIds=132&from=2024-01-22&to=2024-01-29&referenceFrom=2024-01-15&referenceTo=2024-01-22&baselineFrom=2024-01-01&baselineTo=2024-01-22
```

Sur le périmètre janvier–mars, pour un historique plus fourni :

```text
http://localhost:8080/api/flow-changes?borough=Brooklyn&from=2024-02-26&to=2024-03-04&referenceFrom=2024-02-19&referenceTo=2024-02-26&baselineFrom=2024-01-01&baselineTo=2024-02-26
```

Le second exemple est un choix de paramètres, pas un résultat déjà mesuré dans
le benchmark limité à janvier. Les semaines avec jours fériés sont signalées.

Choisir zoneIds (liste séparée par virgules), borough, ou aucun des deux pour
l'ensemble des zones du référentiel. Le dénominateur est **tous les départs
retenus de cette aire**, vers toutes les destinations, y compris internes.
Il reste identique dans sa définition pour référence, courant et baseline.
Sans filtre, les origines sont les identifiants du référentiel, pas des codes
invalides absents de zones. Les exclusions du profil flows restent celles de F2 :
NEGATIVE_AMOUNT, EXACT_DUPLICATE et UNKNOWN_ZONE (264/265 dans le catalogue actuel).

Les périodes sont définies par les départs locaux de New York. Bornes de fin
exclues, lundi à lundi, dates de 2024. Les périodes référence et courante doivent
avoir la même durée en semaines complètes, sans chevauchement. Baseline est une
période historique finissant avant ou au début du courant ; elle peut inclure
la référence, ce qui est déclaré, mais pas le courant. On n'utilise pas les
variations du courant pour fabriquer son propre seuil de référence.

Un mois civil quelconque n'est pas automatiquement une période comparable :
le service refuse des bornes non alignées plutôt que de rogner silencieusement
les jours. Il accepte une ou plusieurs semaines par période comparée.

## Paramètres de sélection et de preuve

| Paramètre | Défaut | Rôle |
|---|---:|---|
| minTrips | 20 | Effectif minimal atteint dans au moins une des deux périodes |
| minBaselineTrips | 20 | Effectif total minimal du flux sur les semaines historiques utilisables |
| minTotalTrips | 100 | Dénominateur hebdomadaire minimal de l'aire |
| minBaselineWeeks | 3 | Minimum de semaines historiques utilisables, au moins 3 |
| minShareChange | 0.001 | Plancher de variation absolue de part, soit 0,1 point |
| minVariationRatio | 2 | Ratio minimal face à la variation habituelle/plancher, au moins 1 |
| limit | 10 | Nombre maximal par liste, de 1 à 100 |

Ces règles sont exploratoires et modifiables. Ce ne sont ni des tests de
significativité, ni des seuils imposés par le sujet. Une disparition peut être
évaluée sans exiger un effectif courant positif : minTrips porte sur le maximum
des deux comptes. Un flux nouvellement observé sans historique probant est
signalé LOW_BASELINE_COUNTS plutôt que déclaré changement majeur.

## Calcul des parts et séparation de l'effet volume

Pour une paire origine–destination :

```text
nA, nB = comptes retenus du flux dans les deux périodes
NA, NB = tous les départs retenus de l'aire dans les deux périodes
pA = nA / NA ; pB = nB / NB
shareChange = pB - pA
percentagePointChange = 100 × (pB - pA)
relativeShareChange = (pB - pA) / pA, null si pA = 0
```

Les parts sont des fractions : 0,02 vaut 2 %, un écart de 0,01 vaut un point de
pourcentage. Ce n'est pas une hausse relative de 1 %. Les dénominateurs restent
les totaux de toute l'aire retenue, jamais seulement les flux du top affiché.

La décomposition des comptes est :

```text
expectedCurrentAtReferenceShare = pA × NB
volumeOnlyCountChange = expectedCurrentAtReferenceShare - nA
residualCountChange = nB - expectedCurrentAtReferenceShare
nB - nA = volumeOnlyCountChange + residualCountChange
```

L'effectif attendu est théorique et peut être fractionnaire ; aucun trajet n'est
créé. Il répond à « combien si le flux avait seulement suivi le volume global ? ».
Exemple **illustratif** : si le total double et le flux double aussi, sa part ne
change pas. Son augmentation de compte ne suffit pas à entrer dans le classement.

Si un dénominateur est nul, les parts/écarts non définis sont null ; la période
n'est pas présentée comme comparable. Les totaux raw/retained/excluded et les
comptes par fichier sont exposés pour chaque période et chaque semaine.

## Comparer au bruit hebdomadaire propre à chaque flux

Pour chaque semaine historique utilisable : `p_w = n_w / N_w`.
Un flux absent une semaine reçoit un compte zéro si la semaine de l'aire est
utilisable ; on ne supprime pas ces zéros, car ils font partie de sa régularité.

Pour chaque paire de semaines consécutives du calendrier, le service calcule
`d_w = p_w - p_(w-1)`. Il ne relie pas artificiellement les semaines séparées par
une lacune. Il faut au moins minBaselineWeeks semaines et minBaselineWeeks-1
différences adjacentes. Une histoire avec lacunes peut rester exploitable si ces
conditions sont remplies ; les semaines et statuts restent visibles.

`typicalWeeklyChange` est la médiane des |d_w| ; `p90WeeklyChange` leur p90 exact
par interpolation linéaire. Le score descriptif est :

```text
variationRatio = |pB - pA| / max(p90WeeklyChange, minShareChange)
```

Le plancher empêche un ratio infini quand toutes les variations historiques sont
nulles. Un flux n'est CHANGED que si l'effectif, l'historique, le minimum de part
et le ratio passent. Avec les défauts, p90=0 implique un écart d'au moins
2 × 0,001, soit **0,2 point**, à cause du ratio minimal 2. Le plancher n'est donc
pas une promesse de classer tout écart de 0,1 point.

Le p90 est un repère de fluctuations observées, pas une borne probabiliste ni
une p-value. Trois semaines ne donnent que deux différences, une estimation
fragile : un historique plus long est préférable. Les périodes de plusieurs
semaines moyennent la variation ; le seuil hebdomadaire n'est pas converti en
incertitude statistique pour leur moyenne. Le ratio reste descriptif.

## Classement et réponses non concluantes

Les flux CHANGED sont triés par **variation absolue de part décroissante**, puis
identifiants origine/destination croissants pour les ex aequo. `increases` et
`decreases` séparent les deux sens du changement, avec limit résultats chacune.
Le classement ne privilégie pas un petit pourcentage passant de 1 à 2 trajets.

Les plus grands écarts non qualifiés restent dans `otherLargestChanges` avec leur
statut : LOW_COUNTS, LOW_BASELINE_COUNTS, SMALL_SHARE_CHANGE ou
WITHIN_WEEKLY_VARIATION. Ce tableau peut aussi afficher les candidats non
concluants en cas de données incomplètes ; il ne constitue pas un classement de
changements majeurs. Les écarts null ne sont pas classés devant les écarts définis.
`pairsConsidered` compte les paires avec au moins un trajet retenu dans les périodes
comparées ; `qualifiedPairs` compte les CHANGED avant limit.

Le statut global est COMPARABLE, INCOMPLETE_OR_LOW_VOLUME_PERIOD ou
INSUFFICIENT_BASELINE. Les deux derniers empêchent toute entrée dans increases
et decreases. Ils ne sont pas transformés en résultats normaux à zéro.

## Couverture, calendrier et traçabilité

Une semaine n'est utilisable que si tous ses mois sources ont un import complete
et si son total retenu atteint minTotalTrips. Ce contrôle est conservateur : un
fichier peut contenir des dates hors mois, et des totaux suffisants ne prouvent
pas la complétude de chaque jour ou zone. Les imports sont sélectionnés par état,
pas restreints au mois annoncé ; on filtre les trajets sur leurs dates réelles.

Les semaines fériées et DST portent des avertissements via le calendrier 2024 de
F3. Elles ne sont pas supprimées ou neutralisées dans F5 : exclure un jour d'une
semaine casserait l'égalité des périodes. Une semaine de transition n'a pas la
même durée physique, et une fête peut modifier les parts. Ces effets restent à
examiner avant d'interpréter le changement. Le calendrier fédéral ne couvre pas
toutes les particularités locales, la météo ou les événements.

Chaque flux expose ses comptes et sources dans les deux périodes, ainsi que
chaque semaine de baseline, son dénominateur et sa part. Les totaux de période
et de semaine portent aussi leur provenance. Les résultats sont des comptes de
lignes retenues, pas une mesure de demande insatisfaite ni de routes physiques.

## MongoDB : le pipeline exact

ActivityRepository lit zones et imports complete. ChangeRepository construit
un seul pipeline sur trips pour les trois intervalles. Le chevauchement possible
baseline/référence ne duplique pas les trajets : `$or` est un filtre, pas une union
qui copierait chaque résultat satisfaisant deux branches.

### `$match` : sélectionner origine, fichiers et dates

```javascript
{ $match: {
  "data.PULocationID": { $in: [132] },
  "source.file_id": { $in: [ /* SHA-256 des imports complete */ ] },
  $or: [
    { "data.tpep_pickup_datetime": { $gte: "2024-01-22T00:00:00", $lt: "2024-01-29T00:00:00" } },
    { "data.tpep_pickup_datetime": { $gte: "2024-01-15T00:00:00", $lt: "2024-01-22T00:00:00" } },
    { "data.tpep_pickup_datetime": { $gte: "2024-01-01T00:00:00", $lt: "2024-01-22T00:00:00" } }
  ]
} }
```

`$in` signifie appartenir à la liste ; les conditions principales se combinent
par ET. `$gte` inclut le début et `$lt` exclut la fin. Les dates ISO locales sont
comparées selon le format stocké. On ne filtre pas la destination : toutes sont
nécessaires pour calculer le dénominateur et découvrir les paires modifiées.

### `$project` : préparer les groupes sans modifier la base

Il conserve origine, destination, fichier, semaine et retained.
`$dateFromString` interprète la chaîne locale pour les calculs de calendrier ;
`$dateTrunc` avec unit=week et startOfWeek=monday retrouve son lundi ;
`$dateToString` produit AAAA-MM-JJ. Sans déplacement de fuseau, on préserve les
chiffres du calendrier local, comme dans F2. Aucune durée n'est calculée ici.

Pour retained, `$ifNull` remplace les flags absents par un tableau vide,
`$setIntersection` trouve ceux exclus par flows, `$size` les compte et `$eq`
vérifie qu'il n'y en a aucun. Une ligne portant plusieurs flags reste une seule
ligne exclue dans les totaux.

### `$group`, `$sum` et `$cond` : compter dans MongoDB

```javascript
{ $group: {
  _id: { origin: "$origin", destination: "$destination", week: "$week", source: "$source" },
  raw: { $sum: 1 },
  retained: { $sum: { $cond: ["$retained", 1, 0] } }
} }
```

`_id` est la clé du groupe, pas celle d'un trajet. `$sum:1` compte les candidats.
`$cond` vaut 1 si retenu, 0 sinon, pour compter séparément les utilisables.
La source dans la clé conserve la preuve par fichier.

Java reçoit les comptes agrégés, pas les millions de trajets. Il forme les totaux
hebdomadaires et de période, ajoute les zéros historiques justifiés, calcule
parts/p90 et classe. L'ordre des lignes agrégées ne change pas les comptes ; les
semaines et sorties sont ordonnées explicitement pour la reproductibilité.

On n'utilise pas un `$facet` contenant toutes les paires dans un unique document,
pour éviter sa limite BSON de 16 Mo. Le group autorise le disque (allowDiskUse)
et la requête est limitée à 120 secondes. Java conserve tous les groupes pour
calculer les dénominateurs et historiques avant le top : la taille croît avec
les zones, semaines et sources, même si limit est petit.

## Index et mesures

Le filtre principal est origine + date : l'index F1 départ correspond directement.
L'index F4 origine + destination + date peut aussi être considéré par MongoDB,
mais la destination n'est pas fixée ici ; il n'est pas supposé meilleur.
Aucun hint ne force le plan. Aucun nouvel index F5 n'est créé.

Le benchmark compare _id_ seul, index F1 puis F1 + F4, sur deux requêtes et les
mêmes lignes de janvier complet, avec un échauffement et trois répétitions par
phase. Les caches restent actifs, sans garantie de froid. Les JSON sont comparés
strictement et les plans explain proviennent du constructeur Java de production.

Avec une base dédiée urbanflow_f5_benchmark contenant janvier complet et seulement
_id_, le backend compilé lancé sur cette base avec PORT=8086 :

```bash
python scripts/benchmark-f5.py --database urbanflow_f5_benchmark
python scripts/verify-f5-parquet.py --api http://127.0.0.1:8086
```

Le benchmark refuse une base déjà indexée et ne supprime aucun index existant.
La vérification indépendante relit le Parquet, recalcule les exclusions flows,
les parts et variations de **toutes** les paires, puis compare les classements et
preuves renvoyées. Elle couvre une zone, Brooklyn et le périmètre ville, ainsi
que les cas de données/historique insuffisants et les erreurs de paramètres.

Voir [les mesures et exemples réels](../results/performance/f5/synthese.md).
