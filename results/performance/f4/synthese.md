# F4 — Synthèse

## Choix réalisés

API par paire de zones et deux périodes non chevauchantes, affectation selon le
départ local. Profil journey inchangé, comparaison séparée des trajets retenus et
moins fiables ; montants négatifs/doublons restent hors des statistiques.

Quantiles exacts par interpolation linéaire, min/max, moyenne, écart-type de
population, IQR et nombre de valeurs hors bornes IQR sans suppression supplémentaire.
Les durées sont celles stockées à l'ingestion, pas une soustraction naïve locale.
Les effectifs et valeurs absentes accompagnent chaque statistique.

MongoDB filtre la paire/dates/fichiers puis projette les seuls champs utiles.
Le curseur fournit des lots de 2 000 ; Java conserve les valeurs sélectionnées,
les trie et calcule les statistiques. Ce choix évite le quantile approximatif
et les gros tableaux BSON, au prix d'un coût mémoire/réseau O(n). Garde-fou :
200 000 candidats maximum au total ; au-delà, erreur 422 explicite.

La comparaison globale est complétée par des strates jour de semaine/week-end,
créneau de 6 h et classe de distance. Les moyennes de durée sont standardisées
sur les poids de référence des strates suffisamment représentées des deux côtés.
Les fractions d'effectif couvertes sont affichées, pas masquées.

## Protocole et mesures

5 novembre 2026, même serveur distant que les mesures précédentes : MongoDB
8.0.16, Spring Boot 3.5.7, Temurin JDK 21.0.9, cgroup 2 CPU/8 Gio ; API et MongoDB
partagent la machine et le disque. Détail dans environment.json.

Janvier complet, **2 964 624 lignes réelles**, copie isolée dans urbanflow_f4_benchmark
conservant les identifiants et flags de l'import validé ; les copies physiques ne
sont pas comptées comme un volume supplémentaire de trajets.

Deux requêtes : 132 -> 161 (JFK -> Midtown Center) et 161 -> 236
(Midtown Center -> Upper East Side North), du 1er au 15 janvier exclu contre le
15 janvier au 1er février exclu. Paramètres exacts dans measurements.json.

Trois configurations sur les mêmes données : _id_ seul, les deux index F1,
puis F1 + index F4 (origine, destination, date de départ). Pour chacune et par
requête : un échauffement puis trois répétitions HTTP, caches actifs, pas de
mesure à froid garantie. Ordre : airport puis manhattan. Explain exécuté après
les mesures ; vérifications Parquet et DST après la mesure, sans import concurrent.

Médianes HTTP en secondes (répétitions, min/max et écart-type archivés) :

| Requête | Sans index analytique | Index F1 | F1 + index F4 |
|---|---:|---:|---:|
| airport | 2.816 | 0.314 | 0.045 |
| manhattan | 2.515 | 0.433 | 0.186 |

| Requête | Documents examinés sans index | Index F1 | F1 + F4 |
|---|---:|---:|---:|
| 132 -> 161 | 2 964 624 | 111 942 | 2 459 |
| 161 -> 236 | 2 964 624 | 143 469 | 8 766 |

COLLSCAN devient un parcours d'index avec FETCH ; avec l'index F4, les documents
examinés correspondent ici aux candidats de la paire sur les deux périodes.
Les deux égalités avant la date évitent de relire les autres destinations de
l'origine. Les plans complets et pipelines exacts sont archivés.

La construction de l'index F4 a pris environ 7,46 s ; la taille totale des index
passe de 130 519 040 à 187 248 640 octets (+54,1 Mio environ). Le surcoût à l'import
n'a pas été mesuré : les index ont été construits après import. L'index F4 est
retenu pour ces requêtes, vu le gain face aux index F1. `urbanflow/deploy.py` le crée
avec les autres index.

## Exactitude et résultats réels

Toutes les répétitions et les trois configurations renvoient des JSON
strictement identiques ; empreintes SHA-256 archivées.

verify-f4-parquet.py relit le fichier original entier et recalcule directement
les doublons, profils activity/journey et durées UTC, sans lire MongoDB. Les
statistiques sont contrôlées avec NumPy quantile(method="linear"), std(ddof=0),
les effectifs, valeurs absentes, strates et moyennes standardisées sont vérifiés.
La comparaison flottante indépendante utilise une tolérance numérique ; l'égalité
sans/avec index reste stricte. Les erreurs 400/404 et mois manquants sont testés.

Exemples retenus :

- 132 -> 161 : référence 1 070 retenus, médiane 2 678 s et 17,61 miles ;
  courant 1 359 retenus, médiane 2 719 s et 17,57 miles. Écart médian +41 s.
  Six strates communes couvrent 97,94 % / 95,66 % des effectifs ; différence des
  moyennes de durée standardisées +49,76 s.
- 161 -> 236 : 3 424 / 5 239 retenus ; médianes 710,5 / 768 s ; écart +57,5 s.
  Douze strates communes ; différence standardisée +91,75 s. Ce n'est pas
  la différence des médianes et ce n'est pas une preuve de congestion accrue.
- 181 -> 89 : 17 / 29 retenus, statut INSUFFICIENT_SAMPLE au seuil par défaut 30.

## Vérification DST avec des lignes originales de mars

verify-f4-dst.py sélectionne de vraies lignes avec leurs numéros sources et
exerce l'API dans une base temporaire, supprimée après le contrôle. Un import
complete de deux lignes y est simulé uniquement comme fixture : cela ne valide
pas la couverture de mars ni la politique F6 des extraits.

- Ligne source 942 762, départ 9 mars 23:38:43, arrivée 10 mars 03:40:14 :
  **10 891 s réelles** contre 14 491 s par soustraction locale. F4 renvoie la
  durée corrigée et compte le trajet dans DST_SPANNING retenu.
- Ligne source 841 170, départ 9 mars 02:31:02, arrivée 10 mars 02:09:54 :
  l'arrivée est une heure inexistante. Durée stockée null, flag DST_UNRESOLVED,
  exclusion du profil journey. On ne présente pas les 85 132 s locales comme
  une durée réelle.

La vérification Parquet de janvier et ces contrôles sont archivés dans
parquet-verification.json et dst-verification.json. F1–F3 sont aussi contrôlés
contre les résultats précédents, dans regression.json.

## Limites

Les performances ne concernent qu'un mois et deux paires, pas les trois/six mois
ni les expériences E1–E3 distribuées. Trois répétitions ne caractérisent pas
une distribution de latence robuste. Les caches restent actifs.

Les quantiles exacts ont un coût de transfert/mémoire ; l'erreur 422 au-delà de
200 000 candidats n'a pas été exercée par ces paires de janvier. Les drapeaux
qualité ne détectent pas toutes les anomalies possibles. Les strates sont
coarse, les jours fériés ne sont pas neutralisés et la standardisation n'élimine
pas toutes les variations de composition. Les différences de moyennes/médianes
restent descriptives ; les durées/distances ne reconstituent pas un itinéraire.
Les mois complets ne prouvent pas la couverture complète de chaque créneau.

Pour les opérateurs MongoDB : docs/f4-caracteristiques-trajets.md.
