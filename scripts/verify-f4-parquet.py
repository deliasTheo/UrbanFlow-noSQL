"""Recalcul indépendant F4 sur janvier complet, sans lecture MongoDB."""
import argparse
import json
from pathlib import Path
import urllib.request
import urllib.error
import numpy as np
import pandas as pd

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--api', default='http://127.0.0.1:8084')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
trips = pd.read_parquet(root / 'data/raw/yellow_tripdata_2024-01.parquet')
duplicate = trips.duplicated()

# Durée réelle : heures locales de New York converties en UTC avant la soustraction.
pickup_utc = trips.tpep_pickup_datetime.dt.tz_localize('America/New_York', ambiguous='NaT', nonexistent='NaT').dt.tz_convert('UTC')
dropoff_utc = trips.tpep_dropoff_datetime.dt.tz_localize('America/New_York', ambiguous='NaT', nonexistent='NaT').dt.tz_convert('UTC')
duration = (dropoff_utc - pickup_utc).dt.total_seconds()
distance = trips.trip_distance

# Profils activity et journey recalculés depuis les colonnes d'origine.
activity = ~((trips.total_amount < 0) | duplicate)
unresolved = (trips.tpep_pickup_datetime.notna() & pickup_utc.isna()) | (trips.tpep_dropoff_datetime.notna() & dropoff_utc.isna())
usable = activity & ~(
    trips.PULocationID.isin([264, 265])
    | trips.DOLocationID.isin([264, 265])
    | (duration <= 0)
    | (duration > 21600)
    | (distance == 0)
    | (distance > 100)
    | ((duration > 0) & (distance > 0) & (distance / (duration / 3600) > 80))
    | unresolved
)
trips['duration'] = duration
trips['usable'] = usable
trips['activity'] = activity


def get(query):
    with urllib.request.urlopen(args.api + '/api/journeys?' + query, timeout=60) as reply:
        return json.load(reply)


def close(actual, expected):
    """Deux valeurs absentes, ou deux nombres égaux aux arrondis près."""
    assert ((actual is None and expected is None)
            or (actual is not None and expected is not None and np.isclose(actual, expected, rtol=1e-12, atol=1e-9))), (actual, expected)


def metric(values, total, actual):
    """Compare les statistiques renvoyées pour une métrique (durée ou distance)."""
    values = np.asarray(values.dropna(), dtype=float)
    values = values[np.isfinite(values)]
    assert actual['count'] == len(values) and actual['missing'] == total - len(values)
    if not len(values):
        assert actual['median'] is None and actual['mean'] is None
        return
    q25, median, q75, p90 = np.quantile(values, [.25, .5, .75, .9], method='linear')
    iqr = q75 - q25
    for key, value in [
        ('min', values.min()),
        ('q25', q25),
        ('median', median),
        ('q75', q75),
        ('p90', p90),
        ('max', values.max()),
        ('mean', values.mean()),
        ('populationStdDev', values.std(ddof=0)),
        ('iqr', iqr),
    ]:
        close(actual[key], value)
    assert actual['iqrOutliers'] == int(((values < q25 - 1.5 * iqr) | (values > q75 + 1.5 * iqr)).sum())


def stats(frame, actual):
    assert actual['records'] == len(frame)
    metric(frame.duration, len(frame), actual['durationSeconds'])
    metric(frame.trip_distance, len(frame), actual['distanceMiles'])


