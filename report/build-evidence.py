"""Vérifie les exemples d'anomalies dans les fichiers TLC, puis génère l'annexe LaTeX.

Le script contrôle les sources (taille, SHA-256, nombre de lignes), compare chaque
exemple à sa ligne d'origine dans le Parquet et recalcule sa durée. Une différence
l'arrête : l'annexe n'est écrite que si tout est bon.

Il ne lance aucune expérience et ne lit pas MongoDB.

Usage, depuis la racine du dépôt :
    python report/build-evidence.py
"""

import hashlib
import json
import math
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data/raw"
ANNEX_PATH = ROOT / "report/annexes/qualite.tex"
PROOF_PATH = ROOT / "report/evidence-verification.json"

TIMEZONE = "America/New_York"
SOURCE_FILES = [f"yellow_tripdata_2024-0{month}.parquet" for month in range(1, 7)] + ["taxi_zone_lookup.csv"]
ZONES_IN_LOOKUP = 265

# Les anomalies présentées dans l'annexe, avec le mois de leur exemple.
SELECTED_ANOMALIES = {
    "2024-01": ["PICKUP_OUTSIDE_FILE_MONTH", "NON_POSITIVE_DURATION", "ZERO_DISTANCE", "NEGATIVE_AMOUNT", "UNKNOWN_ZONE"],
    "2024-02": ["EXACT_DUPLICATE"],
    "2024-03": ["DST_SPANNING", "DST_UNRESOLVED"],
}

# Ces champs sont calculés par le rapport qualité : ils n'existent pas dans le Parquet.
COMPUTED_FIELDS = ["row_number", "duration_s", "naive_duration_s"]

EXPLANATIONS = {
    "PICKUP_OUTSIDE_FILE_MONTH": "Le départ est en décembre alors que la ligne est publiée en janvier ; la requête doit utiliser la date réelle.",
    "NON_POSITIVE_DURATION": "L'arrivée précède le départ : durée réelle $-364$ s, exclue du profil journey.",
    "ZERO_DISTANCE": "Distance nulle malgré 19 s entre les deux heures : la ligne reste stockée mais n'alimente pas journey.",
    "NEGATIVE_AMOUNT": "Le montant total négatif est exclu des profils analytiques. Le rapport qualité repère aussi cette ligne comme écriture d'annulation.",
    "UNKNOWN_ZONE": "L'arrivée 265 ne désigne pas une zone précise de New York : exclusion du profil flows et donc journey.",
    "EXACT_DUPLICATE": "Le rapport qualité signale cette ligne comme copie d'une ligne précédente du même fichier ; seule la copie est exclue. Les champs cités identifient l'exemple, le rapport JSON conserve toutes les colonnes.",
    "DST_SPANNING": "Durée UTC de 10\\,891 s contre 14\\,491 s locales : une heure est retranchée. Le flag n'exclut pas automatiquement le trajet de journey.",
    "DST_UNRESOLVED": "L'arrivée est à une heure inexistante le 10 mars. La durée exploitable est null et non les 85\\,132 s de différence locale.",
}

ANNEX_INTRO = r"""\section{Anomalies présentes et lignes justificatives}\label{ann:qualite}
Fréquences issues de \chemin{results/quality/quality_report.json}, calculées
\emph{par fichier entier}, indépendamment des profils. Elles peuvent se recouper.
Nous avons comparé les huit exemples aux colonnes originales des Parquet et recalculé leurs durées avec New York puis UTC. Le relevé de cette vérification est
\chemin{report/evidence-verification.json}. Une transition DST est une particularité
à traiter, pas nécessairement une erreur de données. Les numéros de ligne sont en base zéro.

\begin{center}\small
\begin{tabular}{llrr}
\toprule
Mois & Indicateur & Fréquence & Part du fichier (\%)\\
\midrule
"""

TABLE_END = r"""\bottomrule
\end{tabular}\end{center}
"""


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def latex_number(value):
    """Écrit 1234567 sous la forme 1\\,234\\,567."""
    return f"{value:,}".replace(",", r"\,")


