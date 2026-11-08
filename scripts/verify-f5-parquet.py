"""Recalcul indépendant F5 sur janvier complet, sans lire MongoDB."""
import argparse
import json
from pathlib import Path
import urllib.request
import urllib.error
import numpy as np
import pandas as pd

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--api', default='http://127.0.0.1:8086')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
trips = pd.read_parquet(root / 'data/raw/yellow_tripdata_2024-01.parquet')
# Profil flows recalculé directement depuis les colonnes d'origine.
trips['kept'] = ~((trips.total_amount < 0) | trips.duplicated() | trips.PULocationID.isin([264, 265]) | trips.DOLocationID.isin([264, 265]))
trips = trips.loc[
    (trips.tpep_pickup_datetime >= pd.Timestamp('2024-01-01')) & (trips.tpep_pickup_datetime < pd.Timestamp('2024-01-29')),
    ['PULocationID', 'DOLocationID', 'tpep_pickup_datetime', 'kept'],
].copy()
# Une semaine commence le lundi : on enlève le numéro du jour à la date.
trips['week'] = (
    trips.tpep_pickup_datetime.dt.normalize() - pd.to_timedelta(trips.tpep_pickup_datetime.dt.weekday, unit='D')
).dt.strftime('%Y-%m-%d')
zones = pd.read_csv(root / 'data/raw/taxi_zone_lookup.csv')
base = 'from=2024-01-22&to=2024-01-29&referenceFrom=2024-01-15&referenceTo=2024-01-22&baselineFrom=2024-01-01&baselineTo=2024-01-22'


def get(query):
    with urllib.request.urlopen(args.api + '/api/flow-changes?' + query, timeout=150) as reply:
        return json.load(reply)


def close(actual, expected):
    assert np.isclose(actual, expected, rtol=1e-12, atol=1e-12), (actual, expected)


