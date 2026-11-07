# F2 — Synthèse des mesures et vérifications

Ces mesures comparent les index sur un serveur distant. Elles ne font pas partie
des expériences E1–E3.

## Données et protocole

- 5 novembre 2026 ; janvier 2024 complet, **2 964 624 lignes sources réelles**.
- Base dédiée urbanflow_f2_benchmark ; import complete ; aucune réplication comptée.
- MongoDB 8.0.16, Spring Boot 3.5.7, JDK Temurin 21.0.9, Python 3.12 / PyMongo 4.15.3.
- Linux x86_64, trois CPU logiques Intel Xeon Platinum 8370C à 2,80 GHz ;
  environ 9,7 Gio de RAM visibles au processus. MongoDB, Python et Java partagent
  la machine et le disque. Aucune limite explicite Memory/NanoCpus sur le conteneur
  MongoDB. Le cgroup de l’environnement est limité à **8 Gio** de RAM et à
  un quota CPU de **2 CPU** (cpu.max = 200000 100000), malgré trois CPU visibles.
- Deux requêtes : zoneIds=181 et borough=Brooklyn, from=2024-01-01,
  to=2024-02-01, paramètres de seuil et limit par défaut.
- Référence : seul _id_. Alternative : les deux index composés F1 zone/date.
- Par phase et requête : un appel d'échauffement, puis trois mesures HTTP séquentielles.
  Sans index : zone181 puis Brooklyn ; création des index ; même ordre avec index.
- Les explain sont exécutés après les mesures de chaque requête. Pas d'import
  concurrent, pas de purge des caches ; aucune mesure à froid n'est revendiquée.
  Les phases et la construction des index peuvent alimenter les caches.

## Latence HTTP observée

Les valeurs ci-dessous sont en secondes ; les médianes sont calculées sur les
**trois répétitions mesurées**, hors échauffement. Écarts-types/min/max et temps
d'échauffement sont conservés dans measurements.json.

| Requête | Sans index : répétitions | Médiane | Avec index : répétitions | Médiane |
|---|---|---:|---|---:|
| zone181 | 2.313, 2.942, 2.114 | 2.313 | 0.238, 0.209, 0.202 | 0.209 |
| brooklyn | 3.461, 4.748, 3.464 | 3.464 | 1.330, 1.335, 1.239 | 1.330 |

Ces mesures ne sont pas comparables directement aux premiers temps de F1 : matériel,
volume et traitements diffèrent. Elles ne permettent pas de prédire la latence
sur trois/six mois ni sur une machine différente.

## Travail mesuré par MongoDB

| Requête | Documents examinés sans index | Avec index | Clés examinées avec index |
|---|---:|---:|---:|
| Zone 181 | 2 964 624 | 7 924 | 8 049 |
| Brooklyn | 2 964 624 | 119 350 | 132 552 |

Les plans sans index parcourent la collection (COLLSCAN). Avec les index,
MongoDB combine des parcours d'index pour les branches du OR puis lit les
documents (FETCH). Les deux requêtes bénéficient ici des index, avec un gain
plus marqué pour la petite zone. Les plans complets sont archivés, ainsi que
les pipelines exportés depuis le constructeur Java de production.

La création des deux index a pris environ 16.89 s. La taille totale
des index rapportée par collStats passe de 41021440 à 131129344 octets,
soit 85.9 Mio supplémentaires. C'est le coût de stockage observé,
pas une mesure du surcoût d'ingestion : les index ont été construits après l'import.

## Identité des réponses et vérification indépendante

Le script compare tous les JSON des répétitions et compare strictement les
réponses sans/avec index. Les empreintes SHA-256 correspondantes sont archivées :
**aucune différence de réponse** pour les deux requêtes.

Le script verify-f2-parquet.py relit le Parquet original entier et recalcule
montants négatifs, doublons exacts et zones 264/265 sans lire MongoDB ni ses flags.
Il compare totaux, destinations, classement et seuils, comptes des paires,
retours, parts, semaines, classification et effectifs justificatifs par source.
Le détail du résultat est dans parquet-verification.json. Cette vérification
couvre F2 pour janvier et ces paramètres ; elle ne valide pas tous les cas futurs.

Exemples réels de résultats :

- Zone 181 : 983 lignes candidates, 973 retenues et 10 exclues ; 7 paires atteignent minTrips=20.
- Paire 181 → 89 : 48 départs retenus, 18 dans le sens inverse, classée regular.
- Paire 181 → 181 : 122 retenus ; trajet interne, aucune direction opposée artificielle.
- Brooklyn : 25 258 candidates, 24 860 retenues et 398 exclues ; 160 paires au seuil.

Autres contrôles HTTP : erreurs 400/404, sélection multi-zones,
historique trop court, mois source manquant, seuil élevé masquant le classement
sans modifier les totaux, et appel F1 après ajout de F2.

## Interprétation

Les deux index déjà retenus pour F1 sont utiles à F2 sur ces requêtes. Aucun
nouvel index dédié à F2 n'a été ajouté. L'index d'arrivée ne borne pas directement
la date de départ des retours ; un troisième index serait une autre alternative
à mesurer si nécessaire, avec son coût disque/écriture.

Trois répétitions constituent une première comparaison reproductible, pas une
estimation robuste de la distribution des latences. La classification
regular/peak utilise des seuils exploratoires exposés dans l'API, non un test de
significativité. Les détails du pipeline et les limites sont dans docs/f2-flux.md.
