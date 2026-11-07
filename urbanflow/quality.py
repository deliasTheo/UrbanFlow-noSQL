"""Règles de qualité des trajets TLC.

Ce module est la référence unique pour deux choses :

1. le catalogue des anomalies : chaque règle produit un indicateur booléen
   par trajet ;
2. les profils d'utilisation : pour chaque famille d'analyses, la liste des
   anomalies qui rendent un trajet inutilisable.

Les anomalies sont signalées, jamais supprimées : les trajets bruts sont
conservés tels quels et chaque service applique le profil qui le concerne.
Le même code sert à l'ingestion, ce qui garantit que le rapport de qualité
et la base appliquent exactement les mêmes règles.

Règle d'affectation temporelle : un trajet appartient à la période qui
contient son heure de prise en charge (heure locale), quel que soit le
fichier mensuel dont il provient.
"""

from dataclasses import dataclass

import pandas as pd

from urbanflow.config import UNKNOWN_ZONE_IDS
from urbanflow.timeutil import trip_durations

# Seuils de plausibilité. Ils sont volontairement larges : on cherche à écarter
# les erreurs manifestes, pas à définir ce qu'est un trajet « normal ».
MAX_DURATION_S = 6 * 3600
MAX_DISTANCE_MI = 100.0
MAX_SPEED_MPH = 80.0

# Champs qui identifient un trajet physique (cf. dictionnaire TLC) : une écriture
# d'annulation reprend ces valeurs à l'identique avec des montants négatifs.
TRIP_KEY = ["VendorID", "tpep_pickup_datetime", "tpep_dropoff_datetime", "PULocationID", "DOLocationID"]


@dataclass(frozen=True)
class Anomaly:
    code: str
    description: str


ANOMALIES = [
    Anomaly("PICKUP_OUTSIDE_FILE_MONTH", "heure de prise en charge hors du mois du fichier"),
    Anomaly("NON_POSITIVE_DURATION", "durée nulle ou négative"),
    Anomaly("EXCESSIVE_DURATION", f"durée supérieure à {MAX_DURATION_S // 3600} h"),
    Anomaly("ZERO_DISTANCE", "distance nulle"),
    Anomaly("IMPLAUSIBLE_DISTANCE", f"distance supérieure à {MAX_DISTANCE_MI:g} miles"),
    Anomaly("IMPLAUSIBLE_SPEED", f"vitesse moyenne supérieure à {MAX_SPEED_MPH:g} mph"),
    Anomaly("NEGATIVE_AMOUNT", "montant total négatif"),
    Anomaly("REVERSAL_RECORD", "écriture d'annulation : montant négatif avec un trajet d'origine identique"),
    Anomaly("REVERSED_ORIGINAL", "trajet d'origine ayant fait l'objet d'une annulation"),
    Anomaly("UNKNOWN_ZONE", "zone de départ ou d'arrivée inconnue ou hors de la ville (264/265)"),
    Anomaly("EXACT_DUPLICATE", "ligne strictement identique à une ligne précédente du même fichier"),
    Anomaly("MISSING_PASSENGER_INFO", "passenger_count, RatecodeID et suppléments absents"),
    Anomaly("DST_SPANNING", "trajet à cheval sur un changement d'heure (durée corrigée)"),
    Anomaly("DST_UNRESOLVED", "heure inexistante ou ambiguë à cause d'un changement d'heure"),
]
ANOMALY_CODES = [a.code for a in ANOMALIES]


@dataclass(frozen=True)
class Profile:
    name: str
    services: str
    excluded: tuple[str, ...]


# Un profil hérite des exclusions du précédent : chaque analyse est plus
# exigeante que celle qui la précède.
_ACTIVITY = ("NEGATIVE_AMOUNT", "EXACT_DUPLICATE")
_FLOWS = _ACTIVITY + ("UNKNOWN_ZONE",)
_JOURNEY = _FLOWS + (
    "NON_POSITIVE_DURATION", "EXCESSIVE_DURATION", "ZERO_DISTANCE",
    "IMPLAUSIBLE_DISTANCE", "IMPLAUSIBLE_SPEED", "DST_UNRESOLVED",
)

