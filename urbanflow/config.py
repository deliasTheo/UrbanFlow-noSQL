"""Paramètres globaux du projet : chemins, sources et périmètre d'étude.

Le périmètre (mois et zone d'étude) est provisoire tant qu'il n'a pas été
enregistré auprès de l'enseignante ; il suffit de le modifier ici.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
MANIFEST_PATH = DATA_DIR / "manifest.json"
RESULTS_DIR = PROJECT_ROOT / "results"

# Sources officielles TLC
TRIP_URL_TEMPLATE = "https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_{month}.parquet"
ZONE_LOOKUP_URL = "https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv"
ZONE_LOOKUP_FILE = "taxi_zone_lookup.csv"

# Les horodatages TLC sont des heures locales sans fuseau.
LOCAL_TZ = "America/New_York"

# Périmètre d'étude (provisoire)
STUDY_MONTHS = ["2024-01", "2024-02", "2024-03"]  # mars : passage à l'heure d'été
UPDATE_MONTH = "2024-04"                          # mois réservé au service F6
FOCUS_BOROUGH = "Manhattan"

# Zones TLC qui ne désignent pas un lieu précis.
UNKNOWN_ZONE_IDS = (264, 265)  # 264 = "Unknown", 265 = "Outside of NYC"


def trip_file_name(month: str) -> str:
    """Nom du fichier TLC pour un mois au format AAAA-MM."""
    return f"yellow_tripdata_{month}.parquet"
