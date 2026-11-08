"""Vérification indépendante de F3 sur janvier complet ; API sur base janvier seul."""
import argparse
import json
from pathlib import Path
import statistics
import urllib.request
import urllib.error
import pandas as pd

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--api', default='http://127.0.0.1:8083')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
trips = pd.read_parquet(root / 'data/raw/yellow_tripdata_2024-01.parquet')
# Profil activity recalculé directement depuis les colonnes d'origine.
trips['kept'] = ~((trips.total_amount < 0) | trips.duplicated())
zones = pd.read_csv(root / 'data/raw/taxi_zone_lookup.csv')
results = []


def get(query):
    with urllib.request.urlopen(args.api + '/api/unusual-activity?' + query, timeout=180) as reply:
        return json.load(reply)


for scope, direction, start, end in [
    ('zoneIds=132', 'pickup', 0, 24),
    ('borough=Brooklyn', 'pickup', 0, 24),
    ('zoneIds=132', 'dropoff', 8, 12),
]:
    response = get(
        f'{scope}&direction={direction}&from=2024-01-22&to=2024-02-01'
        f'&referenceFrom=2024-01-01&referenceTo=2024-01-22&startHour={start}&endHour={end}'
    )
    time = trips['tpep_' + direction + '_datetime']
    mask = (
        (time >= pd.Timestamp('2024-01-01'))
        & (time < pd.Timestamp('2024-02-01'))
        & (time.dt.hour >= start)
        & (time.dt.hour < end)
    )
    subset = trips.loc[mask, ['PULocationID', 'DOLocationID', 'kept']].copy()
    subset['date'] = time[mask].dt.strftime('%Y-%m-%d')
    field = 'PULocationID' if direction == 'pickup' else 'DOLocationID'
    grouped = subset.groupby([field, 'date']).kept.agg(['size', 'sum'])
    city = subset.groupby('date').kept.agg(['size', 'sum'])

    def counts(zone, date):
        if (zone, date) not in grouped.index:
            return {'raw': 0, 'retained': 0, 'excluded': 0}
        cell = grouped.loc[(zone, date)]
        return {'raw': int(cell['size']), 'retained': int(cell['sum']), 'excluded': int(cell['size'] - cell['sum'])}

    # Contrôle de couverture : le volume de toute la ville, jour par jour.
    for day in response['cityCoverage']:
        row = city.loc[day['date']]
        assert day['counts'] == {'raw': int(row['size']), 'retained': int(row['sum']), 'excluded': int(row['size'] - row['sum'])}

    for observation in response['observations']:
        zone = observation['zone']['id']
        date = observation['observed']['date']
        expected = counts(zone, date)
        assert observation['observed']['counts'] == expected

        # Références : mêmes jours de semaine, sans le 1er janvier ni le 15 (jours fériés).
        reference_dates = [
            day.strftime('%Y-%m-%d') for day in pd.date_range('2024-01-01', '2024-01-21')
            if day.weekday() == pd.Timestamp(date).weekday() and day.day not in [1, 15]
        ]
        assert [reference['date'] for reference in observation['references']] == reference_dates
        values = [counts(zone, day)['retained'] for day in reference_dates]
        for row in observation['references']:
            assert row['counts'] == counts(zone, row['date'])

        # Médiane, dispersion (MAD) et écarts, calculés comme dans le service.
        median = statistics.median(values)
        mad = statistics.median([abs(value - median) for value in values])
        assert observation['baselineMedian'] == median and observation['medianAbsoluteDeviation'] == mad
        expected_relative = None if median == 0 else (expected['retained'] - median) / median
        expected_score = None if mad == 0 else (expected['retained'] - median) / (1.4826 * mad)
        assert observation['relativeChange'] == expected_relative and observation['robustScore'] == expected_score

        city_median = statistics.median([int(city.loc[day, 'size']) for day in reference_dates])
        assert observation['cityRatio'] == int(city.loc[date, 'size']) / city_median
        assert ('CITY_VOLUME_SHIFT' in observation['warnings']) == (observation['cityRatio'] < 0.5 or observation['cityRatio'] > 2)
        assert (('HIGH_EXCLUSION_RATE' in observation['warnings'])
                == (expected['raw'] > 0 and expected['excluded'] / expected['raw'] > 0.2))

        status = 'INSUFFICIENT_REFERENCE' if len(reference_dates) < 3 else 'LOW_BASELINE' if median < 20 else 'USUAL'
        if status == 'USUAL':
            delta = expected['retained'] - median
            if abs(delta) >= 20 and abs(delta / median) >= 0.5 and (mad == 0 or abs(delta / (1.4826 * mad)) >= 3):
                status = 'UNUSUAL'
        assert observation['status'] == status, (zone, date, observation['status'], status)
        if status == 'UNUSUAL':
            assert observation['change'] == ('HIGHER' if expected['retained'] > median else 'LOWER')
        assert sum(source['counts']['retained'] for source in observation['observed']['sources']) == expected['retained']

    assert len(response['unusual']) == sum(item['status'] == 'UNUSUAL' for item in response['observations'])
    assert {day['date'] for day in response['excludedReferenceDays']} == {'2024-01-01', '2024-01-15'}
    results.append({
        'scope': scope,
        'direction': direction,
        'startHour': start,
        'endHour': end,
        'cells': len(response['observations']),
        'unusual': len(response['unusual']),
    })

# Exclusions calendaires de journées entières et couverture : aucun faux résultat normal.
for date, to, status in [
    ('2024-03-10', '2024-03-11', 'DST_DAY_EXCLUDED'),
    ('2024-11-03', '2024-11-04', 'DST_DAY_EXCLUDED'),
    ('2024-02-19', '2024-02-20', "HOLIDAY_EXCLUDED: Washington's Birthday"),
    ('2024-02-20', '2024-02-21', 'SOURCE_MONTH_MISSING'),
]:
    result = get(f'zoneIds=132&from={date}&to={to}&referenceFrom=2024-01-01&referenceTo=2024-01-22')
    assert result['observations'][0]['status'] == status and not result['unusual']

# Entrées invalides : référence qui chevauche la période, créneau inversé.
for query in [
    'zoneIds=132&from=2024-01-22&to=2024-02-01&referenceFrom=2024-01-01&referenceTo=2024-01-23',
    'zoneIds=132&from=2024-01-22&to=2024-02-01&referenceFrom=2024-01-01&referenceTo=2024-01-22&startHour=12&endHour=8',
]:
    try:
        get(query)
        raise AssertionError('400 attendu')
    except urllib.error.HTTPError as error:
        assert error.code == 400

print(json.dumps({'verified': True, 'sourceRows': len(trips), 'checks': results, 'calendarAndCoverageChecks': True}, indent=2))
