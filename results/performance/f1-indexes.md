# F1 — Comparaison sans / avec index

## Mesures exploratoires sur le PC de l'utilisateur

Mesures de temps HTTP communiquées dans le chat le 5 novembre 2026.
Le jeu de référence prévu est janvier–mars 2024 ; le nombre exact de documents
sur le PC reste à confirmer. Les paramètres suivants ont été confirmés par
l'utilisateur pour les comparaisons avant et après index : zone 181 (Park Slope,
Brooklyn), du 1er janvier 2024 inclus au 1er février 2024 exclu.

Requêtes GET exactes :

```text
http://localhost:8080/api/activity?zoneId=181&direction=pickup&from=2024-01-01&to=2024-02-01
http://localhost:8080/api/activity?zoneId=181&direction=dropoff&from=2024-01-01&to=2024-02-01
```

| Configuration | Sens | Appel successif | Temps rapporté |
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

Les temps sont rapportés manuellement, sans précision supplémentaire. Les réponses
et plans d'exécution correspondants n'ont pas été archivés. L'ordre après index rapporté est dropoff, puis pickup ; aucun vidage des caches
n'a été rapporté. Ce sont des repères exploratoires, pas encore une expérience contrôlée.

Les caches MongoDB et du système peuvent expliquer une partie de la baisse,
sans que cette cause ait été isolée. Les appels dropoff peuvent réutiliser des
pages chargées par pickup ; le premier dropoff n'est donc pas un appel à froid
établi. Il ne faut pas attribuer la baisse de 83 à 17 s à un index : aucun index
F1 n'avait encore été créé selon le déroulement rapporté.

## Choix de conception à comparer

Alternative sans index analytique : seul l'index automatique `_id_` sur trips.
Choix proposé : deux index non uniques, zone en égalité puis date en intervalle :

```javascript
{ "data.PULocationID": 1, "data.tpep_pickup_datetime": 1 }
{ "data.DOLocationID": 1, "data.tpep_dropoff_datetime": 1 }
```

Script reproductible : `scripts/create-f1-indexes.js`. Il est exécuté explicitement,
pas au démarrage de Spring ni pendant l'ingestion. MongoDB maintient ensuite les
index lors des insertions, notamment pour F6. Coûts : espace disque et travail
supplémentaire à l'import. Les temps rapportés baissent nettement après création ; le gain dépend de la
sélectivité et des conditions de cache.

## Compléments nécessaires pour le rapport

Le sujet exige de comparer un choix de conception à une alternative sur au moins
deux requêtes représentatives. Une requête pickup et une dropoff permettent de
construire cette comparaison, avec les mêmes données et paramètres avant/après.
Les temps HTTP mesurent le service complet, pas seulement le moteur MongoDB.

Les URL, temps et ordre des appels sont consignés ci-dessus. Restent à archiver :
réponses JSON, état des imports, effectif de trips et liste des index présents.
Documenter le matériel, les ressources Docker et les versions. Définir le même
échauffement pour les deux configurations ; distinguer le premier appel des
répétitions, puis présenter une tendance centrale et la variabilité.

Pour compléter ces premières mesures : réaliser des répétitions avec un
échauffement défini, vérifier l'identité des réponses et examiner le pipeline avec `explain("executionStats")`, notamment
`totalDocsExamined`, `totalKeysExamined` et le plan choisi. L'API ne force pas
l'utilisation d'un index : le planificateur MongoDB décide.

Les mesures observées passent de 83/32/17 s à 0,9/0,030 s pour pickup et de
25/16 s à 1,9/0,9 s pour dropoff. Elles soutiennent l'intérêt des index pour ces
requêtes, sans isoler leur effet de celui des caches. Deux répétitions après
index ne suffisent pas à établir une latence stable ; 30 ms est une observation,
pas une garantie générale. Aucun facteur d'accélération contrôlé n'est déduit.
Les résultats et limites de cette comparaison iront dans la partie
conception/expériences du rapport, avec ce fichier comme trace des observations. Ce travail ne remplace pas les
expériences distribuées E1–E3 demandées séparément dans le sujet.