def sha256_of(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def check_source_files(manifest):
    """Chaque fichier doit correspondre exactement à ce que dit le manifeste."""
    for name in SOURCE_FILES:
        path = RAW_DIR / name
        entry = manifest[name]
        assert path.stat().st_size == entry["size_bytes"], name
        assert sha256_of(path) == entry["sha256"], name
        if name.endswith(".csv"):
            assert len(pd.read_csv(path)) == ZONES_IN_LOOKUP, name
        else:
            assert pq.ParquetFile(path).metadata.num_rows == entry["num_rows"], name


def row_group_starts(parquet):
    """Numéro de la première ligne de chaque groupe du fichier Parquet."""
    starts = []
    next_start = 0
    for group in range(parquet.num_row_groups):
        starts.append(next_start)
        next_start += parquet.metadata.row_group(group).num_rows
    return starts


def check_fields(record, original, where):
    """Compare les champs de l'exemple à la ligne lue dans le Parquet."""
    for field, expected in record.items():
        if field in COMPUTED_FIELDS:
            continue
        actual = original[field]
        location = (*where, field)
        if isinstance(actual, pd.Timestamp):
            assert actual == pd.Timestamp(expected), location
        elif expected is None:
            assert pd.isna(actual), location
        elif isinstance(expected, (int, float)):
            assert math.isclose(float(actual), expected, rel_tol=1e-12, abs_tol=1e-12), location
        else:
            assert actual == expected, location


def real_duration(original):
    """Durée en secondes via UTC. None si une heure est inexistante ou ambiguë."""
    pickup = original["tpep_pickup_datetime"].tz_localize(TIMEZONE, ambiguous="NaT", nonexistent="NaT")
    dropoff = original["tpep_dropoff_datetime"].tz_localize(TIMEZONE, ambiguous="NaT", nonexistent="NaT")
    if pd.isna(pickup) or pd.isna(dropoff):
        return None
    return (dropoff.tz_convert("UTC") - pickup.tz_convert("UTC")).total_seconds()


def find_earlier_copy(parquet, starts, row, group, original):
    """Numéro de la première ligne identique placée avant `row` dans le fichier."""
    for candidate_group in range(group + 1):
        frame = parquet.read_row_group(candidate_group).to_pandas()
        lines_before_row = max(0, min(len(frame), row - starts[candidate_group]))
        earlier = frame.iloc[:lines_before_row]
        # Deux valeurs absentes comptent comme égales.
        same_row = (earlier.eq(original) | (earlier.isna() & original.isna())).all(axis=1)
        positions = same_row.to_numpy().nonzero()[0]
        if len(positions):
            return int(starts[candidate_group] + positions[0])
    raise AssertionError("Copie originale introuvable")


def check_example(parquet, starts, groups, entry, file_name, code, report):
    """Vérifie un exemple. Renvoie sa ligne pour l'annexe et sa preuve pour le JSON."""
    anomaly = report["anomalies"][code]
    record = anomaly["example"]["record"]
    row = record["row_number"]

    group = max(index for index, start in enumerate(starts) if start <= row)
    if group not in groups:
        groups[group] = parquet.read_row_group(group).to_pandas()
    original = groups[group].iloc[row - starts[group]]

    check_fields(record, original, (file_name, row))

    duration = real_duration(original)
    if code == "DST_UNRESOLVED":
        assert duration is None
    else:
        assert duration == record["duration_s"]

    duplicate_of = None
    if code == "EXACT_DUPLICATE":
        duplicate_of = find_earlier_copy(parquet, starts, row, group, original)

    proof = {
        "duplicateOfRow": duplicate_of,
        "file": file_name,
        "sha256": entry["sha256"],
        "row_number": row,
        "flag": code,
        "sourceFieldsMatch": True,
        "realDurationSeconds": duration,
    }
    annex_row = {
        "month": report["file_month"],
        "code": code,
        "count": anomaly["count"],
        "percent": 100 * anomaly["count"] / report["num_rows"],
        "record": record,
        "duplicate_of": duplicate_of,
    }
    return annex_row, proof


def check_examples(manifest, quality):
    annex_rows = []
    proofs = []
    for month, codes in SELECTED_ANOMALIES.items():
        file_name = f"yellow_tripdata_{month}.parquet"
        parquet = pq.ParquetFile(RAW_DIR / file_name)
        report = next(item for item in quality if item["file_month"] == month)
        starts = row_group_starts(parquet)
        groups = {}  # groupes déjà lus : plusieurs exemples peuvent tomber dans le même
        for code in codes:
            annex_row, proof = check_example(parquet, starts, groups, manifest[file_name], file_name, code, report)
            annex_rows.append(annex_row)
            proofs.append(proof)
    return annex_rows, proofs


def annex_text(rows):
    text = ANNEX_INTRO
    for row in rows:
        percent = f"{row['percent']:.6f}".replace(".", ",")
        text += f"{row['month']} & \\code{{{row['code']}}} & {latex_number(row['count'])} & {percent}\\\\\n"
    text += TABLE_END

    for row in rows:
        record = row["record"]
        text += f"\n\\paragraph{{{row['month']}, ligne {latex_number(record['row_number'])} --- \\code{{{row['code']}}}}}\n"
        text += f"Départ : {record['tpep_pickup_datetime']} ; arrivée : {record['tpep_dropoff_datetime']}. "
        text += (f"Zones {record['PULocationID']} $\\to$ {record['DOLocationID']}, fournisseur {record['VendorID']}, "
                 f"distance {record['trip_distance']} miles, total {record['total_amount']}.\n")
        text += EXPLANATIONS[row["code"]] + "\n"
        if row["duplicate_of"] is not None:
            text += f"La ligne identique antérieure se trouve à la position {latex_number(row['duplicate_of'])}.\n"
    return text


def main():
    manifest = read_json(ROOT / "data/manifest.json")["files"]
    quality = read_json(ROOT / "results/quality/quality_report.json")

    check_source_files(manifest)
    annex_rows, proofs = check_examples(manifest, quality)

    ANNEX_PATH.write_text(annex_text(annex_rows), encoding="utf-8")
    proof_file = {
        "verified": True,
        "method": "SHA-256 et effectifs Parquet contrôlés ; toutes les colonnes des exemples comparées aux originaux ; durées UTC recalculées",
        "examples": proofs,
    }
    PROOF_PATH.write_text(json.dumps(proof_file, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Sources et huit exemples vérifiés ; annexe générée.")


if __name__ == "__main__":
    main()
