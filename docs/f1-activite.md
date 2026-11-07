# F1 — Activité d'une zone

## Lancer l'API

Prérequis : **JDK 21** (pas seulement le runtime Java), Docker Desktop et les
imports MongoDB existants. Vérifier `java -version` et `javac -version`.
Maven est téléchargé automatiquement par le wrapper au premier lancement.

Depuis PowerShell, à la racine du dépôt :

```powershell
docker compose up -d --wait
cd backend
.\mvnw.cmd spring-boot:run
```

Linux/macOS : `./mvnw spring-boot:run` depuis `backend`.
On peut aussi lancer `UrbanFlowApplication` dans son IDE après ouverture du `pom.xml`.
L'API écoute uniquement sur `127.0.0.1:8080`. Arrêt avec Ctrl+C.
Les imports Python restent indépendants : aucun réimport n'est nécessaire.

Configuration facultative : variables `MONGODB_URI`, `MONGODB_DATABASE` et `PORT`.
Valeurs par défaut : `mongodb://127.0.0.1:27018`, `urbanflow` et `8080`.
L'API ne crée ni index ni collection : les index viennent de `urbanflow.deploy`.

## Essayer dans Postman

Créer des requêtes **GET**, sans corps ni authentification :

```text
http://localhost:8080/api/zones
http://localhost:8080/api/activity?zoneId=181&direction=pickup&from=2024-01-01&to=2024-02-01
http://localhost:8080/api/activity?zoneId=181&direction=dropoff&from=2024-01-01&to=2024-02-01
```

Le référentiel permet de retrouver les identifiants : les noms ne sont pas uniques.
181 est Park Slope, Brooklyn. Ces URL sont des exemples de paramètres ; les
résultats sont calculés à chaque appel sur la base disponible, pas prédéfinis.

### Entrées

- `zoneId` : identifiant de zone existant.
- `direction` : `pickup` ou `dropoff`.
- `from`, `to` : dates locales AAAA-MM-JJ ; début inclus, fin exclue.
  Par exemple janvier entier : du 2024-01-01 au 2024-02-01.

Départs : zone **et horodatage de départ**. Arrivées : zone **et horodatage
d'arrivée**. Un trajet parti le 31 janvier à 23h50 et arrivé le 1er février à
00h20 apparaît dans les départs de janvier et les arrivées de février.
Cette règle F1 précise la convention générale d'affectation des trajets par départ.

### Sorties

- `zone`, `direction`, intervalle, fuseau et champ temporel utilisé.
- `totals` : `raw`, `retained`, `excluded` ; ce sont des nombres de lignes sources.
- `byHour` : heures locales 0 à 23, avec les trois comptes, zéros inclus.
- `byWeekday` : lundi = 1, dimanche = 7, zéros inclus.
- `byDate` : dates locales ayant au moins une ligne brute, dans l'ordre.
- `exclusionReasons` : compte par flag ; plusieurs motifs peuvent concerner une
  même ligne, leur somme peut donc dépasser `excluded`.
- `sources` : identifiant SHA-256, nom et mois de chaque import complet, avec ses
  comptes pour la requête ; permet de compter les lignes sous-jacentes par source.
- `coverageNote` : limites de couverture.

`raw = retained + excluded` pour chaque compte. Les répartitions comptent toutes
les lignes brutes correspondantes, puis les retenues dans chaque groupe ; leurs
sommes retrouvent les totaux. Les heures et jours sont des **comptages cumulés**,
pas une moyenne par jour ni un taux corrigé du nombre de lundis dans l'intervalle.
La journée du changement d'heure reste dans F1 ; la comparaison de journées et
son exclusion éventuelle relèvent de F3.

Seuls les imports `complete` contribuent. Le profil `activity` exclut
`NEGATIVE_AMOUNT` et `EXACT_DUPLICATE`, comme `urbanflow/quality.py`.
Une ligne cumulant ces deux flags n'est exclue qu'une fois. L'original positif
d'une annulation reste retenu. Les autres anomalies ne sont pas exclues par F1.

