"""Rapport de qualité des fichiers sources.

Pour chaque fichier de trajets du manifeste, le rapport donne :
  - le nombre de lignes et la répartition des trajets par mois de prise en
    charge (règle d'affectation temporelle) ;
  - la couverture spatiale (zones observées, prises en charge par borough) ;
  - la fréquence de chaque anomalie, avec un enregistrement concret
    identifié par son numéro de ligne dans le fichier (base 0) ;
  - l'effet de chaque profil de filtrage sur le nombre de trajets utilisables.

Sorties : results/quality/quality_report.json et quality_report.md.

Usage :
    python -m urbanflow.quality_report
    python -m urbanflow.quality_report --files yellow_tripdata_2024-03.parquet
"""

import argparse
import json
import re
from pathlib import Path

import pandas as pd

from urbanflow import config
from urbanflow.quality import ANOMALIES, ANOMALY_CODES, PROFILES, TRIP_KEY, flag_trips, usable_mask

OUTPUT_DIR = config.RESULTS_DIR / "quality"

# Anomalies qui vont nécessairement ensemble et ne doivent pas disqualifier
# un exemple l'une pour l'autre.
RELATED_ANOMALIES = [{"NEGATIVE_AMOUNT", "REVERSAL_RECORD", "REVERSED_ORIGINAL"}]


def _jsonable(value):
    if value is None or (isinstance(value, float) and pd.isna(value)) or value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat(sep=" ")
    if hasattr(value, "item"):  # scalaires numpy
        return value.item()
    return value


def _record(trips: pd.DataFrame, flags: pd.DataFrame, row: int) -> dict:
    """Enregistrement brut d'une ligne, complété par sa durée calculée."""
    rec = {"row_number": int(row)}
    rec.update({col: _jsonable(trips.at[row, col]) for col in trips.columns})
    rec["duration_s"] = _jsonable(flags.at[row, "duration_s"])
    rec["naive_duration_s"] = _jsonable(flags.at[row, "naive_duration_s"])
    return rec


def _example(trips: pd.DataFrame, flags: pd.DataFrame, code: str) -> dict | None:
    """Premier enregistrement présentant l'anomalie `code`.

    On privilégie une ligne qui ne présente aucune autre anomalie, pour que
    l'exemple illustre un seul problème à la fois.
    """
    hit = flags[code]
    if not hit.any():
        return None
    family = next((f for f in RELATED_ANOMALIES if code in f), {code})
    others = flags[[c for c in ANOMALY_CODES if c not in family]].any(axis=1)
    clean = hit & ~others
    first = flags.index[clean][0] if clean.any() else flags.index[hit][0]
    example = {"record": _record(trips, flags, first)}

    # Pour une annulation, on joint le trajet d'origine afin de montrer la paire.
    if code in ("REVERSAL_RECORD", "REVERSED_ORIGINAL"):
        same_trip = (trips[TRIP_KEY] == trips.loc[first, TRIP_KEY]).all(axis=1)
        partners = trips.index[same_trip & (trips.index != first)]
        example["paired_rows"] = [_record(trips, flags, r) for r in partners[:3]]
    return example


def analyse_file(path: Path, zones: pd.DataFrame) -> dict:
    match = re.search(r"(\d{4}-\d{2})", path.name)
    file_month = match.group(1) if match else None

    trips = pd.read_parquet(path)
    flags = flag_trips(trips, file_month)
    n = len(trips)

    pickup_month = trips["tpep_pickup_datetime"].dt.strftime("%Y-%m")
    # La zone 265 n'a pas de borough : on reprend son libellé ("Outside of NYC").
    label = zones.set_index("LocationID")
    label = label["Borough"].fillna(label["Zone"])
    borough = trips["PULocationID"].map(label).fillna("(zone absente du référentiel)")

    anomalies = {}
    for anomaly in ANOMALIES:
        count = int(flags[anomaly.code].sum())
        anomalies[anomaly.code] = {
            "description": anomaly.description,
            "count": count,
            "share": count / n,
            "example": _example(trips, flags, anomaly.code),
        }

    profiles = {}
    for profile in PROFILES:
        usable = int(usable_mask(flags, profile).sum())
        profiles[profile.name] = {
            "services": profile.services,
            "excluded_anomalies": list(profile.excluded),
            "usable": usable,
            "excluded": n - usable,
            "excluded_share": (n - usable) / n,
        }

    return {
        "file": path.name,
        "file_month": file_month,
        "num_rows": n,
        "trips_by_pickup_month": pickup_month.value_counts().sort_index().to_dict(),
        "spatial_coverage": {
            "distinct_pickup_zones": int(trips["PULocationID"].nunique()),
            "distinct_dropoff_zones": int(trips["DOLocationID"].nunique()),
            "pickups_by_borough": borough.value_counts().to_dict(),
        },
        "anomalies": anomalies,
        "profiles": profiles,
    }


