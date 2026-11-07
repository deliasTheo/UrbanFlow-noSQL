# F5 — Synthèse

## Choix de conception

Comparer des périodes de même durée, lundi à lundi, et les mêmes origines.
Définir le dénominateur comme tous les départs retenus de l'aire, vers toutes les
destinations, y compris les flux internes. Profil flows et imports complete.
Une sélection absente signifie les origines connues du référentiel de zones.

Pour chaque flux : pA=nA/NA, pB=nB/NB et écart pB-pA. L'attendu pA×NB sépare le
changement associé au volume global du résidu propre au flux. Aucun test classique
de significativité n'est utilisé. Les comptes et fichiers justificatifs sont exposés.

La baseline antérieure au courant fournit les parts de chaque semaine et leurs
différences entre semaines adjacentes. Le ratio descriptif est
|pB-pA| / max(p90 des variations hebdomadaires absolues, minShareChange).
Les seuils d'effectif, de baseline et de variation doivent passer avant classement.
Défauts : 20 trajets dans au moins une période, 20 sur la baseline, 100 départs
par semaine pour le dénominateur, trois semaines historiques/deux différences,
minShareChange=0,001 et ratio>=2. Tous sont paramétrables.

Les listes increases/decreases sont triées par variation absolue de part,
puis identifiants. Les autres grands écarts portent leur motif de non-qualification.
Une absence de couverture ou d'historique empêche de classer des changements.
Les parts sont null si le dénominateur est nul, pas artificiellement zéro.

MongoDB filtre origines/dates/fichiers, prépare semaine et qualité puis compte
par paire/semaine/source. Java utilise ces groupes pour les parts, p90 et tris.
Pas de chargement de millions de trajets détaillés, pas de nouvel index F5.

## Protocole

5 novembre 2026, même serveur distant que les mesures précédentes : MongoDB 8.0.16,
Spring Boot 3.5.7 / JDK Temurin 21.0.9, cgroup 2 CPU et 8 Gio. API et MongoDB
partagent le même hôte et le disque ; détail dans environment.json.

Janvier complet : **2 964 624 lignes réelles**, copie isolée dans urbanflow_f5_benchmark,
mêmes identifiants et flags que l'import validé. Les copies entre bases ne sont
pas comptées comme un volume supplémentaire de trajets.

