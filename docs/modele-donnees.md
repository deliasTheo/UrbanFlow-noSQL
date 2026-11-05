# Modèle de données UrbanFlow

Document de conception — 5 novembre 2026. Le modèle ci-dessous est proposé
pour la première ingestion. Le script `urbanflow.ingest` importe directement les documents dans MongoDB. Les règles qualité
existantes restent définies dans `urbanflow/quality.py`.

## Objectif et périmètre

Conserver les enregistrements TLC détaillés de toute la ville, permettre les
services F1 à F6 et retrouver les sources de chaque résultat. Brooklyn est le
focus des exemples, pas un filtre à l'import. Le jeu initial couvre les fichiers
janvier à mars 2024 ; avril reste réservé à F6. Mai et juin complètent les six
mois nécessaires aux expériences.

MongoDB est le serveur de données retenu pour commencer. Docker Compose doit
permettre de reproduire le déploiement local puis les déploiements distribués,
avec un volume persistant propre à chaque instance.

## Collections proposées

### `trips` : un document par ligne source

| Champ / groupe | Contenu et raison |
|---|---|
| `_id` | Identifiant déterministe dérivé du SHA-256 du fichier et du numéro de ligne en base 0. Empêche le réimport de la même ligne. |
| `source.file_id`, `source.row_number` | Référence au fichier importé et position dans le Parquet original. Permet de retrouver une preuve. |
| `data` | Tous les champs bruts TLC, avec leurs noms d'origine : fournisseur, dates locales, zones, distance, passagers, tarifs, suppléments, paiement, etc. |
| `duration_s` | Durée calculée via UTC, en secondes ; `null` si les dates sont absentes ou non convertibles sûrement. |
| `quality_flags` | Liste des codes d'anomalie présents. Les lignes restent stockées. |

La date, l’heure et le jour de semaine locaux sont calculés au moment des
requêtes ; ils ne sont pas stockés dans des champs supplémentaires.

Les dates locales sources sont conservées dans `data` sous forme de chaînes ISO
sans décalage. Leur précision d'origine doit être préservée. Une date BSON a une
précision à la milliseconde : ne pas en faire la seule copie d'une source plus
précise. Les valeurs manquantes deviennent `null`, sans les convertir en zéro.
Les identifiants de zone sont des entiers. Les distances restent en miles et les
durées en secondes ; les conversions d'affichage doivent être explicites.
Les montants sont conservés en nombres flottants, comme dans les fichiers
actuels, sans arrondi à l’import. La détection des annulations compare les
valeurs absolues arrondies au centime, conformément au module qualité existant.

### `zones` : référentiel géographique

Un document par `LocationID`, utilisé comme `_id`, avec `Borough`, `Zone`,
`service_zone` et la référence du fichier source. Les noms ne sont pas uniques :
les jointures et paramètres utilisent les identifiants. Les codes 264/265,
les valeurs absentes et les codes hors référentiel doivent être distingués.
Le référentiel peut être répliqué sur chaque instance distribuée.

### `imports` : provenance et suivi

Un document par contenu de fichier, identifié par son SHA-256 : noms connus,
URL, date de récupération, taille, mois annoncé, nombre de lignes attendu,
dates de début/fin d'import, compteurs et état
(`loading`, `complete`, `failed`). Un même contenu renommé garde la même identité.
Le manifeste existant est la source initiale de ces métadonnées.

Les requêtes analytiques ne doivent utiliser que les imports terminés. Une
requête fige la liste des imports visibles à son démarrage pour éviter un
résultat mélangeant deux états de l'archive pendant F6.

Une collection technique `ingestion_lock` empêche deux imports simultanés dans
la même base. Le guide explique comment retirer un verrou après un arrêt brutal.

## Temps : dates locales conservées, UTC temporaire

La documentation TLC décrit des heures locales de New York sans fuseau.
On attribue `America/New_York`, puis on convertit en UTC :

| 10 mars 2024 | Heure locale | Instant UTC |
|---|---|---|
| Départ | 01:30 | 06:30Z |
| Arrivée | 03:30 | 07:30Z |

Durée réelle stockée : une heure. Les dates UTC et la différence locale ne sont
pas stockées dans les documents MongoDB. Le code existant
signale `DST_SPANNING`. Une heure inexistante en mars ou ambiguë en novembre
produit `DST_UNRESOLVED`. Le rapport historique conserve une durée locale de secours ; le script de
préparation la remplace par `null` pour le stockage. Le profil `journey` exclut
ces lignes. Les dates manquantes doivent aussi être traitées explicitement
avant l'import ; elles ne sont pas nécessairement des anomalies DST.

Les analyses horaires, jours de semaine et jours fériés utilisent New York.
Les durées utilisent UTC. Les intervalles sont semi-ouverts `[début, fin)` pour
éviter les doubles comptages entre périodes adjacentes. Les entrées de l'API/CLI
doivent préciser leur convention de fuseau et refuser une borne ambiguë sans
choix explicite. Un trajet est affecté à la période de sa prise en charge
locale, quel que soit son fichier ; F1 à l'arrivée filtre la date d'arrivée.

## Qualité et identité : deux problèmes distincts

Aucune suppression à l'ingestion. Les profils existants sont appliqués aux
requêtes : `activity` pour F1/F3, `flows` pour F2/F5, `journey` pour F4.
Chaque résultat expose le nombre de lignes candidates, retenues et exclues ;
une ligne ayant plusieurs anomalies ne doit pas être comptée plusieurs fois
dans le total des exclusions. Les règles et seuils doivent être versionnés.

