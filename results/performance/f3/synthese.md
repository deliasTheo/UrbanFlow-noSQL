# F3 — Synthèse pour le rapport final

F2 a été fusionné dans main via la PR #3. F3 est développé sur une branche séparée.
Ces notes et les mesures brutes sont des supports au rapport final unique.

## Fonctionnement et critères

F3 compare chaque zone/date/créneau à la médiane des mêmes jours de semaine
sur une période antérieure explicitement fournie. Le profil activity exclut
montants négatifs et doublons exacts ; seuls les imports complete sont lus.

Les seuils par défaut demandent trois jours de référence, une médiane d'au moins
20 lignes retenues, un écart d'au moins 20 lignes et 50 %, et un score descriptif
médiane/MAD d'au moins 3. Lorsque MAD=0, seuls les critères absolu/relatif sont
utilisés, avec un avertissement et aucun score infini. Ce n'est pas un test de
significativité ni une preuve causale. Les seuils sont paramétrables.

Les jours fériés fédéraux OPM 2024 et les journées DST entières sont exclus des
comparaisons usuelles. Les références et les motifs d'exclusion restent visibles.
Les mois sources et volumes quotidiens ville servent à signaler une couverture
possiblement inégale. Leur présence ne garantit pas la complétude locale.

## Environnement et protocole de mesure

5 novembre 2026 ; même environnement cloud que F2 : Linux, trois CPU logiques
visibles Xeon Platinum 8370C, cgroup limité à 2 CPU et 8 Gio de RAM ; MongoDB
8.0.16 et Spring Boot 3.5.7 / Temurin JDK 21.0.9 partagent CPU, mémoire et disque.
Le détail est conservé dans environment.json.

Janvier complet : **2 964 624 lignes TLC réelles** dans urbanflow_f3_benchmark.
La copie isolée provient de l'import complet validé utilisé pour F2, sans ajout
de trajets au volume logique ; elle conserve les mêmes identifiants et flags.
Les répétitions physiques entre bases ne sont jamais comptées comme des trajets
supplémentaires. Les Parquet originaux servent à la vérification indépendante.

Deux requêtes pickup : zone 132 et Brooklyn, cible [2024-01-22,2024-02-01[,
référence [2024-01-01,2024-01-22[, heures [0,24[, autres paramètres par défaut.
Les URL exactes sont dans measurements.json.

Sans index : uniquement _id_. Avec index : les deux index F1 zone/date, sans
nouvel index dédié. Chaque phase fait un échauffement puis trois appels mesurés
par requête, zone132 puis Brooklyn. Les explain sont exécutés après les mesures
et séparément pour les pipelines local et ville. Aucune purge des caches ni
mesure à froid revendiquée. L'import était terminé avant les mesures ; les
vérifications indépendantes ont été exécutées après le benchmark.

## Temps HTTP du service complet

Secondes, trois répétitions hors échauffement ; médiane dans chaque configuration.
Écarts-types/min/max sont archivés dans measurements.json.

| Requête | Sans index, répétitions | Médiane | Avec index, répétitions | Médiane |
|---|---|---:|---|---:|
| zone132 | 16.298, 15.925, 16.549 | 16.298 | 14.178, 13.517, 14.523 | 14.178 |
| brooklyn | 15.934, 15.399, 16.691 | 15.934 | 13.782, 13.131, 14.165 | 13.782 |

Le gain est limité : le contrôle ville parcourt encore janvier entier et calcule
les comptes quotidiens sur plusieurs millions de documents. Le GET inclut ce
travail nécessaire au diagnostic de couverture ; il ne faut pas présenter le
seul temps du filtre local comme celui de F3. Les deux index sont conservés pour
leur intérêt déjà mesuré pour F1/F2 et pour le pipeline local de F3.

## Explain : documents examinés et coût global

| Sélection | Pipeline | Sans index | Avec index |
|---|---|---:|---:|
| Zone 132 | Local | 2 964 624 | 145 240 |
| Zone 132 | Ville | 2 964 624 | 2 964 624 |
| Brooklyn | Local | 2 964 624 | 25 258 |
| Brooklyn | Ville | 2 964 624 | 2 964 624 |

Les plans sans index sont des COLLSCAN. Le pipeline local avec index utilise
IXSCAN puis FETCH. Le pipeline ville reste COLLSCAN. Les temps explain sont
ceux d'exécutions supplémentaires et ne sont pas les mesures HTTP du tableau.
Un index temporel ou une agrégation maintenue serait une autre conception à
mesurer sur des périodes et volumes pertinents ; aucune n'est ajoutée ici.

## Vérifications et exemples réels

Les réponses JSON sont strictement identiques entre toutes les répétitions et
avant/après index pour les deux requêtes ; empreintes archivées.
verify-f3-parquet.py recalcule directement depuis le Parquet, sans lire MongoDB :
flags activity, comptes locaux et ville, références, médianes, MAD, écarts,
scores, avertissements de volume/qualité, statuts et comptes par source.

Résultats réels avec les seuils par défaut :

- Zone 132 : dix cellules, huit USUAL et deux INSUFFICIENT_REFERENCE, aucune anomalie.
- Brooklyn : 610 cellules, 389 LOW_BASELINE, 122 INSUFFICIENT_REFERENCE,
  96 USUAL et trois UNUSUAL.
- Zone 181, 23 janvier : 55 lignes retenues contre une médiane de 20 (+175 %).
- Zone 97, 27 janvier : 55 contre 27 (+103,7 %).
- Zone 181, 27 janvier : 49 contre 26 (+88,5 %).

Ces trois hausses ne constituent pas une explication de leur cause. Les comptes
par source et références exactes sont dans les réponses JSON archivées.
Les lundis de référence sont peu nombreux après exclusion des 1er et 15 janvier :
les lundis cibles sont donc non concluants, pas artificiellement « normaux ».

La vérification indépendante porte aussi sur dropoff 8..12 h. Les journées
DST du 10 mars et du 3 novembre, le jour férié du 19 février, l'absence du mois
source et les paramètres invalides sont contrôlés. Le contrôle calendaire Java
vérifie aussi les journées voisines, pour éviter d'exclure une date erronée.
Les contrôles de calendrier ne valident pas une anomalie réelle de mars/novembre :
les données de mesure ne contiennent que janvier. Voir parquet-verification.json.

La non-régression F1 est contrôlée contre les comptes du Parquet et F2 contre
la réponse JSON archivée de la version précédente (zone 181, janvier).

## Limites à conserver dans le rapport

Les trois répétitions et le jeu d'un mois sont une première comparaison, pas
les expériences E1–E3 ni une prédiction sur trois/six mois ou sur le PC utilisateur.
La référence courte rend le seuil MAD fragile ; le comportement MAD=0 est décrit
explicitement. Le calendrier fédéral ne couvre pas toutes les particularités de
New York. La couverture source est un diagnostic conservateur, pas une preuve
que chaque heure/zone est complète. Les arrivées peuvent dépendre du mois de
départ précédent, dont l'absence est signalée. Pas d'import concurrent ni de
snapshot transactionnel entre les deux agrégations.

La réponse contient toutes les cellules et leurs références pour la traçabilité ;
sa taille augmente avec le nombre de zones, jours et références. La consommation
et les performances restent à mesurer sur le périmètre initial complet.

Les opérateurs et règles sont expliqués dans docs/f3-activite-inhabituelle.md.