def _pct(x: float) -> str:
    return f"{100 * x:.2f} %"


def to_markdown(reports: list[dict]) -> str:
    files = [r["file"] for r in reports]
    short = [r["file_month"] or r["file"] for r in reports]
    lines = ["# Rapport de qualité des données TLC", ""]

    lines += ["## Fichiers et affectation temporelle", "",
              "Règle : un trajet est affecté au mois de son heure de prise en charge (heure locale).", "",
              "| Fichier | Lignes | Dans le mois du fichier | Hors du mois |",
              "|---|---:|---:|---:|"]
    for r in reports:
        inside = r["trips_by_pickup_month"].get(r["file_month"], 0)
        lines.append(f"| {r['file']} | {r['num_rows']:,} | {inside:,} | {r['num_rows'] - inside:,} |")

    boroughs = sorted({b for r in reports for b in r["spatial_coverage"]["pickups_by_borough"]})
    lines += ["", "## Couverture spatiale (prises en charge par borough)", "",
              "| Mois | Zones de départ | Zones d'arrivée | " + " | ".join(boroughs) + " |",
              "|---|---:|---:|" + "---:|" * len(boroughs)]
    for r in reports:
        cov = r["spatial_coverage"]
        cells = [f"{cov['pickups_by_borough'].get(b, 0):,}" for b in boroughs]
        lines.append(f"| {r['file_month']} | {cov['distinct_pickup_zones']} | {cov['distinct_dropoff_zones']} | "
                     + " | ".join(cells) + " |")

    lines += ["", "## Fréquence des anomalies", "",
              "| Code | Description | " + " | ".join(short) + " |",
              "|---|---|" + "---:|" * len(reports)]
    for anomaly in ANOMALIES:
        cells = [f"{r['anomalies'][anomaly.code]['count']:,} ({_pct(r['anomalies'][anomaly.code]['share'])})"
                 for r in reports]
        lines.append(f"| `{anomaly.code}` | {anomaly.description} | " + " | ".join(cells) + " |")

    lines += ["", "## Effet du filtrage par profil", ""]
    for profile in PROFILES:
        lines.append(f"- **{profile.name}** ({profile.services}) : exclut "
                     + ", ".join(f"`{c}`" for c in profile.excluded))
    lines += ["", "| Profil | " + " | ".join(short) + " |", "|---|" + "---:|" * len(reports)]
    for profile in PROFILES:
        cells = [f"{r['profiles'][profile.name]['usable']:,} (−{_pct(r['profiles'][profile.name]['excluded_share'])})"
                 for r in reports]
        lines.append(f"| {profile.name} | " + " | ".join(cells) + " |")

    lines += ["", "## Exemples concrets", "",
              "Numéro de ligne en base 0 dans le fichier Parquet d'origine.", ""]
    for anomaly in ANOMALIES:
        source = next((r for r in reports if r["anomalies"][anomaly.code]["example"]), None)
        lines.append(f"### `{anomaly.code}` — {anomaly.description}")
        if source is None:
            lines += ["", f"Aucune occurrence dans : {', '.join(files)}.", ""]
            continue
        example = source["anomalies"][anomaly.code]["example"]
        lines += ["", f"Fichier `{source['file']}` :", "", "```json",
                  json.dumps(example, indent=2, ensure_ascii=False), "```", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--files", nargs="+", help="fichiers de data/raw à analyser (défaut : tous ceux du manifeste)")
    args = parser.parse_args()

    if args.files:
        names = args.files
    else:
        manifest = json.loads(config.MANIFEST_PATH.read_text(encoding="utf-8"))
        names = [name for name in manifest["files"] if name.endswith(".parquet")]

    zones = pd.read_csv(config.RAW_DIR / config.ZONE_LOOKUP_FILE)
    reports = []
    for name in sorted(names):
        print(f"Analyse de {name}…")
        reports.append(analyse_file(config.RAW_DIR / name, zones))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "quality_report.json").write_text(
        json.dumps(reports, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUTPUT_DIR / "quality_report.md").write_text(to_markdown(reports) + "\n", encoding="utf-8")
    print(f"Rapport écrit dans {OUTPUT_DIR.relative_to(config.PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
