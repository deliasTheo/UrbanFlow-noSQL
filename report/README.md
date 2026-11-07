# Rapport — contribution données et F1–F5

`main.tex` compile la contribution en français. `main.pdf` est le PDF correspondant,
vérifié après compilation. La version initiale comporte **5 pages de corps, références
comprises, et 2 pages d'annexes**. Le sujet autorise 10 pages hors annexes pour le
rapport final entier : conserver une marge pour la contribution du second membre.

## Compiler

Depuis la racine du dépôt, avec une installation LaTeX (TeX Live, MiKTeX ou Overleaf) :

```bash
latexmk -pdf -interaction=nonstopmode -halt-on-error -cd report/main.tex
```

Sans latexmk, exécuter deux fois `pdflatex main.tex` depuis `report/`.
Sur Overleaf, importer **le dossier report entier** et sélectionner `main.tex`.
Les annexes générées sont versionnées : Python et les Parquet ne sont pas nécessaires
pour compiler. Le préambule utilise les paquets habituels, notamment Latin Modern,
Babel, geometry, amsmath, booktabs, tabularx, microtype, hyperref, fancyhdr et enumitem.
Une variante Babel locale est prévue lorsque french.ldf n'est pas installé.

## Intégrer la partie du second membre

Les sections sont séparées pour conserver **un seul rapport final**. Le point
`sections/04-complement-binome.tex`, vide et commenté, accueille sa rédaction ;
il se situe après F5, avant les mesures locales. Il peut utiliser plusieurs `\input`.
Éviter de créer une seconde page de titre, bibliographie ou commande `\appendix`.
Après intégration, vérifier le nombre de pages du corps : la valeur de `fin-corps`
dans `main.aux` donne actuellement la page 5. Les annexes commencent ensuite.

Les noms des deux membres n'ont pas été fournis dans cette conversation : ajouter
les deux noms dans `\author` et, si souhaité, remplacer les désignations de rôle par
les noms dans la répartition du travail. Aucun nom n'a été déduit du compte GitHub.

À intégrer par le second membre, sur la base de ses résultats effectifs :

- F6 : identité finale, extraits chevauchants, reprise et réimport, démonstration de
  la mise à jour sur local et distribué ; le code correspondant est déjà dans main.
- Distribution : deux instances de données, placements par zone et par période,
  chemin des trois types de requêtes, calculs locaux et résultats échangés.
- Comparaison automatique après ordre canonique, notamment entre plusieurs instances.
- Arrêt d'une instance : ce que renvoient F1 et F5, limites de récupération.
- E1 : trois volumes croissants dont six mois, effectifs distincts, ingestion,
  stockage, latences ; E2 sur les trois configurations et mêmes données ; E3 avec
  prédiction déposée avant mesure et analyse des deux charges de travail.
- Matériel, versions, limites, échauffement/cache, répétitions et variabilité des
  expériences finales. Les scripts existants ne prouvent pas que ces essais ont réussi.

Le bonus E4 est facultatif. Le sujet demande aussi code, README reproductible,
mesures brutes, présentation et démonstration ; ils ne sont pas remplacés par ce PDF.

## Sources et versions

Le texte a été rédigé après `git pull --ff-only origin main`, sur l'état intégré
**5f11cfd**. Il tient compte notamment de la nouvelle identité Pandas + rang,
des insertions au lieu d'upserts, de `/api/trips`, des profils Java mutualisés,
des quatre index gérés par `urbanflow.deploy`, des optimisations de F3 et de la
construction différée des preuves de F5.

Les exemples et mesures du 5 novembre proviennent de `results/performance/f2` à
`f5`, pas d'une réexécution de l'application actuelle. Les essais de F3 sont
antérieurs à son optimisation et à l'index temporel supplémentaire. Le texte le
précise ; aucune nouvelle mesure locale, distribuée ou sur six mois n'a été inventée.
Les bilans qualité sont par fichier et ne sont pas un comptage actuel de la base
après la nouvelle déduplication inter-fichiers.

Pour régénérer les annexes avec les fichiers sources présents :

```bash
.venv/bin/python report/build-evidence.py
```

Windows : `.\.venv\Scripts\python.exe report\build-evidence.py`.
Le script contrôle SHA-256 et nombres de lignes, compare toutes les colonnes des
huit exemples aux Parquet, recherche la copie antérieure de l'exemple de doublon
et recalcule les durées via UTC. Il écrit les deux annexes et
`evidence-verification.json`. Les fréquences sont reprises explicitement du rapport
qualité existant, pas recalculées par ce script. Aucun import ni benchmark n'est lancé.
