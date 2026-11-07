"""Vérifie les preuves dans les sources TLC puis génère les annexes LaTeX.
Depuis la racine : .venv/bin/python report/build-evidence.py
Ne relance aucune expérience MongoDB et ne modifie aucun résultat existant.
"""
import hashlib
import json
from pathlib import Path
import math
import pandas as pd
import pyarrow.parquet as pq

ROOT=Path(__file__).resolve().parents[1]
manifest=json.loads((ROOT/'data/manifest.json').read_text())['files']
quality=json.loads((ROOT/'results/quality/quality_report.json').read_text())
selection=[('2024-01','PICKUP_OUTSIDE_FILE_MONTH'),('2024-01','NON_POSITIVE_DURATION'),
 ('2024-01','ZERO_DISTANCE'),('2024-01','NEGATIVE_AMOUNT'),('2024-01','UNKNOWN_ZONE'),
 ('2024-02','EXACT_DUPLICATE'),('2024-03','DST_SPANNING'),('2024-03','DST_UNRESOLVED')]
def number(n):return f'{n:,}'.replace(',',r'\,')
def escaped(s):
 for a,b in [('&',r'\&'),('%',r'\%'),('_',r'\_'),('#',r'\#')]:s=str(s).replace(a,b)
 return s
proofs=[];annex=[]
for month in ['2024-01','2024-02','2024-03']:
 file=f'yellow_tripdata_{month}.parquet';path=ROOT/'data/raw'/file;entry=manifest[file]
 assert path.stat().st_size==entry['size_bytes'],file
 h=hashlib.sha256()
 with path.open('rb') as stream:
  while chunk:=stream.read(1024*1024):h.update(chunk)
 assert h.hexdigest()==entry['sha256'],file
 parquet=pq.ParquetFile(path);assert parquet.metadata.num_rows==entry['num_rows']
 report=next(x for x in quality if x['file_month']==month)
 cache={};offsets=[];offset=0
 for group in range(parquet.num_row_groups):offsets.append(offset);offset+=parquet.metadata.row_group(group).num_rows
 for _,code in [x for x in selection if x[0]==month]:
  anomaly=report['anomalies'][code];record=anomaly['example']['record'];row=record['row_number']
  group=max(g for g,start in enumerate(offsets) if start<=row)
  if group not in cache:cache[group]=parquet.read_row_group(group).to_pandas()
  original=cache[group].iloc[row-offsets[group]]
  for key,value in record.items():
   if key in ['row_number','duration_s','naive_duration_s']:continue
   v=original[key]
   if isinstance(v,pd.Timestamp):assert v==pd.Timestamp(value),(file,row,key)
   elif value is None:assert pd.isna(v),(file,row,key)
   elif isinstance(value,(int,float)):assert math.isclose(float(v),value,rel_tol=1e-12,abs_tol=1e-12),(file,row,key)
   else:assert v==value,(file,row,key)
  real=[]
  for key in ['tpep_pickup_datetime','tpep_dropoff_datetime']:
   real.append(original[key].tz_localize('America/New_York',ambiguous='NaT',nonexistent='NaT'))
  duration=None if any(pd.isna(v) for v in real) else (real[1].tz_convert('UTC')-real[0].tz_convert('UTC')).total_seconds()
  if code!='DST_UNRESOLVED':assert duration==record['duration_s']
  else:assert duration is None
  duplicate_of=None
  if code=='EXACT_DUPLICATE':
   for g in range(group+1):
    frame=cache[g] if g in cache else parquet.read_row_group(g).to_pandas()
    earlier=frame.iloc[:max(0,min(len(frame),row-offsets[g]))]
    mask=(earlier.eq(original)|(earlier.isna()&original.isna())).all(axis=1)
    positions=mask.to_numpy().nonzero()[0]
    if len(positions):duplicate_of=int(offsets[g]+positions[0]);break
   assert duplicate_of is not None,'Copie originale introuvable'
  proofs.append({'duplicateOfRow':duplicate_of,'file':file,'sha256':entry['sha256'],'row_number':row,'flag':code,'sourceFieldsMatch':True,'realDurationSeconds':duration})
  pct=100*anomaly['count']/report['num_rows']
  annex.append((month,code,anomaly['count'],pct,record,duration,duplicate_of))
 del cache