PROFILES = [
    Profile("activity", "F1, F3 (comptages par zone et par période)", _ACTIVITY),
    Profile("flows", "F2, F5 (flux origine-destination)", _FLOWS),
    Profile("journey", "F4 (durées, distances, vitesses)", _JOURNEY),
]


def _reversal_flags(trips: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Repère les paires (trajet d'origine, écriture d'annulation).

    Une annulation partage la clé du trajet et porte un montant total opposé.
    On compare sur la valeur absolue arrondie au centime pour éviter les
    écarts d'arrondi en virgule flottante.
    """
    keys = trips[TRIP_KEY].copy()
    keys["abs_total"] = trips["total_amount"].abs().round(2)
    cols = TRIP_KEY + ["abs_total"]

    negative = trips["total_amount"] < 0
    positive = trips["total_amount"] > 0
    paired = (
        keys[negative].drop_duplicates()
        .merge(keys[positive].drop_duplicates(), on=cols)
        .assign(_paired=True)
    )
    # Une jointure à gauche conserve l'ordre des lignes de `keys`.
    in_pair = keys.merge(paired, on=cols, how="left")["_paired"].notna().to_numpy()
    return pd.Series(negative.to_numpy() & in_pair, index=trips.index), \
        pd.Series(positive.to_numpy() & in_pair, index=trips.index)


def flag_trips(trips: pd.DataFrame, file_month: str | None = None) -> pd.DataFrame:
    """Calcule les indicateurs d'anomalie et la durée réelle de chaque trajet.

    `trips` contient les colonnes brutes d'un fichier TLC ; `file_month`
    (AAAA-MM) est le mois annoncé par le nom du fichier.
    Retourne un DataFrame aligné sur `trips` avec une colonne booléenne par
    code d'anomalie, plus `duration_s` et `naive_duration_s`.
    """
    pickup = trips["tpep_pickup_datetime"]
    distance = trips["trip_distance"]
    durations = trip_durations(pickup, trips["tpep_dropoff_datetime"])
    duration = durations["duration_s"]

    flags = pd.DataFrame(index=trips.index)

    if file_month is None:
        flags["PICKUP_OUTSIDE_FILE_MONTH"] = False
    else:
        start = pd.Timestamp(f"{file_month}-01")
        end = start + pd.offsets.MonthBegin(1)
        flags["PICKUP_OUTSIDE_FILE_MONTH"] = (pickup < start) | (pickup >= end)

    flags["NON_POSITIVE_DURATION"] = duration <= 0
    flags["EXCESSIVE_DURATION"] = duration > MAX_DURATION_S
    flags["ZERO_DISTANCE"] = distance == 0
    flags["IMPLAUSIBLE_DISTANCE"] = distance > MAX_DISTANCE_MI

    speed_mph = distance / (duration / 3600)
    flags["IMPLAUSIBLE_SPEED"] = (duration > 0) & (distance > 0) & (speed_mph > MAX_SPEED_MPH)

    flags["NEGATIVE_AMOUNT"] = trips["total_amount"] < 0
    flags["REVERSAL_RECORD"], flags["REVERSED_ORIGINAL"] = _reversal_flags(trips)

    flags["UNKNOWN_ZONE"] = (
        trips["PULocationID"].isin(UNKNOWN_ZONE_IDS) | trips["DOLocationID"].isin(UNKNOWN_ZONE_IDS)
    )
    # keep="first" : la première occurrence reste exploitable, seules les copies sont signalées.
    flags["EXACT_DUPLICATE"] = trips.duplicated(keep="first")
    flags["MISSING_PASSENGER_INFO"] = trips["passenger_count"].isna()
    flags["DST_SPANNING"] = durations["dst_corrected"]
    flags["DST_UNRESOLVED"] = durations["dst_unresolved"]

    flags["duration_s"] = duration
    flags["naive_duration_s"] = durations["naive_duration_s"]
    return flags


def usable_mask(flags: pd.DataFrame, profile: Profile) -> pd.Series:
    """Trajets utilisables pour un profil donné."""
    return ~flags[list(profile.excluded)].any(axis=1)
