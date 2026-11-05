# F1 — Comparaison sans / avec index

## Mesures exploratoires sur le PC de l'utilisateur

Mesures de temps HTTP communiquées dans le chat le 5 novembre 2026.
Le jeu de référence prévu est janvier–mars 2024 ; le nombre exact de documents
sur le PC et les paramètres effectifs des requêtes restent à confirmer.
Les exemples donnés dans le guide utilisent zoneId=181, from=2024-01-01 et
to=2024-02-01, mais ces valeurs ne sont pas attestées pour ces mesures.

| Configuration | Sens | Appel successif | Temps rapporté |
|---|---|---:|---:|
| Sans index F1 | pickup | 1 | 83 s |
| Sans index F1 | pickup | 2 | 32 s |
| Sans index F1 | pickup | 3 | 17 s |
| Sans index F1 | dropoff | 1, après les appels pickup | 25 s |
| Sans index F1 | dropoff | 2 | 16 s |

Les temps sont rapportés manuellement, sans précision supplémentaire. Les réponses
et plans d'exécution correspondants n'ont pas été archivés. Ce sont des repères
exploratoires, pas encore une expérience contrôlée.

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
supplémentaire à l'import. Le gain reste à mesurer ; il dépend de la sélectivité.

## Compléments nécessaires pour le rapport

Le sujet exige de comparer un choix de conception à une alternative sur au moins
deux requêtes représentatives. Une requête pickup et une dropoff permettent de
construire cette comparaison, avec les mêmes données et paramètres avant/après.
Les temps HTTP mesurent le service complet, pas seulement le moteur MongoDB.

À conserver pour chaque requête : URL exacte, réponse JSON, état des imports,
effectif de trips, index présents, ordre des appels et temps successifs.
Documenter le matériel, les ressources Docker et les versions. Définir le même
échauffement pour les deux configurations ; distinguer le premier appel des
répétitions, puis présenter une tendance centrale et la variabilité.

Après création : relever plusieurs temps pickup et dropoff, vérifier l'identité
des réponses et examiner le pipeline avec `explain("executionStats")`, notamment
`totalDocsExamined`, `totalKeysExamined` et le plan choisi. L'API ne force pas
l'utilisation d'un index : le planificateur MongoDB décide.

Aucune mesure avec index n'est encore disponible. Ne pas calculer de gain ni
conclure que le choix est validé avant ces mesures. Les résultats et limites de
cette comparaison iront dans la partie conception/expériences du rapport, avec
ce fichier comme trace des observations initiales. Ce travail ne remplace pas les
expériences distribuées E1–E3 demandées séparément dans le sujet.