provenance=r'''\section{Provenance du jeu initial}\label{ann:provenance}
Le manifeste est \chemin{data/manifest.json}. Les fichiers ci-dessous ont été
récupérés le 2 novembre 2026 selon les métadonnées enregistrées. Les tailles,
empreintes et effectifs ont été revérifiés lors de la préparation de ces annexes.
Les numéros de ligne des exemples sont en base zéro.

Les URL Parquet suivent \url{https://d37ci6vzurychx.cloudfront.net/trip-data/}
et les noms mensuels ci-dessous. Le référentiel vient de
\url{https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv}.
'''
for file in ['yellow_tripdata_2024-01.parquet','yellow_tripdata_2024-02.parquet','yellow_tripdata_2024-03.parquet','taxi_zone_lookup.csv']:
 entry=manifest[file];path=ROOT/'data/raw'/file
 # Le CSV est vérifié ici, les Parquet l'ont été dans la boucle précédente.
 if file.endswith('.csv'):
  assert hashlib.sha256(path.read_bytes()).hexdigest()==entry['sha256']
  assert len(pd.read_csv(path))==265
 assert path.stat().st_size==entry['size_bytes'],file
 rows=entry.get('num_rows',265)
 sha=r'\allowbreak{}'.join(entry['sha256'][i:i+8] for i in range(0,64,8))
 provenance+=("\n\\paragraph{\\code{"+file+"}}\n")+f"{number(rows)} lignes de données ; {number(entry['size_bytes'])} octets.\n\\par SHA-256 : \\texttt{{{sha}}}.\n"
provenance+=r'''
Le rapport qualité couvre aussi avril--juin ; les effectifs utilisés ici sont
ceux des trois mois initiaux. Les empreintes de tous les fichiers, y compris
ceux réservés à F6 et E1--E3, restent dans le manifeste.
'''
text=r'''\section{Anomalies présentes et lignes justificatives}\label{ann:qualite}
Fréquences issues de \chemin{results/quality/quality_report.json}, calculées
\emph{par fichier entier}, indépendamment des profils. Elles peuvent se recouper.
Les huit exemples ont été comparés aux colonnes originales des Parquet et leurs
durées recalculées avec New York puis UTC. Le relevé de cette vérification est
\chemin{report/evidence-verification.json}. Une transition DST est une particularité
à traiter, pas nécessairement une erreur de données.

\begin{center}\small
\begin{tabular}{llrr}
\toprule
Mois & Indicateur & Fréquence & Part du fichier (\%)\\
\midrule
'''
for month,code,count,pct,record,duration,duplicate_of in annex:
 text+=f"{month} & \\code{{{code}}} & {number(count)} & {pct:.6f}".replace(".",",")+chr(92)*2+"\n"
text+=r'''\bottomrule
\end{tabular}\end{center}
'''
explanations={
'PICKUP_OUTSIDE_FILE_MONTH':"Le départ est en décembre alors que la ligne est publiée en janvier ; la requête doit utiliser la date réelle.",
'NON_POSITIVE_DURATION':"L'arrivée précède le départ : durée réelle $-364$ s, exclue du profil journey.",
'ZERO_DISTANCE':"Distance nulle malgré 19 s entre les deux heures : la ligne reste stockée mais n'alimente pas journey.",
'NEGATIVE_AMOUNT':"Le montant total négatif est exclu des profils analytiques. Le rapport qualité repère aussi cette ligne comme écriture d'annulation.",
'UNKNOWN_ZONE':"L'arrivée 265 ne désigne pas une zone précise de New York : exclusion du profil flows et donc journey.",
'EXACT_DUPLICATE':"Le rapport qualité signale cette ligne comme copie d'une ligne précédente du même fichier ; seule la copie est exclue. Les champs cités identifient l'exemple, le rapport JSON conserve toutes les colonnes.",
'DST_SPANNING':"Durée UTC de 10\\,891 s contre 14\\,491 s locales : une heure est retranchée. Le flag n'exclut pas automatiquement le trajet de journey.",
'DST_UNRESOLVED':"L'arrivée est à une heure inexistante le 10 mars. La durée exploitable est null et non les 85\\,132 s de différence locale affichées par l'ancien rapport de diagnostic."
}
for month,code,count,pct,r,duration,duplicate_of in annex:
 text+="\n\\paragraph{"+month+", ligne "+number(r["row_number"])+" --- \\code{"+code+"}}\n"
 text+=f"Départ : {r['tpep_pickup_datetime']} ; arrivée : {r['tpep_dropoff_datetime']}. "
 text+=f"Zones {r['PULocationID']} $\\to$ {r['DOLocationID']}, fournisseur {r['VendorID']}, distance {r['trip_distance']} miles, total {r['total_amount']}.\n"
 text+=explanations[code]+'\n'
 if duplicate_of is not None:text+='La ligne identique antérieure a été retrouvée à la position '+number(duplicate_of)+'.\n'
(ROOT/'report/annexes/provenance.tex').write_text(provenance)
(ROOT/'report/annexes/qualite.tex').write_text(text)
(ROOT/'report/evidence-verification.json').write_text(json.dumps({'verified':True,'method':'SHA-256 et effectifs Parquet contrôlés ; toutes les colonnes des exemples comparées aux originaux ; durées UTC recalculées','examples':proofs},ensure_ascii=False,indent=2)+'\n')
print('Sources et huit exemples vérifiés ; annexes générées.')
