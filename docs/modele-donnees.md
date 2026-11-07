# Modèle de données UrbanFlow

## Objectif et périmètre

Conserver les enregistrements TLC détaillés de toute la ville, permettre les
services F1 à F6 et retrouver les sources de chaque résultat. Brooklyn est le
focus des exemples, pas un filtre à l'import. Le jeu initial couvre les fichiers
janvier à mars 2024 ; avril est réservé à F6. Mai et juin complètent les six
mois nécessaires aux expériences.

MongoDB est le serveur de données. Docker Compose reproduit le déploiement local
et les déploiements répartis, avec un volume persistant propre à chaque instance.

## Collections

### `trips` : un document par ligne source

| Champ / groupe | Contenu et raison |
|---|---|
| `_id` | Identité du trajet : heure de départ, empreinte de toutes les colonnes et rang parmi les lignes identiques du fichier. Empêche d'importer deux fois la même ligne. |
| `source.file_id`, `source.row_number` | Fichier importé et position de la ligne dans ce fichier. Permet de retrouver une preuve. |
| `data` | Tous les champs bruts TLC, avec leurs noms d'origine : fournisseur, dates locales, zones, distance, passagers, tarifs, suppléments, paiement, etc. |
| `duration_s` | Durée calculée via UTC, en secondes ; `null` si elle n'est pas déterminable. |
| `quality_flags` | Liste des codes d'anomalie présents. Les lignes restent stockées. |

La date, l'heure et le jour de semaine locaux sont calculés au moment des
requêtes ; ils ne sont pas stockés dans des champs supplémentaires.

Les dates locales sources sont conservées dans `data` sous forme de chaînes ISO
sans décalage. Une date BSON ferait croire à un instant UTC, alors que la source
donne une heure locale. Les valeurs manquantes deviennent `null`, sans être
converties en zéro. Les identifiants de zone sont des entiers, les distances
restent en miles et les durées en secondes. Les montants sont conservés en nombres
flottants, sans arrondi à l'import. La détection des annulations compare les
valeurs absolues arrondies au centime.

### `zones` : référentiel géographique

Un document par `LocationID`, utilisé comme `_id`, avec `Borough`, `Zone`,
`service_zone` et la référence du fichier source. Les noms ne sont pas uniques :
les jointures et les paramètres utilisent les identifiants. Sur le cluster, cette
collection reste sur le premier shard.

### `imports` : provenance et suivi

Un document par contenu de fichier, identifié par son SHA-256 : nom, URL, date de
récupération, taille, mois annoncé, nombre de lignes attendu, dates de début et de
fin d'import, résumé et état (`loading`, `complete`, `failed`). Un même contenu
renommé garde la même identité. Le manifeste est la source de ces métadonnées pour
les mois téléchargés.

Les services ne lisent que les trajets des imports `complete`. La liste est lue au
début de chaque requête : il ne faut pas importer pendant une analyse, car l'API
n'offre pas d'instantané transactionnel.

## Temps : dates locales conservées, UTC temporaire

La documentation TLC décrit des heures locales de New York sans fuseau.
On attribue `America/New_York`, puis on convertit en UTC :

| 10 mars 2024 | Heure locale | Instant UTC |
|---|---|---|
| Départ | 01:30 | 06:30Z |
| Arrivée | 03:30 | 07:30Z |

Durée réelle stockée : une heure. Les dates UTC et la différence locale ne sont
pas stockées. Un trajet à cheval sur le changement d'heure porte `DST_SPANNING`.
Une heure inexistante en mars ou ambiguë en novembre produit `DST_UNRESOLVED` et
une durée `null` ; le profil `journey` exclut ces lignes.

Les analyses horaires, les jours de semaine et les jours fériés utilisent New York.
Les durées utilisent UTC. Les intervalles sont semi-ouverts `[début, fin[` pour
éviter les doubles comptages entre périodes adjacentes. Les bornes de l'API sont
des dates locales. Un trajet est affecté à la période de sa prise en charge locale,
quel que soit son fichier ; F1 et F3 en mode arrivées filtrent la date d'arrivée.

## Qualité

Aucune suppression à l'ingestion. Les profils sont appliqués aux requêtes :
`activity` pour F1 et F3, `flows` pour F2 et F5, `journey` pour F4. Chaque résultat
expose le nombre de lignes candidates, retenues et exclues ; une ligne ayant
plusieurs anomalies n'est comptée qu'une fois dans le total des exclusions. Les
règles et les seuils sont dans `urbanflow/quality.py`.

Les doublons exacts sont cherchés à l'intérieur d'un fichier, et seules les copies
sont exclues. Les paires original/annulation sont aussi repérées dans un fichier ;
l'original positif reste compté. Le mois entier est analysé avant l'écriture : le
résultat ne dépend donc pas de la taille des lots.

## Identité d'un trajet

La source n'a pas d'identifiant. On construit donc celui-ci :

```text
heure de départ | empreinte de toutes les colonnes : rang
```

