# F1 — Comparaison sans / avec index

## Premières mesures

Temps HTTP relevés à la main le 5 novembre 2026 sur un PC de développement. Le jeu
visé est janvier à mars 2024 ; le nombre de documents de cette base n'a pas été
relevé. Paramètres : zone 181 (Park Slope, Brooklyn), du 1er janvier 2024 inclus au
1er février 2024 exclu.

Requêtes GET exactes :

```text
http://localhost:8080/api/activity?zoneId=181&direction=pickup&from=2024-01-01&to=2024-02-01
http://localhost:8080/api/activity?zoneId=181&direction=dropoff&from=2024-01-01&to=2024-02-01
```

| Configuration | Sens | Appel successif | Temps relevé |
|---|---|---:|---:|
| Sans index F1 | pickup | 1 | 83 s |
| Sans index F1 | pickup | 2 | 32 s |
| Sans index F1 | pickup | 3 | 17 s |
| Sans index F1 | dropoff | 1, après les appels pickup | 25 s |
| Sans index F1 | dropoff | 2 | 16 s |
| Avec index F1 d'arrivée | dropoff | 1 après création | 1,9 s |
| Avec index F1 d'arrivée | dropoff | 2 | 0,9 s |
| Avec index F1 de départ | pickup | 1 après création, après les appels dropoff | 0,9 s |
| Avec index F1 de départ | pickup | 2 | 0,030 s (30 ms) |

Les réponses ont été comparées à l'œil, sans comparaison automatique, et n'ont pas
été archivées, pas plus que les plans d'exécution. Aucun vidage des caches n'a été
fait. Ces temps sont donc des repères, pas une expérience contrôlée.

Les caches de MongoDB et du système peuvent expliquer une partie de la baisse, sans
que cette cause ait été isolée. Les appels dropoff peuvent réutiliser des pages
chargées par pickup : le premier dropoff n'est pas un appel à froid. La baisse de
83 à 17 s ne vient pas d'un index, car aucun index F1 n'existait encore.

## Choix de conception comparé

Alternative sans index analytique : seul l'index automatique `_id_` sur trips.
Choix retenu : deux index non uniques, zone en égalité puis date en intervalle :

```javascript
{ "data.PULocationID": 1, "data.tpep_pickup_datetime": 1 }
{ "data.DOLocationID": 1, "data.tpep_dropoff_datetime": 1 }
```

`urbanflow/deploy.py` les crée avant l'import, et MongoDB les maintient ensuite lors
des insertions, notamment pour F6. Ils coûtent de l'espace disque et du travail à
l'import. L'API ne force pas leur utilisation : le planificateur MongoDB décide.

## Lecture des résultats

Les temps passent de 83/32/17 s à 0,9/0,030 s pour pickup, et de 25/16 s à 1,9/0,9 s
pour dropoff. Ils soutiennent l'intérêt des index, sans isoler leur effet de celui
des caches. Deux répétitions après index ne suffisent pas à établir une latence
stable.

Les comparaisons mesurées avec répétitions, plans d'exécution et réponses archivées
sont dans `results/performance/f2/` à `f5/`, pour les mêmes index et sur janvier
complet.