Les fichiers mensuels peuvent contenir des dates hors mois. On ne sélectionne
donc pas les imports selon leur mois annoncé. La réponse liste tous les imports
complets consultés, y compris ceux sans contribution. Elle ne garantit pas la
couverture complète d'une période : un résultat nul peut venir d'un mois absent,
et les arrivées en début de période peuvent provenir de départs du mois précédent.
Un import `loading` ou `failed` est ignoré ; cela ne constitue pas une archive complète.
Il ne faut pas importer pendant une analyse : l'API n'offre pas d'instantané
transactionnel entre la lecture des imports et l'agrégation.

### Erreurs

- 400 : paramètre absent/invalide ou intervalle vide/inversé.
- 404 : zone inconnue.
- 503 : aucun import complet, MongoDB indisponible ou requête interrompue.

L'agrégation est limitée à 120 secondes côté MongoDB. Aucun résultat partiel
n'est renvoyé comme complet. Sans index analytique, une recherche peut être lente
sur plusieurs millions de documents. Les index retenus et la procédure de
comparaison sont décrits ci-dessous.

## Organisation et requête MongoDB

`ActivityController` expose les routes. `ActivityService` valide l'intervalle,
applique les conventions F1 et construit la réponse. `ActivityRepository` utilise
`MongoTemplate` pour lire MongoDB, sans JPA ni chargement de tous les trajets en Java.
Les records Java de réponse sont des DTO ; ils ne modifient pas le modèle stocké.

Le pipeline est explicite en BSON :

1. `$match` : zone, intervalle sur la chaîne ISO locale et fichiers complets.
2. `$project` : heure, jour ISO, date locale et booléen de rétention qualité.
3. `$facet` : comptes globaux, par heure, jour, date, source et motif d'exclusion.
4. `$group` et `$sort` dans chaque branche pour des résultats déterministes.

Les chaînes ISO locales sont comparables lexicalement dans le format produit
par l'ingestion. L'extraction calendaire les traite comme des valeurs sans
décalage : aucune seconde conversion UTC ne vient déplacer l'heure locale.
Aucune durée n'est calculée dans F1.

Le profil activity est reproduit en Java ; en cas de changement dans `quality.py`,
il faut aussi mettre à jour `QualityProfiles.java`.


## Vérification

Contrôles HTTP contre MongoDB 8.0.16, dans une base temporaire distincte : les 50 000
premières lignes de janvier et les 50 000 premières de mars 2024, sans données
synthétiques. Les indicateurs qualité ont été calculés sur ces sous-ensembles :
ce contrôle ne valide pas la détection des doublons à l'échelle du mois entier.

Comparaison des réponses avec un calcul Python à partir de ces lignes sources :

| Zone | Sens | Brutes | Retenues | Exclues |
|---|---|---:|---:|---:|
| 181 | Départs | 24 | 24 | 0 |
| 181 | Arrivées | 150 | 147 | 3 |
| 132 | Départs | 2 681 | 2 615 | 66 |
| 132 | Arrivées | 1 116 | 1 087 | 29 |

Paramètres : `from=2024-01-01`, `to=2024-02-01`. Ces effectifs concernent
**uniquement le sous-ensemble de vérification**, pas le mois complet.
Les répartitions par heure, jour de semaine et date correspondent également.
Les sommes des comptes par source retrouvent les totaux. Les réponses 400/404,
l'absence d'import complet (503), l'exclusion des imports loading/failed, une
période sans résultats et MongoDB inaccessible (503) ont été vérifiées.


## Index F1

`python -m urbanflow.deploy --placement local` crée les deux index zone/date, un
pour les départs et un pour les arrivées, avec ceux des autres services. La commande
peut être relancée sans dupliquer les index. Une fois créés, ils persistent et
MongoDB les maintient lors des imports.

Les index occupent du disque et augmentent le travail d'écriture ; ils accélèrent la
sélection sans éviter les regroupements sur les trajets retenus par le filtre.
Les premières mesures sont dans [le suivi des mesures F1](../results/performance/f1-indexes.md).


Pour une explication étape par étape des opérateurs et de leur rôle dans le code,
voir [Comprendre les requêtes MongoDB de F1](f1-mongodb-explique.md).