Le rang compte les lignes identiques à l'intérieur du fichier. On obtient les
propriétés demandées à F6 :

| Situation | Résultat |
|---|---|
| Deux lignes identiques dans un fichier | Rangs 0 et 1 : les deux sont gardées. |
| Le même fichier importé deux fois | Reconnu par son SHA-256 : rien ne change. |
| Le même contenu sous un autre nom ou dans un autre ordre | Mêmes identifiants : aucune ligne ajoutée. |
| Un extrait qui recoupe un fichier déjà importé | Seules les lignes nouvelles sont ajoutées. |
| Un import interrompu puis relancé | Les lignes déjà là sont refusées, les manquantes sont ajoutées. |

Les services ne lisent que les imports `complete` : un import partiel reste invisible.

Cette identité a des limites :

- deux lignes identiques dans **deux fichiers différents** portent le même rang 0 et
  comptent pour un seul trajet. Sans identifiant dans la source, rien ne distingue ce
  cas d'une même ligne publiée deux fois ;
- une ligne corrigée par la TLC change d'empreinte : elle s'ajoute à l'ancienne ;
- les doublons et les annulations ne sont repérés qu'à l'intérieur d'un fichier.

L'identité d'un enregistrement source n'est pas une preuve de l'identité d'un
déplacement physique.

Sur le cluster, MongoDB ne garantit l'unicité de `_id` que sur chaque shard, car
`_id` n'est pas la clé de partition. L'identité reste sûre : l'empreinte couvre la
zone et l'heure de départ, donc une même ligne retombe toujours sur le même shard.

## Conséquences des six services

| Service | Accès nécessaires |
|---|---|
| F1 — activité | Filtrer départ ou arrivée, zone et intervalle ; grouper en heure locale par heure et par jour ; exposer effectifs et exclusions. |
| F2 — flux | Résoudre un borough ou un ensemble de zones à l'exécution ; compter les paires et les directions opposées ; garder une série hebdomadaire et un minimum d'effectif. |
| F3 — activité inhabituelle | Comparer chaque zone et chaque jour à des jours de référence, hors jours fériés ; distinguer une activité faible d'une couverture incomplète. |
| F4 — caractéristiques | Lire les durées et distances détaillées pour les quantiles, la dispersion et les tailles d'échantillon ; comparer des groupes comparables. |
| F5 — changements de flux | Compter chaque paire, les totaux servant de dénominateurs et les variations par semaine. |
| F6 — mise à jour | Import par lots, reprise après interruption, identités stables, publication des seuls imports complets. |

La couverture temporelle se déduit des fichiers complets attendus, pas du premier
et du dernier trajet observés. L'absence de ligne sur un créneau ne suffit pas à
prouver un défaut de couverture. Chaque service renvoie ses paramètres, les imports
utilisés et les effectifs par fichier source.

## Index et agrégats

`urbanflow/deploy.py` crée les mêmes index sur tous les déploiements :

| Index | Champs | Rôle |
|---|---|---|
| `f1_pickup_zone_datetime` | zone de départ, date de départ | F1 départs, F2, F3 et F5 par zone ; clé de partition du placement par zone |
| `f1_dropoff_zone_datetime` | zone d'arrivée, date d'arrivée | F1 arrivées, retours de F2, F3 en arrivées |
| `f4_pair_pickup_datetime` | zone de départ, zone d'arrivée, date de départ | F4 sur une paire |
| `pickup_datetime_zone` | date de départ, zone de départ | clé de partition du placement par période, contrôle ville de F3 |

Les trois premiers ont été comparés à une base sans index analytique dans
`results/performance/`. Le quatrième est imposé par le placement par période ; son
effet sur F3 n'a pas de mesure séparée. Chaque index augmente le stockage et le coût
d'import.

Aucun agrégat n'est pré-calculé : les services comptent à partir des détails. Il n'y
a donc rien à maintenir à jour lors de F6.

## Distribution

Le modèle et les identités sont les mêmes sur tous les déploiements. La répartition
utilise le sharding natif de MongoDB, avec des zones de partition fixées avant
l'import et le balancer arrêté, pour que rien ne bouge pendant les mesures. Deux
placements sont comparés :

- **par zone de départ** : chaque zone est entière sur un shard, et les zones sont
  réparties pour équilibrer le nombre de départs de janvier à mars ;
- **par période** : janvier à mars sur le premier shard, à partir d'avril sur le second.

En cas de panne, une requête qui a besoin de l'instance arrêtée échoue explicitement.
Les réponses sont triées avec les identifiants pour départager les ex æquo, ce qui
permet de les comparer entre déploiements.

## Vérifications

- `scripts/verify-f6.py` contrôle l'identité sur de vraies lignes TLC.
- `scripts/verify-f2-parquet.py` à `verify-f5-parquet.py` et
  `verify-registered-period.py` recalculent les résultats depuis les Parquet, sans
  lire MongoDB.
- `scripts/verify-f4-dst.py` contrôle les durées autour du changement d'heure.
- `scripts/compare-deployments.py` compare automatiquement le local et les clusters.
