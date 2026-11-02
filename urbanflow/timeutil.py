"""Conversion des horodatages locaux TLC et calcul des durées.

Les horodatages TLC sont en heure locale de New York sans indication de
fuseau. Deux cas posent problème lors des changements d'heure :

* passage à l'heure d'été (2e dimanche de mars, 2024-03-10) : les heures
  entre 02:00 et 03:00 n'existent pas ;
* retour à l'heure d'hiver (1er dimanche de novembre, 2024-11-03) : les
  heures entre 01:00 et 02:00 existent deux fois et sont ambiguës.

Une durée calculée par simple soustraction des heures locales est fausse
d'une heure pour tout trajet qui chevauche une transition. On convertit donc
chaque horodatage en UTC avant de soustraire. Lorsque la conversion est
impossible (heure inexistante ou ambiguë), on se rabat sur la différence
locale et le trajet est signalé comme incertain.
"""

import numpy as np
import pandas as pd

from urbanflow.config import LOCAL_TZ


def localize(local: pd.Series) -> pd.DataFrame:
    """Convertit une série d'heures locales naïves en UTC.

    Retourne un DataFrame avec la colonne `utc` (NaT si non convertible) et
    les indicateurs booléens `nonexistent` et `ambiguous`.
    """
    # Chaque appel n'invalide qu'un seul des deux cas, ce qui permet de les distinguer.
    as_ambiguous_nat = local.dt.tz_localize(LOCAL_TZ, ambiguous="NaT", nonexistent="shift_forward")
    as_nonexistent_nat = local.dt.tz_localize(
        LOCAL_TZ, ambiguous=np.ones(len(local), dtype=bool), nonexistent="NaT"
    )
    ambiguous = as_ambiguous_nat.isna() & local.notna()
    nonexistent = as_nonexistent_nat.isna() & local.notna()

    utc = local.dt.tz_localize(LOCAL_TZ, ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")
    return pd.DataFrame({"utc": utc, "nonexistent": nonexistent, "ambiguous": ambiguous})


def trip_durations(pickup: pd.Series, dropoff: pd.Series) -> pd.DataFrame:
    """Durées des trajets en secondes.

    Colonnes retournées :
      duration_s        durée réelle (via UTC) si les deux heures sont convertibles,
                        différence locale sinon ;
      naive_duration_s  différence brute des heures locales ;
      dst_unresolved    au moins une des deux heures est inexistante ou ambiguë ;
      dst_corrected     la durée réelle diffère de la durée locale (trajet à cheval
                        sur un changement d'heure).
    """
    pu = localize(pickup)
    do = localize(dropoff)

    naive = (dropoff - pickup).dt.total_seconds()
    real = (do["utc"] - pu["utc"]).dt.total_seconds()
    unresolved = pu["nonexistent"] | pu["ambiguous"] | do["nonexistent"] | do["ambiguous"]

    duration = real.where(~unresolved, naive)
    return pd.DataFrame({
        "duration_s": duration,
        "naive_duration_s": naive,
        "dst_unresolved": unresolved,
        "dst_corrected": ~unresolved & (duration != naive),
    })
