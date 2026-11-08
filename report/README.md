# Rapport UrbanFlow

`report.tex` compile le rapport en français et `report.pdf` est le PDF correspondant.
Le sujet autorise 10 pages hors annexes. Le label `fin-corps` dans `report.aux` donne
la dernière page du corps, références comprises.

## Compiler

Depuis la racine du dépôt, avec une installation LaTeX (TeX Live, MiKTeX ou Overleaf) :

```bash
latexmk -pdf -interaction=nonstopmode -halt-on-error -cd report/report.tex
```

Sans latexmk, exécuter deux fois `pdflatex report.tex` depuis `report/`.
Sur Overleaf, importer le dossier `report` entier et sélectionner `report.tex`.
Les annexes générées sont versionnées : Python et les Parquet ne sont pas nécessaires
pour compiler.

## Organisation

| Fichier | Contenu | Auteur |
|---|---|---|
| `sections/00-resume.tex` | Résumé | Ion |
| `sections/01-donnees.tex` | Périmètre, données, qualité | Théo |
| `sections/02-modele.tex` | Modèle local, identité, dates, traçabilité | Théo |
| `sections/03-services.tex` | F1 à F5 | Théo |
| `sections/04-f6.tex` | F6 | Ion |
| `sections/05-mesures.tex` | Alternative d'index mesurée en local | Théo |
| `sections/06-reparti.tex` | Placements, travail par instance, comparaison, panne | Ion |
| `sections/07-experiences.tex` | Protocole, E1, E2, E3 | Ion |
| `sections/08-verifications.tex` | Vérifications indépendantes et limites | Ion, Théo |
| `sections/09-references.tex` | Références | Ion, Théo |
| `figures/architecture.tex` | Schéma du déploiement réparti | Ion |
| `figures/temps-par-rapport-au-local.pdf` | Figure générée par `build-figures.py` | Ion |
| `annexes/` | Anomalies, générées par `build-evidence.py` | Théo |

## Sources des chiffres

- E1 à E3, environnement et journal : `results/experiments/`.
- Comparaison, plans `explain`, pannes et placement : `results/distributed/`.
- Vérifications indépendantes : `results/verification/`. Les fichiers `.txt` sont les
  sorties des scripts. `verifications-janvier.txt` vient de l'essai complet sur janvier
  et avril du 7 novembre, dont l'API et l'ingestion sont identiques à `5f11cfd`.
  `f1-zone181-janvier.json` est un calcul direct sur le Parquet de janvier (départs de la zone 181,
  profil activity), dont les totaux sont ceux de l'API.
- Mesures du prototype du 5 novembre : `results/performance/`.
- Bilans des fichiers : `results/ingestion/` et `results/quality/`.

## Régénérer la figure des temps

`report/build-figures.py` lit `results/experiments/` et écrit le PDF dans `report/figures/`.
Il demande une installation LaTeX et `matplotlib`, absent de `requirements.txt` (`pip install matplotlib`). Le PDF est versionné : ce n'est pas
nécessaire pour compiler le rapport.

```bash
python report/build-figures.py
```

## Régénérer les annexes

```bash
.venv/bin/python report/build-evidence.py
```

Windows, avec l'encodage UTF-8 :

```powershell
$env:PYTHONUTF8 = "1"; .\.venv\Scripts\python.exe report\build-evidence.py
```

Le script contrôle les SHA-256 et les effectifs des six Parquet et du référentiel,
compare toutes les colonnes des huit exemples aux Parquet, recherche la copie antérieure
de l'exemple de doublon et recalcule les durées via UTC. Il écrit l'annexe des anomalies et
`evidence-verification.json`. Aucun import ni benchmark n'est lancé.
