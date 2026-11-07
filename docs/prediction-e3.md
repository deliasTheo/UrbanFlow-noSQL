# Prédiction pour l'expérience E3

Écrite avant toute mesure sur les déploiements répartis, comme le demande le sujet.

## Ce qu'on compare

Trois configurations sur les mêmes trajets (janvier à juin 2024) et les mêmes index :

- **local** : un seul serveur MongoDB ;
- **zone** : deux shards, chaque zone de départ est entière sur un shard, les
  zones sont réparties pour équilibrer le nombre de départs ;
- **période** : deux shards, janvier à mars sur le premier, avril à juin sur le second.

Tout tourne sur le même PC (6 cœurs, 12 threads, 32 Go de mémoire, disque SSD). Les
serveurs partagent donc le processeur, la mémoire et le disque. Le cache total de
MongoDB est fixé à 1,4 Go partout, coupé en deux quand il y a deux shards.

## Les deux charges

- **Charge A, zones chargées** : quelques zones très actives (132 JFK, 161 Midtown
  Center, 236 et 237 Upper East Side). Requêtes F1 sur les départs et F4 sur des
  paires, avec une fenêtre d'une semaine.
- **Charge B, large** : beaucoup de zones et de périodes. F1 sur des zones variées
  à l'arrivée et sur tout le semestre, F2 sur Brooklyn et Queens et sur quatre
  semaines, F5 sur Brooklyn et Queens avec cinq semaines d'historique.

On mesure aussi des mélanges des deux charges.

## Ce qu'on prévoit

**Charge A : le local sera le plus rapide, et la configuration zone la meilleure
des deux configurations réparties.** Une requête F1 sur les départs d'une zone ne
touche qu'un shard avec le placement par zone, sans fusion. Une fenêtre courte ne
touche aussi qu'un shard avec le placement par période, donc l'écart entre les
deux devrait être faible, sauf pour les fenêtres à cheval sur le 1er avril. Le
local devrait quand même gagner : pas de passage par mongos, et un cache de 1,4 Go
au lieu de 0,7 Go pour le shard interrogé. La charge se concentrera sur un shard
dans les deux cas réels : celui qui contient les zones chaudes (zone) ou les mois
tirés (période).

**Charge B : les configurations réparties gagneront sur les grosses agrégations,
et la configuration zone sera la moins bonne des deux.** MongoDB traite une
agrégation sur un seul cœur par serveur. Deux shards font les regroupements en
parallèle et n'échangent ensuite que des comptes partiels, donc F2 et F5 devraient
aller plus vite qu'en local, d'environ 20 à 40 %. Le placement par période devrait
faire mieux que le placement par zone, car une requête limitée à un trimestre ne
lit qu'un shard alors que le placement par zone les interroge presque toujours
tous les deux. L'exception attendue est F1, dont l'étape `$facet` n'est pas
découpée : les documents remontent vers un seul serveur, et le réparti devrait
être plus lent que le local.

**Mélanges** : le passage de la charge A à la charge B devrait faire passer le
meilleur choix du local vers le réparti, vers le milieu du mélange. La charge
entre shards sera déséquilibrée avec le placement par période si les requêtes
visent surtout un trimestre, et plus équilibrée avec le placement par zone.

## Ce qui pourrait donner tort à cette prédiction

Le disque et la mémoire sont partagés : deux shards peuvent se gêner au lieu de
s'aider, et le cache coupé en deux peut coûter plus cher que le parallélisme ne
rapporte. Dans ce cas, le local gagnerait aussi la charge B.