checks = []
for scope, zone_ids in [
    ('zoneIds=132', [132]),
    ('borough=Brooklyn', zones.loc[zones.Borough == 'Brooklyn', 'LocationID'].tolist()),
    ('', zones.LocationID.tolist()),
]:
    response = get((scope + '&' if scope else '') + base)
    area_trips = trips[trips.PULocationID.isin(zone_ids)]
    counts = area_trips.groupby(['PULocationID', 'DOLocationID', 'week']).kept.agg(['size', 'sum'])
    weekly = area_trips.groupby('week').kept.agg(['size', 'sum'])

    def retained_count(origin, destination, week):
        return int(counts.loc[(origin, destination, week), 'sum']) if (origin, destination, week) in counts.index else 0

    def raw_count(origin, destination, week):
        return int(counts.loc[(origin, destination, week), 'size']) if (origin, destination, week) in counts.index else 0

    baseline_weeks = ['2024-01-01', '2024-01-08', '2024-01-15']
    reference_week = '2024-01-15'
    current_week = '2024-01-22'
    for label, week in [('reference', reference_week), ('current', current_week)]:
        assert response[label]['counts'] == {
            'raw': int(weekly.loc[week, 'size']),
            'retained': int(weekly.loc[week, 'sum']),
            'excluded': int(weekly.loc[week, 'size'] - weekly.loc[week, 'sum']),
        }

    # Recalcul de chaque flux : parts, variation hebdomadaire habituelle, ratio et statut.
    expected = {}
    for origin, destination in counts.index.droplevel(2).unique():
        reference_trips, current_trips = (
            retained_count(origin, destination, reference_week),
            retained_count(origin, destination, current_week),
        )
        if not reference_trips and not current_trips:
            continue
        reference_share, current_share = (
            reference_trips / weekly.loc[reference_week, 'sum'],
            current_trips / weekly.loc[current_week, 'sum'],
        )
        delta = current_share - reference_share
        shares = [retained_count(origin, destination, week) / weekly.loc[week, 'sum'] for week in baseline_weeks]
        diffs = np.diff(shares)
        p90 = float(np.quantile(abs(diffs), .9, method='linear'))
        ratio = abs(delta) / max(p90, .001)
        status = (
            'LOW_COUNTS' if max(reference_trips, current_trips) < 20
            else 'LOW_BASELINE_COUNTS' if sum(retained_count(origin, destination, week) for week in baseline_weeks) < 20
            else 'SMALL_SHARE_CHANGE' if abs(delta) < .001
            else 'WITHIN_WEEKLY_VARIATION' if ratio < 2
            else 'CHANGED'
        )
        expected[(int(origin), int(destination))] = dict(
            ca=reference_trips, cb=current_trips, pa=reference_share, pb=current_share,
            delta=delta, p90=p90, ratio=ratio, status=status, diffs=diffs,
        )

    # Tri : plus grand écart de part d'abord, puis identifiants.
    rank = lambda pair: (-abs(expected[pair]['delta']), pair[0], pair[1])
    qualified = sorted([pair for pair, flow in expected.items() if flow['status'] == 'CHANGED'], key=rank)
    assert response['status'] == 'COMPARABLE' and response['pairsConsidered'] == len(expected) and response['qualifiedPairs'] == len(qualified)

    for field, pairs in [
        ('increases', [pair for pair in qualified if expected[pair]['delta'] > 0]),
        ('decreases', [pair for pair in qualified if expected[pair]['delta'] < 0]),
        ('otherLargestChanges', sorted([pair for pair, flow in expected.items() if flow['status'] != 'CHANGED'], key=rank)),
    ]:
        assert [(change['origin']['id'], change['destination']['id']) for change in response[field]] == pairs[:10]
        for change in response[field]:
            origin, destination = change['origin']['id'], change['destination']['id']
            flow = expected[(origin, destination)]
            assert (change['status'] == flow['status']
                    and change['referenceCounts']['retained'] == flow['ca']
                    and change['currentCounts']['retained'] == flow['cb'])
            for response_field, key in [
                ('referenceShare', 'pa'),
                ('currentShare', 'pb'),
                ('shareChange', 'delta'),
                ('p90WeeklyChange', 'p90'),
                ('variationRatio', 'ratio'),
            ]:
                close(change[response_field], flow[key])
            close(change['percentagePointChange'], 100 * flow['delta'])
            close(change['volumeOnlyCountChange'] + change['residualCountChange'], flow['cb'] - flow['ca'])
            for baseline_week in change['baselineWeeks']:
                assert (baseline_week['counts']['retained'] == retained_count(origin, destination, baseline_week['start'])
                        and baseline_week['counts']['raw'] == raw_count(origin, destination, baseline_week['start']))
                assert sum(source['counts']['retained'] for source in baseline_week['sources']) == baseline_week['counts']['retained']

    checks.append({
        'scope': scope or 'citywide',
        'pairs': len(expected),
        'qualified': len(qualified),
        'referenceTotal': response['reference']['counts']['retained'],
        'currentTotal': response['current']['counts']['retained'],
    })

# Entrées invalides : zone inconnue, zone et borough ensemble, périodes mal alignées.
for query, status in [
    ('zoneIds=9999&' + base, 404),
    ('zoneIds=132&borough=Brooklyn&' + base, 400),
    ('zoneIds=132&' + base.replace('from=2024-01-22', 'from=2024-01-23'), 400),
    ('zoneIds=132&' + base.replace('baselineTo=2024-01-22', 'baselineTo=2024-01-29'), 400),
]:
    try:
        get(query)
        raise AssertionError('Erreur attendue')
    except urllib.error.HTTPError as error:
        assert error.code == status

# Mois absent ou historique trop court : aucun flux ne doit être annoncé.
missing = get('zoneIds=132&' + base.replace('from=2024-01-22&to=2024-01-29', 'from=2024-02-05&to=2024-02-12'))
assert missing['status'] == 'INCOMPLETE_OR_LOW_VOLUME_PERIOD' and not missing['increases'] and not missing['decreases']
short = get('zoneIds=132&' + base.replace('baselineTo=2024-01-22', 'baselineTo=2024-01-15'))
assert short['status'] == 'INSUFFICIENT_BASELINE' and not short['increases'] and not short['decreases']

print(json.dumps({'verified': True, 'sourceRows': 2964624, 'checks': checks, 'coverageAndInputChecks': True}, indent=2))