L'identité fichier + ligne préserve deux lignes sources identiques tout en
empêchant de réimporter la même ligne. Un hash du seul contenu de la ligne
ne suffit pas : deux enregistrements identiques peuvent correspondre à deux
trajets distincts. L'identité d'un enregistrement source n'est pas une preuve
de l'identité d'un déplacement physique.

Le code actuel signale les doublons exacts à l'intérieur d'un fichier et exclut
les copies des analyses. Il repère aussi les paires original/annulation dans un
fichier ; l'original positif est conservé pour les comptages. Ce sont des choix
d'analyse à expliquer, distincts de l'idempotence de F6.

**À résoudre avant F6 sur des extraits :** fichier modifié, extrait chevauchant
un fichier existant ou annulations réparties entre fichiers. L'identité fichier
+ ligne ne résout pas ces cas. Sans provenance permettant de reconnaître les
lignes originales, une déduplication certaine est impossible. L'import doit
signaler le cas et appliquer une politique documentée ; ne pas promettre une
déduplication universelle. L'état qualité doit rester identique quelle que soit
la taille des lots : doublons et paires d'annulation peuvent traverser deux lots.

## Conséquences des six services

| Service | Besoins à anticiper |
|---|---|
| F1 — activité | Filtrer départ ou arrivée, zone et intervalle ; grouper en heure locale par heure/jour ; exposer effectifs et exclusions. |
| F2 — flux | Résoudre borough/ensemble de zones à l'exécution ; compter les paires et les directions opposées ; conserver une série temporelle et un minimum d'effectif. |
| F3 — activité inhabituelle | Définir périodes de référence, fenêtres, seuils et jours fériés ; distinguer activité faible et couverture incomplète. Un calendrier férié sourcé sera nécessaire. |
| F4 — caractéristiques | Accéder aux durées et distances détaillées pour médianes, quantiles, dispersion et tailles d'échantillon ; comparer des groupes comparables. |
| F5 — changements de flux | Compter chaque paire, les totaux servant de dénominateurs et les variations par semaine ; expliciter le périmètre du dénominateur et départager les ex æquo. |
| F6 — mise à jour | Import par lots, reprise après interruption, identités stables, publication des seuls imports complets et absence de doublons lors d'une relance. |

La couverture temporelle doit être dérivée des fichiers complets attendus et de
leurs dates effectives, pas seulement du premier et du dernier trajet observés.
L'absence de ligne sur un créneau ne suffit pas à prouver un défaut de couverture.
Chaque service conserve ses paramètres, ses versions de règles et les imports
utilisés, et permet de compter/lister les lignes justificatives avec provenance.

## Index et agrégats : propositions à mesurer

Premiers index candidats : `data.PULocationID` + `data.tpep_pickup_datetime`,
`data.DOLocationID` + `data.tpep_dropoff_datetime`, puis paire origine/destination
+ date locale de départ si les mesures le justifient. Les dates locales ISO
uniformes permettent des filtres chronologiques ; les extractions calendaires
sont réalisées pendant les requêtes. Aucun champ UTC supplémentaire n'est stocké.

Chaque index augmente le stockage et le coût d'import. Comparer au moins une
alternative sur deux requêtes représentatives et mesurer latence, stockage et
ingestion. Ne pas créer un index pour chaque champ par défaut.

Commencer par les détails. Des agrégats zone/heure ou paire/jour pourront être
ajoutés après mesure, avec compteurs de qualité et traçabilité. Ils devront être
mis à jour par F6 et comparés aux détails. Une médiane globale ne se calcule pas
en moyennant les médianes de plusieurs instances ; garder les données nécessaires
à une fusion correcte, déterministe et identique au déploiement local.

## Préparation de la distribution

Le modèle et les identités restent identiques sur tous les déploiements. La
stratégie de placement reste à choisir : comparer une répartition temporelle à
une répartition par zone de départ, en tenant compte de la forte concentration
des trajets dans certaines zones. Docker ne réalise pas cette répartition.
Choisir séparément sharding MongoDB natif ou routage applicatif.

Prévoir le routage des requêtes, la fusion des résultats, un ordre canonique avec
départage déterministe et l'unicité des imports à l'échelle du déploiement.
En cas de panne, une réponse doit échouer explicitement ou identifier les données
manquantes ; un classement ou une part calculés sur un sous-ensemble ne doivent
jamais être présentés comme complets.

## Validation du premier import

1. Importer les zones puis janvier ; contrôler les lignes contre les métadonnées
   Parquet, les types, la provenance et les compteurs qualité.
2. Relancer le même fichier, puis reprendre un import interrompu : contenu final
   identique, sans doublons ni lignes incomplètes visibles.
3. Comparer les règles qualité sur le fichier entier et sur plusieurs tailles de
   lots, particulièrement les doublons et annulations.
4. Ajouter février et mars ; vérifier les cas réels de changement d'heure contre
   les sources. Garder avril pour le test F6.
5. Vérifier ensuite les mêmes résultats local/distribué, y compris les requêtes
   couvrant plusieurs instances ; vérifier deux résultats analytiques avec des
   scripts indépendants lisant directement les Parquet, comme demandé au sujet.