Deux requêtes : zoneIds=132 et borough=Brooklyn. Référence [15,22 janvier[,
courant [22,29 janvier[, baseline [1er,22 janvier[ ; paramètres de seuil par défaut.
Les URL exactes sont archivées dans measurements.json.

Trois configurations : _id_ seul, deux index F1, puis F1 + index F4. Un échauffement
et trois appels HTTP mesurés par requête/phase, ordre zone132 puis Brooklyn.
Explain exécuté après chaque mesure de requête. Caches conservés, aucune mesure
à froid revendiquée. La vérification Parquet et la non-régression ont été lancées
après les mesures, sans import concurrent pendant celles-ci.

## Résultats de performance

Médianes HTTP en secondes ; répétitions, min/max, écart-type et échauffement archivés.

| Requête | Sans index analytique | Index F1 | F1 + F4 |
|---|---:|---:|---:|
| zone132 | 3.653 | 0.971 | 1.046 |
| brooklyn | 3.799 | 0.572 | 0.297 |

| Requête | Documents examinés sans index | Index F1 | F1 + F4 |
|---|---:|---:|---:|
| Zone 132 | 2 964 624 | 133 084 | 133 084 |
| Brooklyn | 2 964 624 | 22 902 | 22 902 |

COLLSCAN devient un parcours de l'index F1 départ avec FETCH. L'ajout de F4 ne
réduit pas le travail examiné pour ces requêtes ; la destination n'est pas fixée.
Les différences de temps entre les deux dernières phases ne prouvent donc pas
un bénéfice causal de F4 : ordre, caches, plan et variabilité doivent être considérés.
Aucun index supplémentaire n'est retenu pour F5. Les index F1/F4 restent utiles
aux services qui ont justifié leur création.

Les JSON sont strictement identiques dans les trois configurations et répétitions.
Les plans explain proviennent du constructeur Java du pipeline de production,
exporté par ExportChangePipeline.java, pas d'une requête réécrite approximativement.

## Vérification indépendante et résultats réels

verify-f5-parquet.py relit janvier complet, recalcule les doublons, montants
négatifs et zones 264/265 depuis les colonnes sources, sans lire MongoDB. Il
recalcule les paires, totaux hebdomadaires, parts, p90, scores et classements sur
**toutes les paires**. Les effectifs, parts, rangs, comptes historiques et
la décomposition volume/résidu des résultats affichés sont contrôlés.

La vérification couvre une zone, Brooklyn et toute la ville, les paramètres
invalides, le mois absent et une baseline trop courte. Détail dans
parquet-verification.json. Les comparaisons flottantes indépendantes tolèrent
l'arrondi numérique ; la comparaison sans/avec index reste stricte.

Exemples réels avec les paramètres du benchmark :

- Zone 132 : 30 263 départs retenus en référence, 26 739 au courant (-11,64 %).
  Sur 255 paires présentes, trois passent les critères.
- JFK -> Homecrest (132 -> 123) : 29 puis 146 retenus. Part de 0,0958 % à 0,5460 %,
  soit +0,4502 point. Avec le seul effet volume, l'attendu serait 25,62 trajets ;
  le résidu est +120,38. Ratio de variation 4,50 avec le plancher exposé.
- JFK -> JFK (132 -> 132) : 1 381 puis 1 277, un compte en baisse mais une part en
  hausse de +0,2125 point car le volume total de la zone baisse davantage. Cela
  illustre pourquoi les comptes seuls ne suffisent pas.
- Brooklyn : 5 526 puis 5 858 retenus (+6,01 %). Sur 4 113 paires présentes,
  une baisse est qualifiée : East New York -> East New York (76 -> 76), 24 puis
  11, soit -0,2465 point. Ces trajets internes ne décrivent pas un itinéraire précis.
- Périmètre ville : 664 866 puis 694 597 retenus, 19 368 paires présentes,
  aucune qualifiée avec ces seuils. On ne force pas un classement positif.

Les comptes et références de chaque résultat renvoyé sont justifiés par source.
Les régressions F2/F3/F4 ont des JSON identiques aux sorties précédentes sur
janvier ; F1 retrouve les totaux vérifiés précédemment dans le Parquet.

## Limites

Janvier ne fournit ici que trois semaines de baseline et deux différences,
avec des semaines fériées (1er/15 janvier). Le p90 est donc fragile. Les dates
fériées et DST sont signalées, pas neutralisées ; aucune cause de changement
n'est établie. Le calendrier fédéral ne couvre pas tous les événements locaux.

Le plancher minShareChange et le ratio rendent le cas d'une variation historique
nulle fini, pas automatiquement significatif. Les flux sans historique probant
restent non qualifiés. Une baseline peut inclure la référence : ce n'est pas une
validation statistique indépendante. Pour des périodes de plusieurs semaines,
le seuil hebdomadaire reste descriptif, pas une erreur-type de la moyenne.

La couverture par mois source et total hebdomadaire est conservatrice, pas une
preuve de complétude locale. Aucun import concurrent ni snapshot transactionnel.
Le volume mémoire des groupes croît avec les semaines, zones et fichiers, même
si limit est petit. Les performances d'un mois et trois répétitions ne prédisent
pas celles de trois/six mois ou des configurations distribuées E1–E3.

Sur le cluster, les comptes de toutes les instances sont agrégés avant le calcul
des parts et de la variabilité. Une réponse échoue explicitement si une instance
nécessaire ou MongoDB est indisponible.

Le détail des opérateurs et commandes est dans docs/f5-changements-flux.md.