checks = []
for origin, destination in [(132, 161), (161, 236), (181, 89)]:
    response = get(
        f'originId={origin}&destinationId={destination}&from=2024-01-15&to=2024-02-01'
        f'&referenceFrom=2024-01-01&referenceTo=2024-01-15'
    )
    selected = trips[(trips.PULocationID == origin) & (trips.DOLocationID == destination)]
    strata = {}
    for label, start, end in [('reference', '2024-01-01', '2024-01-15'), ('current', '2024-01-15', '2024-02-01')]:
        frame = selected[
            (selected.tpep_pickup_datetime >= pd.Timestamp(start))
            & (selected.tpep_pickup_datetime < pd.Timestamp(end))
        ]
        period = response[label]
        usable_trips = frame[frame.usable].copy()
        unreliable_trips = frame[frame.activity & ~frame.usable]
        assert (
            period['raw'] == len(frame)
            and period['retained'] == len(usable_trips)
            and period['lessReliable'] == len(unreliable_trips)
            and period['activityExcluded'] == int((~frame.activity).sum())
        )
        stats(usable_trips, period['usable'])
        stats(unreliable_trips, period['unreliable'])

        def stratum_key(trip):
            """Strate d'un trajet : semaine ou week-end, créneau de 6 h, classe de distance."""
            miles = (
                'missing' if not np.isfinite(trip.trip_distance)
                else '0-2' if trip.trip_distance < 2
                else '2-5' if trip.trip_distance < 5
                else '5-10' if trip.trip_distance < 10
                else '10+'
            )
            return (
                ('weekend' if trip.tpep_pickup_datetime.weekday() >= 5 else 'weekday')
                + '_h' + str(trip.tpep_pickup_datetime.hour // 6 * 6) + '_mi' + miles
            )

        usable_trips['stratum'] = usable_trips.apply(stratum_key, axis=1) if len(usable_trips) else pd.Series(dtype=str)
        strata[label] = {key: group for key, group in usable_trips.groupby('stratum')}
        assert [stratum['key'] for stratum in period['strata']] == sorted(strata[label])
        for stratum in period['strata']:
            stats(strata[label][stratum['key']], stratum['stats'])
        assert sum(source['retained'] for source in period['sources']) == len(usable_trips)

    # Moyennes standardisées : mêmes poids de référence, strates assez fournies des deux côtés.
    common_keys = [
        key for key in strata['reference'].keys() & strata['current'].keys()
        if len(strata['reference'][key].duration.dropna()) >= 30 and len(strata['current'][key].duration.dropna()) >= 30
    ]
    assert response['comparison']['commonStrata'] == len(common_keys)
    if common_keys:
        total = sum(len(strata['reference'][key]) for key in common_keys)
        reference_mean = sum(len(strata['reference'][key]) / total * strata['reference'][key].duration.mean() for key in common_keys)
        current_mean = sum(len(strata['reference'][key]) / total * strata['current'][key].duration.mean() for key in common_keys)
        close(response['comparison']['standardizedDurationDifferenceSeconds'], current_mean - reference_mean)
    checks.append({
        'origin': origin,
        'destination': destination,
        'referenceRetained': response['reference']['retained'],
        'currentRetained': response['current']['retained'],
        'status': response['comparison']['status'],
    })

# Cas sans effectif et couverture manquante, sans fausse comparaison concluante.
result = get('originId=181&destinationId=89&from=2024-02-01&to=2024-02-02&referenceFrom=2024-01-01&referenceTo=2024-01-15')
assert result['comparison']['status'] == 'SOURCE_MONTH_MISSING' and result['comparison']['standardizedDurationDifferenceSeconds'] is None

# Entrées invalides.
for query, status in [
    ('originId=9999&destinationId=161&from=2024-01-15&to=2024-02-01&referenceFrom=2024-01-01&referenceTo=2024-01-15', 404),
    ('originId=132&destinationId=161&from=2024-01-15&to=2024-02-01&referenceFrom=2024-01-01&referenceTo=2024-01-16', 400),
    ('originId=132&destinationId=161&from=2024-01-15&to=2024-02-01&referenceFrom=2024-01-01&referenceTo=2024-01-15&minTrips=1', 400),
]:
    try:
        get(query)
        raise AssertionError('Erreur attendue')
    except urllib.error.HTTPError as error:
        assert error.code == status

print(json.dumps({'verified': True, 'sourceRows': len(trips), 'checks': checks, 'errorsAndCoverage': True}, indent=2))
